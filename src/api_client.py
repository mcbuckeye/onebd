"""Cortellis API client for fetching deal data."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Optional, List, Dict, Any, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import httpx

from .config import CortellisConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from a deal search."""
    total_results: int
    offset: int
    hits: int
    deal_ids: List[int]


@dataclass
class DealRecord:
    """Full deal record from the API."""
    id: int
    raw_xml: str
    parsed_data: Dict[str, Any]


class CortellisAPIError(Exception):
    """Exception raised for API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class CortellisClient:
    """Client for the Cortellis Deals API."""

    def __init__(self, config: CortellisConfig):
        self.config = config
        self.base_url = config.base_url
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client with digest auth."""
        if self._client is None:
            self._client = httpx.Client(
                auth=httpx.DigestAuth(self.config.username, self.config.password),
                timeout=60.0,
                follow_redirects=True,
            )
        return self._client

    def close(self):
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make an authenticated request with retry logic."""
        client = self._get_client()
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                    time.sleep(wait_time)
                    continue
                elif e.response.status_code >= 500:  # Server error
                    if attempt < max_retries - 1:
                        logger.warning(f"Server error {e.response.status_code}, retrying...")
                        time.sleep(retry_delay)
                        continue
                raise CortellisAPIError(
                    f"HTTP {e.response.status_code}: {e.response.text}",
                    status_code=e.response.status_code,
                    response_text=e.response.text,
                )
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Request error: {e}, retrying...")
                    time.sleep(retry_delay)
                    continue
                raise CortellisAPIError(f"Request failed: {e}")

        raise CortellisAPIError("Max retries exceeded")

    def search_deals(
        self,
        query: str = "*",
        offset: int = 0,
        hits: int = 100,
        sort_by: Optional[str] = None,
        fmt: str = "xml",
    ) -> SearchResult:
        """
        Search deals with pagination.

        Args:
            query: Search query (default "*" for all deals)
            offset: Number of records to skip
            hits: Number of results per page (max 100)
            sort_by: Sort expression (e.g., "-dealDateStartByMonth")
            fmt: Output format ("xml" or "json")

        Returns:
            SearchResult with total count and deal IDs
        """
        url = f"{self.base_url}/deals-v2/deal/expanded/search"
        params = {
            "query": query,
            "offset": offset,
            "hits": min(hits, 100),
            "fmt": fmt,
            "filtersEnabled": "false",
        }
        if sort_by:
            params["sortBy"] = sort_by

        response = self._request("GET", url, params=params)

        if fmt == "xml":
            return self._parse_search_xml(response.text)
        else:
            return self._parse_search_json(response.json())

    def _parse_search_xml(self, xml_text: str) -> SearchResult:
        """Parse XML search response."""
        root = ET.fromstring(xml_text)
        total = int(root.get("totalResults", 0))
        offset = int(root.get("offset", 0))
        hits = int(root.get("hits", 0))

        deal_ids = []
        for deal in root.findall(".//Deal"):
            deal_id = deal.get("id")
            if deal_id:
                deal_ids.append(int(deal_id))

        return SearchResult(
            total_results=total,
            offset=offset,
            hits=hits,
            deal_ids=deal_ids,
        )

    def _parse_search_json(self, data: Dict) -> SearchResult:
        """Parse JSON search response."""
        total = data.get("totalResults", 0)
        offset = data.get("offset", 0)
        hits = data.get("hits", 0)

        deal_ids = []
        for deal in data.get("SearchResults", {}).get("Deal", []):
            if isinstance(deal, dict) and "id" in deal:
                deal_ids.append(int(deal["id"]))

        return SearchResult(
            total_results=total,
            offset=offset,
            hits=hits,
            deal_ids=deal_ids,
        )

    def get_all_deal_ids(
        self,
        query: str = "*",
        *,
        workers: int = 1,
        initial_result: Optional[SearchResult] = None,
        sort_by: Optional[str] = None,
    ) -> Iterator[int]:
        """
        Iterate through all deal IDs matching a query.

        Args:
            query: Search query

        Yields:
            Deal IDs
        """
        hits = 100
        first = initial_result or self.search_deals(
            query=query,
            offset=0,
            hits=hits,
            sort_by=sort_by,
        )
        logger.info(
            f"Fetched deals 0 to {len(first.deal_ids)} of {first.total_results}"
        )
        yield from first.deal_ids

        offsets = list(range(hits, first.total_results, hits))
        workers = max(1, min(int(workers), 16))
        if workers > 1 and offsets:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self.search_deals,
                        query=query,
                        offset=offset,
                        hits=hits,
                        sort_by=sort_by,
                    ): offset
                    for offset in offsets
                }
                for future in as_completed(futures):
                    offset = futures[future]
                    result = future.result()
                    logger.info(
                        f"Fetched deals {offset} to "
                        f"{offset + len(result.deal_ids)} of {result.total_results}"
                    )
                    yield from result.deal_ids
            return

        for offset in offsets:
            result = self.search_deals(
                query=query,
                offset=offset,
                hits=hits,
                sort_by=sort_by,
            )
            logger.info(f"Fetched deals {offset} to {offset + len(result.deal_ids)} of {result.total_results}")
            yield from result.deal_ids
            time.sleep(0.5)  # Rate limiting

    def get_deal_record(self, deal_id: int, fmt: str = "xml") -> DealRecord:
        """
        Get a single expanded deal record.

        Args:
            deal_id: Deal ID
            fmt: Output format ("xml" or "json")

        Returns:
            DealRecord with raw and parsed data
        """
        url = f"{self.base_url}/deals-v2/deal/expanded/{deal_id}"
        params = {"fmt": fmt}

        response = self._request("GET", url, params=params)

        if fmt == "xml":
            parsed = self._parse_deal_xml(response.text)
        else:
            parsed = response.json()

        return DealRecord(
            id=deal_id,
            raw_xml=response.text if fmt == "xml" else "",
            parsed_data=parsed,
        )

    def get_deal_records(self, deal_ids: List[int], fmt: str = "xml") -> List[DealRecord]:
        """
        Get multiple expanded deal records (max 30 at a time).

        Args:
            deal_ids: List of deal IDs (max 30)
            fmt: Output format ("xml" or "json")

        Returns:
            List of DealRecords
        """
        if len(deal_ids) > 30:
            raise ValueError("Maximum 30 deal IDs per request")

        url = f"{self.base_url}/deals-v2/deals/expanded"
        params = {
            "idList": ",".join(str(id) for id in deal_ids),
            "fmt": fmt,
        }

        response = self._request("GET", url, params=params)

        if fmt == "xml":
            return self._parse_deals_xml(response.text)
        else:
            return self._parse_deals_json(response.json())

    def _parse_deal_xml(self, xml_text: str) -> Dict[str, Any]:
        """Parse a single deal XML response into a dictionary."""
        root = ET.fromstring(xml_text)
        return self._element_to_dict(root)

    def _parse_deals_xml(self, xml_text: str) -> List[DealRecord]:
        """Parse multiple deals XML response."""
        root = ET.fromstring(xml_text)
        records = []

        for deal_elem in root.findall(".//Deal"):
            deal_id = int(deal_elem.get("id", 0))
            parsed = self._element_to_dict(deal_elem)
            records.append(DealRecord(
                id=deal_id,
                raw_xml=ET.tostring(deal_elem, encoding="unicode"),
                parsed_data=parsed,
            ))

        return records

    def _parse_deals_json(self, data: Dict) -> List[DealRecord]:
        """Parse multiple deals JSON response."""
        records = []
        deals = data.get("Deal", [])
        if isinstance(deals, dict):
            deals = [deals]

        for deal in deals:
            deal_id = int(deal.get("id", 0))
            records.append(DealRecord(
                id=deal_id,
                raw_xml="",
                parsed_data=deal,
            ))

        return records

    def _element_to_dict(self, element: ET.Element) -> Dict[str, Any]:
        """Convert an XML element to a dictionary."""
        result = {}

        # Add attributes
        if element.attrib:
            result["@attributes"] = dict(element.attrib)

        # Add text content
        if element.text and element.text.strip():
            result["@text"] = element.text.strip()

        # Add children
        for child in element:
            child_data = self._element_to_dict(child)
            tag = child.tag

            if tag in result:
                # Convert to list if multiple children with same tag
                if not isinstance(result[tag], list):
                    result[tag] = [result[tag]]
                result[tag].append(child_data)
            else:
                result[tag] = child_data

        # Simplify if only text content
        if len(result) == 1 and "@text" in result:
            return result["@text"]

        return result

    def get_deal_contracts(self, deal_id: int, fmt: str = "xml") -> List[Dict[str, Any]]:
        """
        Get contract metadata for a deal.

        Args:
            deal_id: Deal ID
            fmt: Output format

        Returns:
            List of contract metadata dictionaries
        """
        url = f"{self.base_url}/deals-v2/deal/contract/{deal_id}"
        params = {"fmt": fmt}

        # The API represents a valid no-contract result as HTTP 200 with an
        # empty XML document. Every HTTP failure must propagate so a coverage
        # scan retries it instead of persisting a false negative.
        response = self._request("GET", url, params=params)

        if fmt == "xml":
            return self._parse_contracts_xml(response.text)
        else:
            return self._parse_contracts_json(response.json())

    def _parse_contracts_xml(self, xml_text: str) -> List[Dict[str, Any]]:
        """Parse contracts XML response."""
        root = ET.fromstring(xml_text)
        contracts = []

        for contract in root.findall(".//Contract"):
            contract_data = {
                "id": int(contract.get("id", 0)),
                "types": [],
                "has_pdf": False,
                "has_text": False,
                "date_filing": None,
                "date_contract": None,
                "is_redacted": False,
            }

            for type_elem in contract.findall(".//Type"):
                if type_elem.text:
                    contract_data["types"].append(type_elem.text)

            has_pdf = contract.find("HasPDF")
            if has_pdf is not None and has_pdf.text == "Y":
                contract_data["has_pdf"] = True

            has_text = contract.find("HasText")
            if has_text is not None and has_text.text == "Y":
                contract_data["has_text"] = True

            date_filing = contract.find("DateFiling")
            if date_filing is not None and date_filing.text:
                contract_data["date_filing"] = date_filing.text

            date_contract = contract.find("DateContract")
            if date_contract is not None and date_contract.text:
                contract_data["date_contract"] = date_contract.text

            is_redacted = contract.find("IsRedacted")
            if is_redacted is not None and is_redacted.text == "Y":
                contract_data["is_redacted"] = True

            contracts.append(contract_data)

        return contracts

    def _parse_contracts_json(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse contracts JSON response."""
        contracts = []
        contract_list = data.get("ContractsSummary", {}).get("Contract", [])
        if isinstance(contract_list, dict):
            contract_list = [contract_list]

        for contract in contract_list:
            contracts.append({
                "id": int(contract.get("id", 0)),
                "types": contract.get("Types", {}).get("Type", []),
                "has_pdf": contract.get("HasPDF") == "Y",
                "has_text": contract.get("HasText") == "Y",
                "date_filing": contract.get("DateFiling"),
                "date_contract": contract.get("DateContract"),
                "is_redacted": contract.get("IsRedacted") == "Y",
            })

        return contracts

    def download_contract_document(
        self,
        contract_id: int,
        fmt: str,  # "pdf" or "txt"
        output_path: str,
    ) -> bool:
        """
        Download a contract document.

        Args:
            contract_id: Contract ID
            fmt: Format ("pdf" or "txt")
            output_path: Path to save the document

        Returns:
            True if successful
        """
        url = f"{self.base_url}/deals-v2/deal/contract/document/{contract_id}"
        params = {"fmt": fmt}

        try:
            response = self._request("GET", url, params=params)

            with open(output_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Downloaded contract {contract_id} to {output_path}")
            return True
        except CortellisAPIError as e:
            logger.error(f"Failed to download contract {contract_id}: {e}")
            return False

    @staticmethod
    def build_updated_deals_query(
        since_date: datetime,
        query: str = "*",
        overlap_days: int = 2,
    ) -> str:
        """Build a date-safe incremental query.

        The Deals API filter is day-granular while local sync timestamps include
        a time. Replaying a short overlap prevents same-day updates from being
        skipped when the strict ``RANGE(>date)`` filter advances at midnight.
        Transformations are upserts, so replayed deal IDs are safe.
        """
        cutoff = since_date - timedelta(days=max(1, overlap_days))
        update_query = f"dealDateUpdate:RANGE(>{cutoff:%Y-%m-%d})"
        if query and query != "*":
            return f"({query}) AND ({update_query})"
        return update_query

    def count_updated_deals_since(
        self,
        since_date: datetime,
        query: str = "*",
        overlap_days: int = 2,
    ) -> int:
        """Return the API count for an incremental window without fetching records."""
        full_query = self.build_updated_deals_query(since_date, query, overlap_days)
        return self.search_deals(query=full_query, offset=0, hits=1).total_results

    def get_updated_deals_since(
        self,
        since_date: datetime,
        query: str = "*",
        overlap_days: int = 2,
    ) -> Iterator[int]:
        """
        Get deal IDs updated since a specific date.

        Args:
            since_date: Date to check updates from
            query: Additional query to combine with

        Yields:
            Deal IDs that have been updated
        """
        full_query = self.build_updated_deals_query(since_date, query, overlap_days)
        yield from self.get_all_deal_ids(full_query)
