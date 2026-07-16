"""
SQL database tool for querying Cortellis and Edgar databases.
"""
from typing import Callable, Optional
from sqlalchemy import text
import structlog

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class SQLTool(BaseTool):
    """Tool for querying SQL databases (PostgreSQL)."""

    SCHEMA_DESCRIPTION = """
    Cortellis PostgreSQL Database - ACTUAL SCHEMA (introspected from DB):

    Table: deals
      id: integer (PRIMARY KEY)
      title: text (deal headline, searchable with ILIKE)
      deal_type: character varying (License, Collaboration, etc.)
      status: character varying (Active, Terminated, etc.)
      is_optional: boolean
      is_merger_acquisition: boolean
      has_contract: boolean
      therapy_area_id: integer
      date_start: timestamp (deal start date)
      date_end: timestamp (deal end date)
      date_event_most_recent: timestamp
      date_change_last: timestamp
      date_added: timestamp
      summary: text (detailed description)
      agreement_type: character varying
      asset_type: character varying
      transaction_type: character varying
      phase_highest_start: character varying (Phase 1, Phase 2, Phase 3, etc.)
      phase_highest_now: character varying
      category_raw: jsonb (JSON data)
      cross_references_raw: jsonb (JSON cross-references)
      
      IMPORTANT: deals table does NOT contain financial data (no value, amount, upfront, milestone, royalty columns)

    Table: companies
      id: integer (PRIMARY KEY)
      name: character varying (company name, searchable)
      company_type: character varying
      hq_location: character varying
      cik: character varying (SEC CIK number)
      ticker: character varying (stock symbol)

    Table: therapy_areas
      id: integer (PRIMARY KEY)
      name: character varying (for example, Cancer)
      Join with deals.therapy_area_id = therapy_areas.id. Do not infer a
      therapy area by requiring words to appear in the deal title.

    Table: deal_finance_summary
      deal_id: integer (PRIMARY KEY, foreign key to deals.id)
      total_projected_current_amount: double precision
      total_projected_current_currency: character varying
      total_projected_current_unit: character varying
      total_projected_current_disclosure_status: character varying
      total_projected_signing_amount: double precision
      total_paid_amount: double precision
      Financial values are stored here, not in deals.category_raw. Compare
      current projected totals only when currency='USD' and unit='Million',
      and describe them as projected headline totals rather than realized cash.

    Table: deal_technologies
      deal_id: integer
      technology_id: integer

    Table: technologies
      id: integer (PRIMARY KEY)
      name: character varying (structured modality/technology label)
      Join through deal_technologies for modality questions such as ADC.

    Table: deal_indications
      deal_id: integer
      indication_id: integer

    Table: indications
      id: integer (PRIMARY KEY)
      name: character varying

    Table: deal_companies
      deal_id: integer
      company_id: integer
      role: character varying ('Principal' or 'Partner')

    Table: deal_drugs
      deal_id: integer
      drug_id: integer

    Table: drugs
      id: integer (PRIMARY KEY)
      name_display: character varying
      phase_highest_start: character varying
      phase_highest_now: character varying

    Table: cortellis_deal_sources
      deal_id: integer (foreign key to deals.id)
      source_id: character varying (Cortellis citation identifier)
      source_type: character varying (citation/source category)
      is_current: boolean (true for the latest source response)

    Exact public evidence tables:
    - clinical_trials: nct_id, brief_title, overall_status, phases,
      primary_completion_date, lead_sponsor_name, source_url
    - clinical_trial_drugs: nct_id, drug_id, matched_alias, match_method,
      confidence (trial-to-drug, not deal-specific)
    - deal_clinical_trial_links: deal_id, nct_id, link_method, source_type,
      source_record_id, source_sha256, source_excerpt, parser_version
    - drug_identifiers: drug_id, identifier_type, identifier_value, source,
      source_reference, confidence, review_status
    - public_drug_profiles: drug_id, chembl_id, name, drug_type,
      maximum_clinical_stage, source, source_version, source_url
    - public_targets: ensembl_id, approved_symbol, approved_name, biotype,
      protein_ids, source, source_version
    - public_target_uniprot_records: ensembl_id, requested_accession,
      primary_accession, uniprot_id, protein_name, gene_symbol, function_text,
      disease_annotations, subcellular_locations, sequence_length, source,
      source_version, source_url
    - public_literature_records: article_source, external_id, pmid, pmcid,
      doi, title, abstract_text, journal_title, publication_year,
      first_publication_date, cited_by_count, is_open_access, source,
      source_version, source_url
    - public_target_literature_links: ensembl_id, requested_accession,
      article_source, external_id, match_method, source_query, source,
      source_version
    - public_drug_target_links: drug_id, chembl_id, ensembl_id,
      mechanism_of_action, action_type, source, source_version
    - public_diseases: disease_id, name, source, source_version
    - public_drug_disease_links: drug_id, chembl_id, disease_id,
      maximum_clinical_stage, source, source_version

    Use deal_clinical_trial_links for deal-specific trial claims; never create a
    deal-to-trial claim merely because a deal and trial share a drug or disease.
    Join UniProt records to targets through ensembl_id and literature through
    public_target_literature_links. Never infer links from titles, abstracts,
    descriptions, or other free text.

    PostgreSQL Syntax Rules:
    - Use ILIKE for case-insensitive search: title ILIKE '%oncology%'
    - Boolean checks: is_merger_acquisition = true
    - JSONB access: cross_references_raw->>'key'
    - Date comparison: date_start >= '2020-01-01'::timestamp
    - LIMIT for large result sets

    Example queries:
    - Oncology deals: "SELECT d.id, d.title, d.status FROM deals d JOIN therapy_areas ta ON ta.id=d.therapy_area_id WHERE ta.name='Cancer' LIMIT 10"
    - Disclosed ADC oncology deals: "SELECT DISTINCT d.id, d.title, f.total_projected_current_amount FROM deals d JOIN therapy_areas ta ON ta.id=d.therapy_area_id JOIN deal_technologies dt ON dt.deal_id=d.id JOIN technologies t ON t.id=dt.technology_id JOIN deal_finance_summary f ON f.deal_id=d.id WHERE ta.name='Cancer' AND (t.name ILIKE '%antibody%drug%conjugate%' OR LOWER(t.name) ~ '(^|[^a-z])adc([^a-z]|$)') AND f.total_projected_current_amount IS NOT NULL AND f.total_projected_current_currency='USD' AND f.total_projected_current_unit='Million' ORDER BY f.total_projected_current_amount DESC LIMIT 20"
    - Phase 3 deals: "SELECT title, phase_highest_start FROM deals WHERE phase_highest_start = 'Phase 3' ORDER BY date_start DESC LIMIT 20"
    - Find Pfizer: "SELECT name, ticker, company_type FROM companies WHERE name ILIKE '%pfizer%'"
    - M&A deals: "SELECT title, deal_type FROM deals WHERE is_merger_acquisition = true LIMIT 10"
    """

    def __init__(
        self,
        session_factory: Optional[Callable] = None,
        connection_string: Optional[str] = None,
        max_retries: int = 2
    ):
        super().__init__("sql", max_retries)
        self.session_factory = session_factory
        self.connection_string = connection_string

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Execute SQL query against database."""
        if self.session_factory is None:
            return ToolResult(
                success=False,
                error="SQL session factory not provided",
                row_count=0,
                query_executed=query
            )

        import asyncio

        # Use async wrapper since SQLAlchemy sessions in database.py are synchronous
        def _sync_execute():
            session = None
            try:
                session = self.session_factory()
                result = session.execute(text(query))

                # Fetch all rows
                rows = result.mappings().all()

                # Convert to list of dicts
                data = []
                for row in rows:
                    row_dict = dict(row)
                    # Convert non-serializable types
                    for key, value in row_dict.items():
                        if hasattr(value, 'isoformat'):  # datetime
                            row_dict[key] = value.isoformat()
                        elif value is None:
                            row_dict[key] = None
                        else:
                            row_dict[key] = value
                    data.append(row_dict)

                return ToolResult(
                    success=True,
                    data=data,
                    row_count=len(data),
                    query_executed=query
                )

            except Exception as e:
                logger.error("SQL query failed", query=query, error=str(e))
                return ToolResult(
                    success=False,
                    error=str(e),
                    row_count=0,
                    query_executed=query
                )
            finally:
                if session:
                    session.close()

        # Run synchronous query in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_execute)

    def is_available(self) -> bool:
        """Check if SQL tool is available."""
        return self.session_factory is not None or self.connection_string is not None

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION

    def validate_query(self, query: str) -> tuple[bool, Optional[str]]:
        """
        Basic SQL validation - prevent destructive operations.
        Returns (is_valid, error_message).
        """
        query_upper = query.strip().upper()

        # Only allow SELECT statements
        forbidden_keywords = ['DELETE', 'DROP', 'TRUNCATE', 'UPDATE', 'INSERT', 'ALTER']
        for keyword in forbidden_keywords:
            if keyword in query_upper:
                return False, f"Query contains forbidden keyword: {keyword}"

        # Must start with SELECT
        if not query_upper.startswith('SELECT'):
            return False, "Only SELECT queries are allowed"

        return True, None
