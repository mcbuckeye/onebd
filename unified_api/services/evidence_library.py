"""
Clinical Evidence Library service.

Manages a curated collection of clinical evidence documents:
- FDA prescribing labels
- Pivotal trial publications
- FDA briefing documents
- EMA assessment reports

Documents are indexed with PageIndex for tree-based retrieval,
enabling queries like "Compare PFS rates across BTK inhibitors."
"""
import json
from typing import Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


def store_evidence_document(
    session,
    drug_name: str,
    brand_name: str,
    doc_type: str,
    therapeutic_area: str,
    indications: list[str],
    source_url: str,
    pdf_path: Optional[str] = None,
) -> int:
    """
    Store a new evidence document in the library.

    Args:
        session: SQLAlchemy session
        drug_name: Generic drug name (e.g. "zanubrutinib")
        brand_name: Brand name (e.g. "Brukinsa")
        doc_type: One of: fda_label, publication, briefing, epar, guideline
        therapeutic_area: Drug class (e.g. "BTK inhibitor")
        indications: List of indications (e.g. ["CLL/SLL", "MCL", "WM"])
        source_url: URL where the document was obtained
        pdf_path: Local path to the PDF file

    Returns:
        The new evidence_documents.id
    """
    result = session.execute(
        text("""
            INSERT INTO evidence_documents
                (drug_name, brand_name, doc_type, therapeutic_area, indications, source_url, pdf_path)
            VALUES
                (:drug_name, :brand_name, :doc_type, :therapeutic_area,
                 CAST(:indications AS jsonb), :source_url, :pdf_path)
            ON CONFLICT (drug_name, doc_type) DO UPDATE SET
                brand_name = EXCLUDED.brand_name,
                therapeutic_area = EXCLUDED.therapeutic_area,
                indications = EXCLUDED.indications,
                source_url = EXCLUDED.source_url,
                pdf_path = EXCLUDED.pdf_path,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "drug_name": drug_name,
            "brand_name": brand_name,
            "doc_type": doc_type,
            "therapeutic_area": therapeutic_area,
            "indications": json.dumps(indications),
            "source_url": source_url,
            "pdf_path": pdf_path,
        },
    )
    session.commit()
    row = result.fetchone()
    return row.id if row else None


def get_evidence_by_drug(session, drug_name: str) -> list:
    """Get all evidence documents for a drug (by generic or brand name)."""
    return session.execute(
        text("""
            SELECT id, drug_name, brand_name, doc_type, therapeutic_area,
                   indications, source_url, pdf_path, tree_cached, created_at
            FROM evidence_documents
            WHERE drug_name ILIKE :name OR brand_name ILIKE :name
            ORDER BY doc_type
        """),
        {"name": f"%{drug_name}%"},
    ).fetchall()


def get_evidence_by_indication(session, indication: str) -> list:
    """Get all evidence documents for an indication."""
    return session.execute(
        text("""
            SELECT id, drug_name, brand_name, doc_type, therapeutic_area,
                   indications, source_url, pdf_path, tree_cached, created_at
            FROM evidence_documents
            WHERE indications::text ILIKE :indication
            ORDER BY drug_name, doc_type
        """),
        {"indication": f"%{indication}%"},
    ).fetchall()


def get_evidence_tree(session, evidence_id: int) -> Optional[dict]:
    """Get cached PageIndex tree for an evidence document."""
    row = session.execute(
        text("SELECT tree_json FROM evidence_tree_index WHERE evidence_id = :eid"),
        {"eid": evidence_id},
    ).fetchone()
    return row.tree_json if row else None


def store_evidence_tree(
    session,
    evidence_id: int,
    tree_json: dict,
    model: str,
) -> None:
    """Store a PageIndex tree for an evidence document."""
    session.execute(
        text("""
            INSERT INTO evidence_tree_index (evidence_id, tree_json, model, indexed_at)
            VALUES (:eid, CAST(:tree AS jsonb), :model, NOW())
            ON CONFLICT (evidence_id) DO UPDATE SET
                tree_json = CAST(:tree AS jsonb),
                model = :model,
                indexed_at = NOW()
        """),
        {
            "eid": evidence_id,
            "tree": json.dumps(tree_json),
            "model": model,
        },
    )
    session.commit()

    # Mark the document as tree-cached
    session.execute(
        text("UPDATE evidence_documents SET tree_cached = TRUE WHERE id = :eid"),
        {"eid": evidence_id},
    )
    session.commit()

    logger.info("Evidence tree cached", evidence_id=evidence_id, model=model)


def find_evidence_for_query(session, query: str) -> list:
    """
    Find relevant evidence documents for a clinical query.

    Searches drug names, brand names, and indications in the query text.
    """
    # Get all evidence docs and match against query terms
    all_docs = session.execute(
        text("""
            SELECT id, drug_name, brand_name, doc_type, therapeutic_area,
                   indications, source_url, pdf_path, tree_cached
            FROM evidence_documents
            ORDER BY drug_name
        """)
    ).fetchall()

    query_lower = query.lower()
    matches = []
    for doc in all_docs:
        if (doc.drug_name.lower() in query_lower
                or doc.brand_name.lower() in query_lower
                or any(ind.lower() in query_lower
                       for ind in (doc.indications or []))):
            matches.append(doc)

    return matches
