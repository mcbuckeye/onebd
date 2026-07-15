"""Governed metric definitions and deterministic source citations."""

from __future__ import annotations

from hashlib import sha256
from typing import Optional


METRIC_DEFINITIONS = {
    "deal_count": {
        "label": "Deal count",
        "status": "supported",
        "definition": "Distinct Cortellis deal IDs satisfying the stated filters.",
        "source": "deals.id",
        "unit": "deals",
    },
    "total_projected_current": {
        "label": "Current projected total deal value",
        "status": "supported",
        "definition": "Latest disclosed projected total consideration; not an upfront or milestone value.",
        "source": "deal_finance_summary.total_projected_current_amount",
        "unit": "millions, source currency",
    },
    "total_paid": {
        "label": "Reported total paid",
        "status": "supported",
        "definition": "Cortellis-reported paid consideration; completeness varies by deal.",
        "source": "deal_finance_summary.total_paid_amount",
        "unit": "millions, source currency",
    },
    "total_projected_signing": {
        "label": "Projected total at signing",
        "status": "supported",
        "definition": "Projected aggregate consideration reported at signing; not the upfront payment.",
        "source": "deal_finance_summary.total_projected_signing_amount",
        "unit": "millions, source currency",
    },
    "upfront_payment": {
        "label": "Upfront payment",
        "status": "supported_governed_patterns",
        "definition": "Disclosed non-contingent consideration payable at signing or closing; governed analytics use projected-current, known, non-breakdown USD terms and one maximum headline term per deal.",
        "source": "deal_financial_terms (Cortellis FinanceDetail JSON; parser v4)",
        "unit": "USD millions",
    },
    "milestone_payment": {
        "label": "Milestone payment",
        "status": "supported_governed_patterns",
        "definition": "Disclosed aggregate contingent milestone potential; governed analytics use projected-current milestone totals, not component sums.",
        "source": "deal_financial_terms (Cortellis FinanceDetail JSON; parser v4)",
        "unit": "USD millions",
    },
    "royalty_rate": {
        "label": "Royalty rate",
        "status": "supported_governed_patterns",
        "definition": "Disclosed contractual sales royalty percentage or tiered range; governed analytics summarize one low/high range per deal.",
        "source": "deal_financial_terms (Cortellis FinanceDetail JSON; parser v4)",
        "unit": "percent",
    },
    "acquisition_premium": {
        "label": "Acquisition premium",
        "status": "unsupported_structured",
        "definition": "Offer price premium to unaffected pre-announcement equity value.",
        "source": None,
        "unit": "percent",
    },
}


def requested_unsupported_metric(question: str) -> Optional[str]:
    """Identify unsupported governed concepts without substituting nearby fields."""
    normalized = question.lower()
    if "acquisition premium" in normalized:
        return "acquisition_premium"
    if "upfront" in normalized or "up-front" in normalized:
        return "upfront_payment"
    if "milestone" in normalized:
        return "milestone_payment"
    if "royalt" in normalized and any(
        term in normalized for term in ("average", "median", "typical", "range", "rate")
    ):
        return "royalty_rate"
    return None


def metric_limitation(question: str) -> Optional[str]:
    metric_key = requested_unsupported_metric(question)
    if not metric_key:
        return None
    metric = METRIC_DEFINITIONS[metric_key]
    if metric_key != "acquisition_premium":
        from unified_api.services.governed_financial_queries import (
            build_governed_financial_sql,
        )

        if build_governed_financial_sql(question) is not None:
            return None
        return (
            f"{metric['label']} data is available, but this question does not "
            "match a governed analytical pattern yet. The platform will not "
            "generate an unconstrained financial-term query or substitute total "
            f"deal value. Definition: {metric['definition']}"
        )
    return (
        f"{metric['label']} analytics are not available as a governed structured "
        "metric yet. The platform will not substitute projected total deal value. "
        f"Definition: {metric['definition']}"
    )


