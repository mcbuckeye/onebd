"""Incremental SEC EDGAR ingestion using the daily master indexes.

The service deliberately uses one daily index request per date instead of one
submissions request per tracked company.  This keeps the crawler within the SEC
fair-access limits while still discovering filings for every company already in
the EDGAR database.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import structlog
from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.chunk import get_chunker
from unified_api.services.database import get_edgar_session
from unified_api.services.edgar import EDGARClient, get_edgar_client, is_priority_form
from unified_api.services.embed import embed_texts
from unified_api.services.parse import DocumentParser, parse_document

logger = structlog.get_logger(__name__)

PRIORITY_EXHIBIT_RE = re.compile(r"^EX-(?:99|10|2|4)(?:\.|$)", re.IGNORECASE)
DOCUMENT_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)


@dataclass
class SyncWindow:
    start: date
    end: date


def normalize_cik(value: str) -> Optional[str]:
    """Normalize a CIK to its unpadded numeric representation."""
    digits = re.sub(r"\D", "", value or "")
    return (digits.lstrip("0") or "0") if digits else None


def calculate_sync_window(
    cursor: date,
    target: date,
    batch_days: int,
    overlap_days: int,
) -> SyncWindow:
    """Calculate the next bounded backfill window.

    Once caught up, a short overlap is intentionally replayed. Persistence is
    idempotent, and replaying recent indexes catches late SEC index corrections.
    """
    batch_days = max(1, batch_days)
    overlap_days = max(1, overlap_days)

    if cursor < target:
        start = cursor + timedelta(days=1)
    else:
        start = target - timedelta(days=overlap_days - 1)

    end = min(target, start + timedelta(days=batch_days - 1))
    return SyncWindow(start=start, end=end)


def _sgml_field(block: str, name: str) -> Optional[str]:
    match = re.search(rf"<{name}>\s*([^\r\n<]+)", block, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_submission_documents(payload: bytes, parent_form: str) -> list[dict]:
    """Extract the primary filing and deal-relevant exhibits from SEC SGML."""
    decoded = payload.decode("latin-1", errors="ignore")
    extracted = []
    primary_form = (parent_form or "").strip().upper()
    primary_base = primary_form[:-2] if primary_form.endswith("/A") else primary_form

    for block in DOCUMENT_RE.findall(decoded):
        doc_type = (_sgml_field(block, "TYPE") or "").upper()
        doc_base = doc_type[:-2] if doc_type.endswith("/A") else doc_type
        is_primary = doc_type == primary_form or doc_base == primary_base
        is_priority_exhibit = bool(PRIORITY_EXHIBIT_RE.match(doc_type))
        if not is_primary and not is_priority_exhibit:
            continue

        text_match = re.search(r"<TEXT>(.*?)</TEXT>", block, re.IGNORECASE | re.DOTALL)
        if not text_match:
            continue

        content = text_match.group(1).strip()
        if not content or content.upper().startswith("<PDF>"):
            continue

        extracted.append({
            "doc_type": doc_type or primary_form,
            "filename": _sgml_field(block, "FILENAME"),
            "description": _sgml_field(block, "DESCRIPTION"),
            "content": content.encode("latin-1", errors="ignore"),
            "is_primary": is_primary,
        })

    # Some older submissions do not have well-formed DOCUMENT wrappers. Keep a
    # searchable primary document rather than silently dropping the filing.
    if not extracted:
        extracted.append({
            "doc_type": primary_form or "FILING",
            "filename": None,
            "description": primary_form or "SEC filing",
            "content": payload,
            "is_primary": True,
        })

    return extracted


class EDGARIngestionService:
    """Discover, download, parse, chunk, and embed new tracked-company filings."""

    def __init__(
        self,
        client: Optional[EDGARClient] = None,
        session_context: Callable = get_edgar_session,
        embedding_function: Callable = embed_texts,
        storage_dir: Optional[str] = None,
        embed_chunks: Optional[bool] = None,
    ):
        self.client = client or get_edgar_client(settings.edgar_user_agent)
        self.session_context = session_context
        self.embedding_function = embedding_function
        self.storage_dir = Path(storage_dir or settings.edgar_storage_dir)
        self.embed_chunks = settings.edgar_sync_embed if embed_chunks is None else embed_chunks

    def ensure_sync_state(self, initial_target: date) -> None:
        """Create and seed the singleton sync cursor used for zero-result days."""
        with self.session_context() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS edgar_sync_state (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    last_index_date DATE NOT NULL,
                    last_run_at TIMESTAMPTZ,
                    status TEXT NOT NULL DEFAULT 'never',
                    indexes_checked INTEGER NOT NULL DEFAULT 0,
                    filings_seen INTEGER NOT NULL DEFAULT 0,
                    filings_fetched INTEGER NOT NULL DEFAULT 0,
                    documents_created INTEGER NOT NULL DEFAULT 0,
                    chunks_created INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                )
            """))
            latest_loaded = session.execute(text("""
                SELECT MAX(filing_date::date)
                FROM raw_documents
                WHERE source_type = 'edgar'
                  AND storage_path IS NOT NULL
            """)).scalar()
            initial_cursor = latest_loaded or (initial_target - timedelta(days=1))
            session.execute(text("""
                INSERT INTO edgar_sync_state (id, last_index_date)
                VALUES (1, :initial_cursor)
                ON CONFLICT (id) DO NOTHING
            """), {"initial_cursor": initial_cursor})

    def get_cursor(self) -> date:
        with self.session_context() as session:
            return session.execute(text(
                "SELECT last_index_date FROM edgar_sync_state WHERE id = 1"
            )).scalar_one()

    def load_tracked_companies(self) -> dict[str, int]:
        with self.session_context() as session:
            rows = session.execute(text(
                "SELECT id, cik FROM companies WHERE cik IS NOT NULL AND cik <> ''"
            )).fetchall()

        companies = {}
        for row in rows:
            normalized = normalize_cik(row.cik)
            if normalized:
                companies[normalized] = row.id
        return companies

    def mark_running(self) -> None:
        with self.session_context() as session:
            session.execute(text("""
                UPDATE edgar_sync_state
                SET last_run_at = NOW(), status = 'running', indexes_checked = 0,
                    filings_seen = 0, filings_fetched = 0, documents_created = 0,
                    chunks_created = 0, error_message = NULL
                WHERE id = 1
            """))

    def advance_cursor(self, completed_date: date) -> None:
        with self.session_context() as session:
            session.execute(text("""
                UPDATE edgar_sync_state SET last_index_date = :completed_date WHERE id = 1
            """), {"completed_date": completed_date})

    def finish(self, status: str, stats: dict, error: Optional[str] = None) -> None:
        with self.session_context() as session:
            session.execute(text("""
                UPDATE edgar_sync_state
                SET status = :status, indexes_checked = :indexes_checked,
                    filings_seen = :filings_seen, filings_fetched = :filings_fetched,
                    documents_created = :documents_created, chunks_created = :chunks_created,
                    error_message = :error
                WHERE id = 1
            """), {**stats, "status": status, "error": error})

    def filing_is_known(self, accession_number: str, form: str) -> bool:
        with self.session_context() as session:
            return bool(session.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM documents
                    WHERE accession_no = :accession_number AND subtype = :form
                )
            """), {"accession_number": accession_number, "form": form}).scalar())

    def _document_url(self, filing: dict, filename: Optional[str]) -> str:
        if not filename:
            return filing["url"]
        accession = filing["accession_number"].replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{filing['cik']}/"
            f"{accession}/{filename.lstrip('/')}"
        )

    def _store_content(self, content: bytes, filename: Optional[str]) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        suffix = Path(filename or "filing.txt").suffix.lower()
        if suffix not in {".htm", ".html", ".txt", ".xml"}:
            suffix = ".txt"
        relative = Path("filings") / digest[:2] / f"{digest}{suffix}"
        destination = self.storage_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(content)
        return digest, str(relative)

    async def _prepare_document(self, content: bytes, filename: Optional[str]) -> Optional[dict]:
        lower_name = (filename or "").lower()
        looks_html = lower_name.endswith((".htm", ".html")) or b"<html" in content[:4096].lower()
        mime = "text/html" if looks_html else "text/plain"
        parsed_text, parse_metadata = parse_document(content, mime)
        if not parsed_text or not parsed_text.strip():
            return None

        sections = DocumentParser.extract_sections(parsed_text)
        chunks = get_chunker().chunk_document_by_sections(sections)
        vectors = [None] * len(chunks)

        if self.embed_chunks and chunks:
            try:
                vectors = await self.embedding_function([chunk.text for chunk in chunks])
            except Exception as exc:
                logger.warning(
                    "EDGAR embedding failed; retaining full-text chunks",
                    error=str(exc),
                    chunks=len(chunks),
                )

        return {
            "text": parsed_text,
            "mime": mime,
            "parse_metadata": parse_metadata,
            "sections": sections,
            "chunks": chunks,
            "vectors": vectors,
        }

    async def persist_document(
        self,
        filing: dict,
        company_id: int,
        extracted: dict,
    ) -> dict:
        content = extracted["content"]
        filename = extracted.get("filename")
        document_url = self._document_url(filing, filename)
        content_sha, storage_path = self._store_content(content, filename)
        prepared = await self._prepare_document(content, filename)
        if not prepared:
            return {"created": False, "chunks": 0, "embedded": 0}

        metadata = {
            "accession_number": filing["accession_number"],
            "form_type": extracted["doc_type"],
            "parent_form": filing["form"],
            "company_name": filing.get("company_name"),
            "status": "indexed",
        }
        canonical_sha = hashlib.sha256(prepared["text"].encode("utf-8")).hexdigest()
        section_path = json.dumps([name for name, _ in prepared["sections"]])

        with self.session_context() as session:
            existing = session.execute(text("""
                SELECT id FROM raw_documents WHERE url = :url OR sha256 = :sha LIMIT 1
            """), {"url": document_url, "sha": content_sha}).fetchone()
            if existing:
                return {"created": False, "chunks": 0, "embedded": 0}

            raw_id = session.execute(text("""
                INSERT INTO raw_documents (
                    company_id, source_type, url, fetched_at, filing_date,
                    mime, sha256, storage_path, filing_metadata
                ) VALUES (
                    :company_id, 'edgar', :url, NOW(), :filing_date,
                    :mime, :sha, :storage_path, CAST(:metadata AS jsonb)
                ) RETURNING id
            """), {
                "company_id": company_id,
                "url": document_url,
                "filing_date": filing["filing_date"],
                "mime": prepared["mime"],
                "sha": content_sha,
                "storage_path": storage_path,
                "metadata": json.dumps(metadata),
            }).scalar_one()

            document_id = session.execute(text("""
                INSERT INTO documents (
                    raw_document_id, doc_type, subtype, title, published_at,
                    accession_no, section_path, canonical_text_sha, parse_ok,
                    parse_notes, chunking_attempted
                ) VALUES (
                    :raw_id, 'filing', :subtype, :title, :published_at,
                    :accession, CAST(:section_path AS jsonb), :canonical_sha, TRUE,
                    NULL, TRUE
                ) RETURNING id
            """), {
                "raw_id": raw_id,
                "subtype": extracted["doc_type"],
                "title": extracted.get("description") or extracted["doc_type"],
                "published_at": filing["filing_date"],
                "accession": filing["accession_number"],
                "section_path": section_path,
                "canonical_sha": canonical_sha,
            }).scalar_one()

            session.execute(text("""
                INSERT INTO doc_text (document_id, text, lang, char_count)
                VALUES (:document_id, :text, 'en', :char_count)
            """), {
                "document_id": document_id,
                "text": prepared["text"],
                "char_count": len(prepared["text"]),
            })

            embedded = 0
            for chunk, vector in zip(prepared["chunks"], prepared["vectors"]):
                vector_value = None
                if vector is not None:
                    vector_value = "[" + ",".join(str(value) for value in vector) + "]"
                    embedded += 1
                session.execute(text("""
                    INSERT INTO chunks (
                        document_id, section, chunk_index, text, token_count, vector
                    ) VALUES (
                        :document_id, :section, :chunk_index, :text, :token_count,
                        CAST(:vector AS vector)
                    )
                """), {
                    "document_id": document_id,
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "token_count": chunk.token_count,
                    "vector": vector_value,
                })

        return {
            "created": True,
            "chunks": len(prepared["chunks"]),
            "embedded": embedded,
        }

    async def process_filing(self, filing: dict, company_id: int) -> dict:
        if self.filing_is_known(filing["accession_number"], filing["form"]):
            return {"status": "known", "documents": 0, "chunks": 0, "embedded": 0}

        payload = await self.client.download_filing(filing["url"])
        extracted_documents = extract_submission_documents(payload, filing["form"])
        totals = {"documents": 0, "chunks": 0, "embedded": 0}

        for extracted in extracted_documents:
            result = await self.persist_document(filing, company_id, extracted)
            if result["created"]:
                totals["documents"] += 1
                totals["chunks"] += result["chunks"]
                totals["embedded"] += result["embedded"]

        return {"status": "fetched", **totals}

    async def sync_incremental(
        self,
        now: Optional[datetime] = None,
        batch_days: Optional[int] = None,
        overlap_days: Optional[int] = None,
        max_filings: Optional[int] = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        target = now.date() - timedelta(days=1)
        batch_days = batch_days or settings.edgar_sync_batch_days
        overlap_days = overlap_days or settings.edgar_sync_overlap_days
        max_filings = max_filings or settings.edgar_sync_max_filings

        self.ensure_sync_state(target)
        cursor = self.get_cursor()
        window = calculate_sync_window(cursor, target, batch_days, overlap_days)
        companies = self.load_tracked_companies()
        stats = {
            "indexes_checked": 0,
            "filings_seen": 0,
            "filings_fetched": 0,
            "documents_created": 0,
            "chunks_created": 0,
        }
        embedded_chunks = 0
        status = "completed"
        error = None
        self.mark_running()

        logger.info(
            "Starting incremental EDGAR sync",
            cursor=str(cursor),
            start=str(window.start),
            end=str(window.end),
            tracked_companies=len(companies),
            max_filings=max_filings,
        )

        current = window.start
        while current <= window.end:
            try:
                daily_filings = await self.client.get_daily_index(current)
                stats["indexes_checked"] += 1
                matched = [
                    filing for filing in daily_filings
                    if normalize_cik(filing["cik"]) in companies
                    and is_priority_form(filing["form"])
                ]
                stats["filings_seen"] += len(matched)

                date_failed = False
                limit_reached = False
                for filing in matched:
                    normalized_cik = normalize_cik(filing["cik"])
                    if self.filing_is_known(filing["accession_number"], filing["form"]):
                        continue
                    if stats["filings_fetched"] >= max_filings:
                        limit_reached = True
                        break

                    try:
                        result = await self.process_filing(filing, companies[normalized_cik])
                    except Exception as exc:
                        logger.error(
                            "Failed to ingest EDGAR filing",
                            accession=filing["accession_number"],
                            error=str(exc),
                        )
                        error = f"{filing['accession_number']}: {exc}"
                        date_failed = True
                        break

                    if result["status"] == "fetched":
                        stats["filings_fetched"] += 1
                        stats["documents_created"] += result["documents"]
                        stats["chunks_created"] += result["chunks"]
                        embedded_chunks += result["embedded"]

                if date_failed or limit_reached:
                    status = "partial"
                    if limit_reached:
                        error = f"Per-run filing limit ({max_filings}) reached"
                    break

                self.advance_cursor(current)
                current += timedelta(days=1)

            except Exception as exc:
                status = "failed"
                error = str(exc)
                logger.error("EDGAR daily index sync failed", filing_date=str(current), error=error)
                break

        self.finish(status, stats, error)
        result = {
            "status": status,
            "window_start": str(window.start),
            "window_end": str(window.end),
            **stats,
            "embedded_chunks": embedded_chunks,
        }
        if error:
            result["error"] = error
        logger.info("Incremental EDGAR sync complete", **result)
        return result


async def run_edgar_sync(**kwargs) -> dict:
    """Entrypoint used by Celery and management scripts."""
    return await EDGARIngestionService().sync_incremental(**kwargs)
