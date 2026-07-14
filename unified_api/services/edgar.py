"""
SEC EDGAR ingestion service

Implements SEC fair access policy:
- User-Agent header with company name and email
- Max 10 requests per second
- Exponential backoff on 429 errors

Imported from Edgar BD project and adapted for unified platform.
"""
import asyncio
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import List, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


def is_priority_form(form: str, priority_forms: Optional[List[str]] = None) -> bool:
    """Return whether a filing form (including amendments) is deal-relevant."""
    normalized = (form or "").strip().upper()
    base_form = normalized[:-2] if normalized.endswith("/A") else normalized
    allowed = {value.upper() for value in (priority_forms or EDGARClient.PRIORITY_FORMS)}
    return normalized in allowed or base_form in allowed


def parse_master_index(content: str) -> List[dict]:
    """Parse an SEC daily ``master.idx`` file into filing metadata."""
    filings = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.count("|") != 4:
            continue

        cik, company_name, form, filed_on, filename = [part.strip() for part in line.split("|", 4)]
        if not cik.isdigit() or not filename.lower().endswith(".txt"):
            continue

        try:
            date_format = "%Y-%m-%d" if "-" in filed_on else "%Y%m%d"
            filing_date = datetime.strptime(filed_on, date_format).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        accession_match = re.search(r"(\d{10}-\d{2}-\d{6})\.txt$", filename)
        if not accession_match:
            continue

        filings.append({
            "cik": cik.lstrip("0") or "0",
            "company_name": company_name,
            "form": form,
            "filing_date": filing_date,
            "accession_number": accession_match.group(1),
            "filename": filename,
            "url": f"https://www.sec.gov/Archives/{filename.lstrip('/')}",
        })

    return filings


class FilingIndexParser(HTMLParser):
    """Parser for SEC filing index pages to extract exhibit information"""

    # Exhibit types we want to capture
    PRIORITY_EXHIBITS = {
        "EX-99.1", "EX-99.2", "EX-99.3",  # Press releases, news
        "EX-10.1", "EX-10.2", "EX-10.3", "EX-10.4", "EX-10.5",  # Material contracts
        "EX-2.1", "EX-2.2",  # Plans of acquisition
        "EX-4.1", "EX-4.2",  # Instruments defining rights
    }

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.rows = []
        self.cell_data = ""
        self.cell_link = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            for name, value in attrs:
                if name == "summary" and "Document" in value:
                    self.in_table = True
                    break
            else:
                if not self.in_table:
                    self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag == "td" and self.in_row:
            self.in_cell = True
            self.cell_data = ""
            self.cell_link = ""
        elif tag == "a" and self.in_cell:
            for name, value in attrs:
                if name == "href":
                    self.cell_link = value

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row and len(self.current_row) >= 4:
                self.rows.append(self.current_row)
        elif tag == "td" and self.in_cell:
            self.in_cell = False
            self.current_row.append({
                "text": self.cell_data.strip(),
                "link": self.cell_link
            })

    def handle_data(self, data):
        if self.in_cell:
            self.cell_data += data

    def get_exhibits(self) -> List[dict]:
        """Extract exhibit documents from parsed rows"""
        exhibits = []

        for row in self.rows:
            if len(row) < 4:
                continue

            doc_type = row[3]["text"].strip().upper()

            if not any(doc_type.startswith(ex.replace(".", "")) or doc_type == ex
                      for ex in self.PRIORITY_EXHIBITS):
                if not re.match(r"EX-(?:99|10|2|4)\.", doc_type):
                    continue

            doc_link = ""
            for cell in row:
                if cell["link"] and ("/Archives/" in cell["link"] or cell["link"].endswith(".htm")):
                    doc_link = cell["link"]
                    break

            if not doc_link:
                continue

            if doc_link.endswith((".xml", ".xsd", ".json")):
                continue

            description = row[1]["text"].strip() if len(row) > 1 else ""

            exhibits.append({
                "doc_type": doc_type,
                "description": description,
                "url": doc_link,
            })

        return exhibits