def build_citations(mode: str, data: list[dict], query: Optional[str] = None) -> list[dict]:
    """Build stable citations from retrieved record identifiers and query provenance."""
    citations = []
    seen = set()
    source = "Cortellis" if mode in {"sql", "rag"} else "Neo4j"
    for row in data:
        if row.get("article_source") and row.get("external_id"):
            record_id = f"{row['article_source']}:{row['external_id']}"
            if record_id in seen:
                continue
            seen.add(record_id)
            citations.append({
                "id": f"C{len(citations) + 1}",
                "source": "Europe PMC",
                "record_type": "publication",
                "record_id": record_id,
                "label": row.get("title") or record_id,
            })
            if len(citations) == 10:
                break
            continue
        if row.get("nct_id"):
            record_id = row["nct_id"]
            if record_id in seen:
                continue
            seen.add(record_id)
            citations.append({
                "id": f"C{len(citations) + 1}",
                "source": "ClinicalTrials.gov",
                "record_type": "clinical_trial",
                "record_id": record_id,
                "label": row.get("brief_title") or record_id,
            })
            if len(citations) == 10:
                break
            continue
        if row.get("primary_accession"):
            record_id = str(row["primary_accession"])
            if record_id in seen:
                continue
            seen.add(record_id)
            citations.append({
                "id": f"C{len(citations) + 1}",
                "source": "UniProt",
                "record_type": "protein",
                "record_id": record_id,
                "label": (
                    row.get("protein_name") or row.get("gene_symbol") or record_id
                ),
            })
            if len(citations) == 10:
                break
            continue
        if row.get("ensembl_id"):
            record_id = "|".join(str(value) for value in (
                row.get("chembl_id"), row.get("ensembl_id"), row.get("drug_id")
            ) if value is not None)
            if record_id in seen:
                continue
            seen.add(record_id)
            citations.append({
                "id": f"C{len(citations) + 1}",
                "source": "Open Targets",
                "record_type": "drug_target",
                "record_id": record_id,
                "label": (
                    f"{row.get('drug_name') or row.get('chembl_id')} → "
                    f"{row.get('target_symbol') or row.get('ensembl_id')}"
                ),
            })
            if len(citations) == 10:
                break
            continue
        if row.get("disease_id"):
            record_id = "|".join(str(value) for value in (
                row.get("chembl_id"), row.get("disease_id"), row.get("drug_id")
            ) if value is not None)
            if record_id in seen:
                continue
            seen.add(record_id)
            citations.append({
                "id": f"C{len(citations) + 1}",
                "source": "Open Targets",
                "record_type": "drug_indication",
                "record_id": record_id,
                "label": (
                    f"{row.get('drug_name') or row.get('chembl_id')} → "
                    f"{row.get('disease_name') or row.get('disease_id')}"
                ),
            })
            if len(citations) == 10:
                break
            continue
        # Ranking/grouping rows can expose an entity ``id`` alongside an
        # aggregate count.  That ID is not a deal ID and must not be presented
        # as one; the query fingerprint below is the honest provenance.
        if (
            "deal_count" in row
            and not row.get("deal_id")
            and not row.get("contract_id")
        ):
            continue
        deal_id = row.get("deal_id") or row.get("id")
        contract_id = row.get("contract_id")
        if not deal_id or deal_id in seen:
            continue
        seen.add(deal_id)
        citation = {
            "id": f"C{len(citations) + 1}",
            "source": source,
            "record_type": "contract" if contract_id else "deal",
            "record_id": contract_id or deal_id,
            "deal_id": deal_id,
            "label": row.get("deal_title") or row.get("title") or f"Deal {deal_id}",
        }
        citations.append(citation)
        if len(citations) == 10:
            break

    if not citations and data:
        fingerprint = sha256((query or mode).encode()).hexdigest()[:12]
        citations.append({
            "id": "C1",
            "source": source,
            "record_type": "aggregate_query",
            "record_count": len(data),
            "query_fingerprint": fingerprint,
            "label": f"{source} aggregate result",
        })
    return citations


def append_citation_section(answer: str, citations: list[dict]) -> str:
    if not citations:
        return answer
    sources = []
    for citation in citations:
        suffix = f" (record {citation['record_id']})" if citation.get("record_id") else ""
        sources.append(f"[{citation['id']}] {citation['source']}: {citation['label']}{suffix}")
    return answer.rstrip() + "\n\nSources: " + "; ".join(sources)
