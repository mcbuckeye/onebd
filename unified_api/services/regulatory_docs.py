"""
Regulatory document search service.

Framework for indexing and querying FDA briefing documents,
EMA assessment reports, and advisory committee transcripts.
"""
from typing import Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)

# Supported regulatory document types
REGULATORY_DOC_TYPES = {
    "fda_briefing": {
        "description": "FDA Briefing Document for advisory committee meeting",
        "typical_pages": "100-300",
        "source": "FDA ODAC/advisory committee meetings",
    },
    "epar": {
        "description": "European Medicines Agency Public Assessment Report",
        "typical_pages": "50-200",
        "source": "EMA website",
    },
    "advisory_committee": {
        "description": "FDA Advisory Committee transcript or summary",
        "typical_pages": "200-500",
        "source": "FDA advisory committee meetings",
    },
    "approval_letter": {
        "description": "FDA approval letter and review documents",
        "typical_pages": "10-50",
        "source": "Drugs@FDA",
    },
    "clinical_review": {
        "description": "FDA medical/clinical review of NDA/BLA",
        "typical_pages": "100-400",
        "source": "Drugs@FDA review documents",
    },
}


def search_regulatory_docs(
    session,
    drug_name: Optional[str] = None,
    doc_type: Optional[str] = None,
    therapeutic_area: Optional[str] = None,
) -> list:
    """
    Search evidence_documents for regulatory documents.

    Filters by drug name, document type, and/or therapeutic area.
    Regulatory doc types are a subset of evidence_documents.
    """
    conditions = []
    params = {}

    # Only regulatory document types
    reg_types = list(REGULATORY_DOC_TYPES.keys()) + ["fda_label"]

    if drug_name:
        conditions.append("(ed.drug_name ILIKE :drug OR ed.brand_name ILIKE :drug)")
        params["drug"] = f"%{drug_name}%"

    if doc_type:
        conditions.append("ed.doc_type = :dtype")
        params["dtype"] = doc_type
    else:
        # Filter to regulatory types only
        type_list = ", ".join(f"'{t}'" for t in reg_types)
        conditions.append(f"ed.doc_type IN ({type_list})")

    if therapeutic_area:
        conditions.append("ed.therapeutic_area ILIKE :area")
        params["area"] = f"%{therapeutic_area}%"

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    return session.execute(
        text(f"""
            SELECT id, drug_name, brand_name, doc_type, therapeutic_area,
                   indications, source_url, pdf_path, tree_cached
            FROM evidence_documents ed
            WHERE {where_clause}
            ORDER BY drug_name, doc_type
        """),
        params,
    ).fetchall()