class EDGARClient:
    """SEC EDGAR API client with rate limiting"""

    BASE_URL = "https://data.sec.gov"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions"
    ARCHIVES_URL = "https://www.sec.gov/Archives"

    # Filing types we care about (deal-relevant)
    PRIORITY_FORMS = ["8-K", "10-K", "10-Q", "20-F", "6-K", "S-1", "F-1", "425", "SC 13D", "SC 13G"]

    # 8-K items that often contain deal information
    DEAL_ITEMS = [
        "1.01",  # Entry into Material Definitive Agreement
        "2.01",  # Completion of Acquisition or Disposition of Assets
        "8.01",  # Other Events (often used for deals)
    ]

    # Default user agent - should be overridden in settings
    DEFAULT_USER_AGENT = "BD-Intelligence-Platform admin@example.com"

    def __init__(self, user_agent: Optional[str] = None, rate_limit: int = 10):
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.rate_limit = rate_limit

        # Validate user agent (SEC requires company name and email)
        if "example.com" in self.user_agent or "@" not in self.user_agent:
            logger.warning(
                "EDGAR_USER_AGENT appears to be a placeholder. "
                "Please update with your company info to comply with SEC policy."
            )

        # Rate limiting state
        self._last_request_time = 0.0
        self._min_interval = 1.0 / self.rate_limit

        logger.info(
            "EDGAR client initialized",
            rate_limit=self.rate_limit,
            user_agent=self.user_agent[:50] + "...",
        )

    async def _rate_limited_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a rate-limited request to SEC EDGAR"""

        # Wait if needed to respect rate limit
        now = asyncio.get_event_loop().time()
        time_since_last = now - self._last_request_time

        if time_since_last < self._min_interval:
            wait_time = self._min_interval - time_since_last
            await asyncio.sleep(wait_time)

        # Make request with retries on 429 and network errors
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await client.get(url, **kwargs)

                if response.status_code == 429:
                    logger.warning(
                        "Rate limited by SEC, backing off",
                        attempt=attempt + 1,
                        delay=retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                response.raise_for_status()
                self._last_request_time = asyncio.get_event_loop().time()
                return response

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "HTTP error during request",
                    url=url,
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                    error=str(e)
                )
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                logger.warning(
                    "Network error during request",
                    url=url,
                    attempt=attempt + 1,
                    error_type=type(e).__name__,
                    error=str(e)
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise Exception(f"Failed after {max_retries} retries: {type(e).__name__}: {str(e)}")

        raise Exception(f"Failed after {max_retries} retries")

    async def _iter_submission_pages(
        self,
        client: httpx.AsyncClient,
        cik_padded: str,
        headers: dict,
    ):
        """
        Iterate through all submission pages for a company.
        SEC paginates historical filings in separate JSON files.
        """
        url = f"{self.SUBMISSIONS_URL}/CIK{cik_padded}.json"
        response = await self._rate_limited_request(client, url, headers=headers)
        root = response.json()
        yield root

        files = root.get("filings", {}).get("files", []) or []
        for file_entry in files:
            file_name = file_entry.get("name", "")
            if not file_name:
                continue

            if file_name.startswith("http"):
                page_url = file_name
            else:
                page_url = f"{self.SUBMISSIONS_URL}/{file_name}"

            logger.info("Fetching historical page", url=page_url)
            page_response = await self._rate_limited_request(client, page_url, headers=headers)
            yield page_response.json()

    async def get_company_filings(
        self,
        cik: str,
        forms: Optional[List[str]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Get filings for a company (with pagination support)

        Args:
            cik: Company CIK (will be zero-padded to 10 digits)
            forms: List of form types to filter (default: PRIORITY_FORMS)
            date_from: Filter filings from this date
            date_to: Filter filings to this date

        Returns:
            List of filing metadata dicts
        """
        cik_padded = cik.lstrip("0").zfill(10)

        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}

        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                filings = []
                allowed_forms = forms if forms is not None else self.PRIORITY_FORMS

                async for page_data in self._iter_submission_pages(client, cik_padded, headers):
                    recent = page_data.get("filings", {}).get("recent", {})

                    if not recent:
                        continue

                    filing_count = len(recent.get("accessionNumber", []))

                    for i in range(filing_count):
                        form = recent["form"][i]

                        if not is_priority_form(form, allowed_forms):
                            continue

                        filing_date_str = recent["filingDate"][i]
                        filing_date_naive = datetime.strptime(filing_date_str, "%Y-%m-%d")
                        filing_date = filing_date_naive.replace(tzinfo=timezone.utc)

                        if date_from and filing_date < date_from:
                            continue
                        if date_to and filing_date > date_to:
                            continue

                        accession_no = recent["accessionNumber"][i]
                        primary_doc = recent.get("primaryDocument", [None] * filing_count)[i]

                        accession_no_nodash = accession_no.replace("-", "")
                        cik_no_pad = cik.lstrip("0")

                        if primary_doc:
                            doc_url = (
                                f"https://www.sec.gov/Archives/edgar/data/"
                                f"{cik_no_pad}/{accession_no_nodash}/{primary_doc}"
                            )
                        else:
                            doc_url = (
                                f"https://www.sec.gov/cgi-bin/viewer?"
                                f"action=view&cik={cik_no_pad}&"
                                f"accession_number={accession_no}&"
                                f"xbrl_type=v"
                            )

                        filings.append(
                            {
                                "cik": cik_padded,
                                "form": form,
                                "filing_date": filing_date,
                                "accession_number": accession_no,
                                "url": doc_url,
                                "primary_document": primary_doc,
                            }
                        )

                logger.info(
                    "Retrieved company filings",
                    cik=cik_padded,
                    total_filings=len(filings),
                    forms=forms,
                )

                return filings

            except Exception as e:
                logger.error("Failed to fetch EDGAR filings", cik=cik_padded, error=str(e))
                raise

    async def get_daily_index(self, filing_date: date) -> List[dict]:
        """Fetch and parse the SEC daily master index for a filing date.

        Weekends and SEC holidays do not have index files; those dates return an
        empty list so an incremental cursor can advance normally.
        """
        quarter = ((filing_date.month - 1) // 3) + 1
        url = (
            f"{self.ARCHIVES_URL}/edgar/daily-index/{filing_date.year}/"
            f"QTR{quarter}/master.{filing_date:%Y%m%d}.idx"
        )
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            try:
                response = await self._rate_limited_request(client, url, headers=headers)
            except httpx.HTTPStatusError as exc:
                # The Archives service commonly returns 403 (rather than 404)
                # for weekends and holidays where no index object exists.
                if exc.response.status_code in {403, 404}:
                    logger.info("No EDGAR daily index for date", filing_date=str(filing_date))
                    return []
                raise

        filings = parse_master_index(response.text)
        if "CIK|Company Name|Form Type" in response.text and not filings:
            raise ValueError(f"SEC daily index could not be parsed for {filing_date}")
        logger.info(
            "Retrieved EDGAR daily index",
            filing_date=str(filing_date),
            filings=len(filings),
        )
        return filings

    async def download_filing(
        self,
        url: str,
        timeout: float = 60.0,
    ) -> bytes:
        """Download a filing document"""
        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await self._rate_limited_request(client, url, headers=headers)
                return response.content

            except Exception as e:
                logger.error("Failed to download filing", url=url, error=str(e))
                raise

    async def get_filing_exhibits(
        self,
        cik: str,
        accession_number: str,
    ) -> List[dict]:
        """
        Get exhibits for a specific filing by fetching and parsing the index page.

        Args:
            cik: Company CIK (will be normalized)
            accession_number: Filing accession number (e.g., "0001140361-25-042607")

        Returns:
            List of exhibit dicts with doc_type, description, url
        """
        cik_no_pad = cik.lstrip("0")
        accession_no_nodash = accession_number.replace("-", "")
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_no_pad}/{accession_no_nodash}/{accession_number}-index.htm"
        )

        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await self._rate_limited_request(client, index_url, headers=headers)
                html_content = response.text

                parser = FilingIndexParser()
                parser.feed(html_content)
                exhibits = parser.get_exhibits()

                base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_pad}/{accession_no_nodash}/"
                for exhibit in exhibits:
                    url = exhibit["url"]
                    if url.startswith("/"):
                        exhibit["url"] = f"https://www.sec.gov{url}"
                    elif not url.startswith("http"):
                        exhibit["url"] = base_url + url

                logger.debug(
                    "Found exhibits in filing",
                    accession=accession_number,
                    exhibit_count=len(exhibits),
                    exhibits=[e["doc_type"] for e in exhibits],
                )

                return exhibits

            except Exception as e:
                logger.warning(
                    "Failed to fetch filing exhibits",
                    accession=accession_number,
                    error=str(e),
                )
                return []


# Global client instance
_edgar_client: Optional[EDGARClient] = None


def get_edgar_client(user_agent: Optional[str] = None) -> EDGARClient:
    """Get or create the EDGAR client"""
    global _edgar_client

    if _edgar_client is None:
        _edgar_client = EDGARClient(user_agent=user_agent)

    return _edgar_client
