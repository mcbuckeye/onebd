"""ETL/Sync pipeline for Cortellis Deals data."""

import os
import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import AppConfig
from .api_client import CortellisClient, DealRecord
from .models import (
    Base, Deal, Company, DealCompany, Indication, Technology, Action,
    DealAction, Territory, DealTerritory, Drug, DealDrug, Patent,
    TherapyArea, DealFinanceSummary, DealTimelineEvent, DealContract,
    DealMASummary, SyncLog, deal_indications, deal_technologies, deal_patents,
)

logger = logging.getLogger(__name__)


class DealTransformer:
    """Transform API response data into database models."""

    def __init__(self, session: Session):
        self.session = session
        self._company_cache: Dict[int, Company] = {}
        self._indication_cache: Dict[int, Indication] = {}
        self._technology_cache: Dict[int, Technology] = {}
        self._action_cache: Dict[int, Action] = {}
        self._territory_cache: Dict[str, Territory] = {}
        self._drug_cache: Dict[int, Drug] = {}
        self._patent_cache: Dict[str, Patent] = {}
        self._therapy_area_cache: Dict[int, TherapyArea] = {}

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not value:
            return None
        try:
            # Handle format like "2011-07-20T00:00:00Z"
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Could not parse datetime: {value}")
                return None

    def _get_text(self, data: Any, default: str = "") -> str:
        """Extract text from parsed XML data."""
        if data is None:
            return default
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("@text", default)
        return default

    def _get_attr(self, data: Any, attr: str, default: str = "") -> str:
        """Extract attribute from parsed XML data."""
        if data is None:
            return default
        if isinstance(data, dict):
            attrs = data.get("@attributes", {})
            return attrs.get(attr, default)
        return default

    def _parse_int_id(self, id_str: str) -> Optional[int]:
        """Parse an ID that may have alphanumeric prefix like 'CM28017' -> 28017."""
        if not id_str:
            return None
        # If purely numeric, convert directly
        if id_str.isdigit():
            return int(id_str)
        # Extract numeric suffix (e.g., 'CM28017' -> 28017)
        import re
        match = re.search(r'(\d+)$', id_str)
        if match:
            return int(match.group(1))
        # If no numeric part, use hash to generate stable int
        return abs(hash(id_str)) % (10**9)

    def get_or_create_company(self, company_id: int, name: str, company_type: str = None) -> Company:
        """Get or create a company record."""
        if company_id in self._company_cache:
            return self._company_cache[company_id]

        company = self.session.get(Company, company_id)
        if not company:
            company = Company(
                id=company_id,
                name=name,
                company_type=company_type,
            )
            self.session.add(company)
            self.session.flush()  # Flush to DB so foreign keys work

        self._company_cache[company_id] = company
        return company

    def get_or_create_indication(self, indication_id: int, name: str) -> Indication:
        """Get or create an indication record."""
        if indication_id in self._indication_cache:
            return self._indication_cache[indication_id]

        indication = self.session.get(Indication, indication_id)
        if not indication:
            indication = Indication(id=indication_id, name=name)
            self.session.add(indication)
            self.session.flush()

        self._indication_cache[indication_id] = indication
        return indication

    def get_or_create_technology(self, tech_id: int, name: str) -> Technology:
        """Get or create a technology record."""
        if tech_id in self._technology_cache:
            return self._technology_cache[tech_id]

        technology = self.session.get(Technology, tech_id)
        if not technology:
            technology = Technology(id=tech_id, name=name)
            self.session.add(technology)
            self.session.flush()

        self._technology_cache[tech_id] = technology
        return technology

    def get_or_create_action(self, action_id: int, name: str) -> Action:
        """Get or create an action record."""
        if action_id in self._action_cache:
            return self._action_cache[action_id]

        action = self.session.get(Action, action_id)
        if not action:
            action = Action(id=action_id, name=name)
            self.session.add(action)
            self.session.flush()

        self._action_cache[action_id] = action
        return action

    def get_or_create_territory(self, territory_id: str, name: str) -> Territory:
        """Get or create a territory record."""
        if territory_id in self._territory_cache:
            return self._territory_cache[territory_id]

        territory = self.session.get(Territory, territory_id)
        if not territory:
            territory = Territory(id=territory_id, name=name)
            self.session.add(territory)
            self.session.flush()

        self._territory_cache[territory_id] = territory
        return territory

    def get_or_create_drug(self, drug_id: int, name: str, phase_start: str = None, phase_now: str = None) -> Drug:
        """Get or create a drug record."""
        if drug_id in self._drug_cache:
            return self._drug_cache[drug_id]

        drug = self.session.get(Drug, drug_id)
        if not drug:
            drug = Drug(
                id=drug_id,
                name_display=name,
                phase_highest_start=phase_start,
                phase_highest_now=phase_now,
            )
            self.session.add(drug)
            self.session.flush()

        self._drug_cache[drug_id] = drug
        return drug

    def get_or_create_patent(self, patent_id: str, number: str, title: str = None) -> Patent:
        """Get or create a patent record."""
        if patent_id in self._patent_cache:
            return self._patent_cache[patent_id]

        patent = self.session.get(Patent, patent_id)
        if not patent:
            patent = Patent(id=patent_id, number=number, title=title)
            self.session.add(patent)
            self.session.flush()

        self._patent_cache[patent_id] = patent
        return patent

    def get_or_create_therapy_area(self, area_id: int, name: str) -> TherapyArea:
        """Get or create a therapy area record."""
        if area_id in self._therapy_area_cache:
            return self._therapy_area_cache[area_id]

        area = self.session.get(TherapyArea, area_id)
        if not area:
            area = TherapyArea(id=area_id, name=name)
            self.session.add(area)
            self.session.flush()

        self._therapy_area_cache[area_id] = area
        return area

    def transform_deal(self, record: DealRecord) -> Deal:
        """Transform a DealRecord into database models."""
        data = record.parsed_data
        deal_id = record.id

        # Check if deal exists
        existing_deal = self.session.get(Deal, deal_id)
        if existing_deal:
            # Delete existing relationships for update
            self.session.query(DealCompany).filter(DealCompany.deal_id == deal_id).delete()
            self.session.query(DealAction).filter(DealAction.deal_id == deal_id).delete()
            self.session.query(DealTerritory).filter(DealTerritory.deal_id == deal_id).delete()
            self.session.query(DealDrug).filter(DealDrug.deal_id == deal_id).delete()
            self.session.query(DealTimelineEvent).filter(DealTimelineEvent.deal_id == deal_id).delete()
            self.session.query(DealContract).filter(DealContract.deal_id == deal_id).delete()
            self.session.query(DealFinanceSummary).filter(DealFinanceSummary.deal_id == deal_id).delete()
            self.session.query(DealMASummary).filter(DealMASummary.deal_id == deal_id).delete()
            # Clear many-to-many relationships
            existing_deal.indications = []
            existing_deal.technologies = []
            existing_deal.patents = []
            deal = existing_deal
        else:
            deal = Deal(id=deal_id)
            self.session.add(deal)

        # Basic fields
        deal.title = self._get_text(data.get("Title", "Unknown"))
        deal.deal_type = self._get_text(data.get("Type"))
        deal.status = self._get_text(data.get("Status"))
        deal.summary = self._extract_summary(data.get("Summary"))

        # Dates
        deal.date_start = self._parse_datetime(self._get_text(data.get("DateStart")))
        deal.date_end = self._parse_datetime(self._get_text(data.get("DateEnd")))
        deal.date_event_most_recent = self._parse_datetime(self._get_text(data.get("DateEventMostRecent")))
        deal.date_change_last = self._parse_datetime(self._get_text(data.get("DateChangeLast")))
        deal.date_added = self._parse_datetime(self._get_text(data.get("DateAdded")))

        # Is Optional
        is_optional = self._get_text(data.get("IsOptional"))
        deal.is_optional = is_optional == "Y" if is_optional else None

        # Category
        category = data.get("Category", {})
        if isinstance(category, dict):
            deal.agreement_type = self._get_text(category.get("AgreementType"))
            deal.category_raw = category

            # Asset types
            asset_types = category.get("AssetTypes", {})
            if asset_types:
                asset_type_list = asset_types.get("AssetType", [])
                if isinstance(asset_type_list, dict):
                    deal.asset_type = self._get_text(asset_type_list)
                elif isinstance(asset_type_list, list) and asset_type_list:
                    deal.asset_type = self._get_text(asset_type_list[0])

            # Transaction types
            tx_types = category.get("TransactionTypes", {})
            if tx_types:
                tx_type_list = tx_types.get("TransactionType", [])
                if isinstance(tx_type_list, dict):
                    deal.transaction_type = self._get_text(tx_type_list)
                elif isinstance(tx_type_list, list) and tx_type_list:
                    deal.transaction_type = self._get_text(tx_type_list[0])

        # Therapy Area
        therapy_area_data = data.get("TherapyArea")
        if therapy_area_data:
            area_id = self._parse_int_id(self._get_attr(therapy_area_data, "id"))
            area_name = self._get_text(therapy_area_data)
            if area_id and area_name:
                therapy_area = self.get_or_create_therapy_area(area_id, area_name)
                deal.therapy_area = therapy_area

        # Companies
        self._process_companies(deal, data)

        # Indications
        self._process_indications(deal, data)

        # Technologies
        self._process_technologies(deal, data)

        # Actions
        self._process_actions(deal, data)

        # Territories
        self._process_territories(deal, data)

        # Drugs
        self._process_drugs(deal, data)

        # Patents
        self._process_patents(deal, data)

        # Finance Summary
        self._process_finance_summary(deal, data)

        # Timeline
        self._process_timeline(deal, data)

        # M&A Summary
        self._process_ma_summary(deal, data)

        # Cross references (store as raw JSON)
        cross_refs = data.get("CrossReferences")
        if cross_refs:
            deal.cross_references_raw = cross_refs

        return deal

    def _extract_summary(self, summary_data: Any) -> Optional[str]:
        """Extract summary text from nested structure."""
        if not summary_data:
            return None
        if isinstance(summary_data, str):
            return summary_data
        if isinstance(summary_data, dict):
            # May have nested <para> elements
            text = self._get_text(summary_data)
            if text:
                return text
            # Try to extract from para elements
            paras = summary_data.get("para", [])
            if isinstance(paras, str):
                return paras
            if isinstance(paras, list):
                return "\n".join(self._get_text(p) for p in paras if self._get_text(p))
        return None

    def _process_companies(self, deal: Deal, data: Dict):
        """Process company associations."""
        # Principal company
        principal = data.get("CompanyPrincipal")
        if principal:
            company_id_str = self._get_attr(principal, "id")
            company_id = self._parse_int_id(company_id_str)
            company_type = self._get_attr(principal, "type")
            company_name = self._get_text(principal)
            if company_id and company_name:
                company = self.get_or_create_company(company_id, company_name, company_type)
                assoc = DealCompany(deal_id=deal.id, company_id=company.id, role="Principal")
                self.session.add(assoc)
                self.session.flush()

        # Partner company
        partner = data.get("CompanyPartner")
        if partner:
            company_id_str = self._get_attr(partner, "id")
            company_id = self._parse_int_id(company_id_str)
            company_type = self._get_attr(partner, "type")
            company_name = self._get_text(partner)
            if company_id and company_name:
                company = self.get_or_create_company(company_id, company_name, company_type)
                assoc = DealCompany(deal_id=deal.id, company_id=company.id, role="Partner")
                self.session.add(assoc)
                self.session.flush()

    def _process_indications(self, deal: Deal, data: Dict):
        """Process indication associations."""
        indications_data = data.get("Indications", {})
        indication_list = indications_data.get("Indication", []) if isinstance(indications_data, dict) else []
        if isinstance(indication_list, dict):
            indication_list = [indication_list]

        for ind_data in indication_list:
            ind_id = self._parse_int_id(self._get_attr(ind_data, "id"))
            ind_name = self._get_text(ind_data)
            if ind_id and ind_name:
                indication = self.get_or_create_indication(ind_id, ind_name)
                if indication not in deal.indications:
                    deal.indications.append(indication)

    def _process_technologies(self, deal: Deal, data: Dict):
        """Process technology associations."""
        tech_data = data.get("Technologies", {})
        tech_list = tech_data.get("Technology", []) if isinstance(tech_data, dict) else []
        if isinstance(tech_list, dict):
            tech_list = [tech_list]

        for tech in tech_list:
            tech_id = self._parse_int_id(self._get_attr(tech, "id"))
            tech_name = self._get_text(tech)
            if tech_id and tech_name:
                technology = self.get_or_create_technology(tech_id, tech_name)
                if technology not in deal.technologies:
                    deal.technologies.append(technology)

    def _process_actions(self, deal: Deal, data: Dict):
        """Process action associations."""
        # Primary actions
        primary_data = data.get("ActionsPrimary", {})
        primary_list = primary_data.get("Action", []) if isinstance(primary_data, dict) else []
        if isinstance(primary_list, dict):
            primary_list = [primary_list]

        for action_data in primary_list:
            action_id = self._parse_int_id(self._get_attr(action_data, "id"))
            action_name = self._get_text(action_data)
            if action_id and action_name:
                action = self.get_or_create_action(action_id, action_name)
                assoc = DealAction(deal_id=deal.id, action_id=action.id, action_type="Primary")
                self.session.add(assoc)

        # Secondary actions
        secondary_data = data.get("ActionsSecondary", {})
        secondary_list = secondary_data.get("Action", []) if isinstance(secondary_data, dict) else []
        if isinstance(secondary_list, dict):
            secondary_list = [secondary_list]

        for action_data in secondary_list:
            action_id = self._parse_int_id(self._get_attr(action_data, "id"))
            action_name = self._get_text(action_data)
            if action_id and action_name:
                action = self.get_or_create_action(action_id, action_name)
                assoc = DealAction(deal_id=deal.id, action_id=action.id, action_type="Secondary")
                self.session.add(assoc)

    def _process_territories(self, deal: Deal, data: Dict):
        """Process territory associations."""
        # Included territories
        included_data = data.get("TerritoriesIncluded", {})
        included_list = included_data.get("Territory", []) if isinstance(included_data, dict) else []
        if isinstance(included_list, dict):
            included_list = [included_list]

        for terr_data in included_list:
            terr_id = self._get_attr(terr_data, "id")
            terr_name = self._get_text(terr_data)
            if terr_id and terr_name:
                territory = self.get_or_create_territory(terr_id, terr_name)
                assoc = DealTerritory(deal_id=deal.id, territory_id=territory.id, territory_type="Included")
                self.session.add(assoc)

        # Excluded territories
        excluded_data = data.get("TerritoriesExcluded", {})
        excluded_list = excluded_data.get("Territory", []) if isinstance(excluded_data, dict) else []
        if isinstance(excluded_list, dict):
            excluded_list = [excluded_list]

        for terr_data in excluded_list:
            terr_id = self._get_attr(terr_data, "id")
            terr_name = self._get_text(terr_data)
            if terr_id and terr_name:
                territory = self.get_or_create_territory(terr_id, terr_name)
                assoc = DealTerritory(deal_id=deal.id, territory_id=territory.id, territory_type="Excluded")
                self.session.add(assoc)

    def _process_drugs(self, deal: Deal, data: Dict):
        """Process drug associations."""
        drugs_data = data.get("Drugs", {})
        drug_list = drugs_data.get("Drug", []) if isinstance(drugs_data, dict) else []
        if isinstance(drug_list, dict):
            drug_list = [drug_list]

        for drug_data in drug_list:
            drug_id_str = self._get_attr(drug_data, "id")
            if not drug_id_str:
                drug_id_str = drug_data.get("@attributes", {}).get("id") if isinstance(drug_data, dict) else None
            drug_name = self._get_text(drug_data.get("DrugNameDisplay", "")) if isinstance(drug_data, dict) else ""
            drug_id = self._parse_int_id(drug_id_str) if drug_id_str else None

            if drug_id and drug_name:
                phase_start = self._get_text(drug_data.get("PhaseHighestStart", "")) if isinstance(drug_data, dict) else ""
                phase_now = self._get_text(drug_data.get("PhaseHighestNow", "")) if isinstance(drug_data, dict) else ""
                drug = self.get_or_create_drug(drug_id, drug_name, phase_start, phase_now)
                assoc = DealDrug(deal_id=deal.id, drug_id=drug.id)
                self.session.add(assoc)

    def _process_patents(self, deal: Deal, data: Dict):
        """Process patent associations."""
        patents_data = data.get("Patents", {})
        patent_list = patents_data.get("Patent", []) if isinstance(patents_data, dict) else []
        if isinstance(patent_list, dict):
            patent_list = [patent_list]

        for patent_data in patent_list:
            patent_id = self._get_attr(patent_data, "id")
            patent_number = self._get_text(patent_data.get("Number", "")) if isinstance(patent_data, dict) else ""
            patent_title = self._get_text(patent_data.get("Title", "")) if isinstance(patent_data, dict) else ""

            if patent_id and patent_number:
                patent = self.get_or_create_patent(patent_id, patent_number, patent_title)
                if patent not in deal.patents:
                    deal.patents.append(patent)

    def _process_finance_summary(self, deal: Deal, data: Dict):
        """Process finance summary."""
        finance_summary = data.get("FinanceSummary", {})
        finance_detail = data.get("FinanceDetail", {})

        if not finance_summary and not finance_detail:
            return

        summary = DealFinanceSummary(deal_id=deal.id)

        # Total Paid
        total_paid = finance_summary.get("TotalPaid", {}) if isinstance(finance_summary, dict) else {}
        if isinstance(total_paid, dict):
            summary.total_paid_amount = self._parse_float(self._get_text(total_paid))
            summary.total_paid_currency = self._get_attr(total_paid, "currency")
            summary.total_paid_unit = self._get_attr(total_paid, "unit")
            summary.total_paid_disclosure_status = self._get_attr(total_paid, "disclosureStatus")

        # Total Projected Current
        total_current = finance_summary.get("TotalProjectedCurrent", {}) if isinstance(finance_summary, dict) else {}
        if isinstance(total_current, dict):
            summary.total_projected_current_amount = self._parse_float(self._get_text(total_current))
            summary.total_projected_current_currency = self._get_attr(total_current, "currency")
            summary.total_projected_current_unit = self._get_attr(total_current, "unit")
            summary.total_projected_current_disclosure_status = self._get_attr(total_current, "disclosureStatus")

        # Total Projected Signing
        total_signing = finance_summary.get("TotalProjectedSigning", {}) if isinstance(finance_summary, dict) else {}
        if isinstance(total_signing, dict):
            summary.total_projected_signing_amount = self._parse_float(self._get_text(total_signing))
            summary.total_projected_signing_currency = self._get_attr(total_signing, "currency")
            summary.total_projected_signing_unit = self._get_attr(total_signing, "unit")
            summary.total_projected_signing_disclosure_status = self._get_attr(total_signing, "disclosureStatus")

        # Store raw finance detail
        if finance_detail:
            summary.finance_detail_raw = finance_detail

        self.session.add(summary)

    def _parse_float(self, value: str) -> Optional[float]:
        """Parse float from string."""
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _process_timeline(self, deal: Deal, data: Dict):
        """Process timeline events."""
        timeline_data = data.get("TimeLine", {})
        event_list = timeline_data.get("Event", []) if isinstance(timeline_data, dict) else []
        if isinstance(event_list, dict):
            event_list = [event_list]

        for event_data in event_list:
            if not isinstance(event_data, dict):
                continue

            event = DealTimelineEvent(deal_id=deal.id)
            event.event_date = self._parse_datetime(self._get_text(event_data.get("Date")))
            event.event_type = self._get_text(event_data.get("Type"))
            event.stage = self._get_text(event_data.get("Stage"))
            event.stage_id = self._get_attr(event_data.get("Stage", {}), "id")
            event.stage_notes = self._get_text(event_data.get("StageNotes"))
            event.summary = self._extract_summary(event_data.get("Summary"))

            # Store payments as JSON
            payments_to_principal = event_data.get("PaymentsToPrincipal")
            if payments_to_principal:
                event.payments_to_principal = payments_to_principal

            payments_to_partner = event_data.get("PaymentsToPartner")
            if payments_to_partner:
                event.payments_to_partner = payments_to_partner

            # Store drugs as JSON
            drugs = event_data.get("Drugs")
            if drugs:
                event.drugs = drugs

            self.session.add(event)

    def _process_ma_summary(self, deal: Deal, data: Dict):
        """Process M&A summary if present."""
        ma_summary = data.get("MergersnAcquisitionsSummary", {})
        ma_financial = data.get("MergersnAcquisitionsFinancial", {})

        if not ma_summary and not ma_financial:
            return

        summary = DealMASummary(deal_id=deal.id)

        if isinstance(ma_summary, dict):
            summary.company_type = self._get_text(ma_summary.get("CompanyType"))
            summary.business_description = self._extract_summary(ma_summary.get("BusinessDescription"))
            prior_rel = self._get_text(ma_summary.get("PriorRelationshipBeforeMerger"))
            summary.prior_relationship = prior_rel.lower() == "yes" if prior_rel else None
            summary.overall_product_phase_highest = self._get_text(ma_summary.get("OverallProductPhaseHighest"))
            summary.ownership = self._get_text(ma_summary.get("Ownership"))
            summary.attitude = self._get_text(ma_summary.get("Attitude"))
            summary.top_3_products = self._get_text(ma_summary.get("Top3Products"))
            summary.major_investors = self._get_text(ma_summary.get("MajorInvestors"))

        if isinstance(ma_financial, dict):
            cash = ma_financial.get("CashAtAcquisition", {})
            if isinstance(cash, dict):
                summary.cash_at_acquisition = self._parse_float(self._get_text(cash))
                summary.cash_at_acquisition_currency = self._get_attr(cash, "currency")

            pps = ma_financial.get("PricePerShare", {})
            if isinstance(pps, dict):
                summary.price_per_share = self._parse_float(self._get_text(pps))
                summary.price_per_share_currency = self._get_attr(pps, "currency")

            revenue = ma_financial.get("TotalRevenueYearPrior", {})
            if isinstance(revenue, dict):
                summary.total_revenue_year_prior = self._parse_float(self._get_text(revenue))

            shares = ma_financial.get("TotalSharesOutstanding", {})
            if isinstance(shares, dict):
                summary.total_shares_outstanding = self._parse_float(self._get_text(shares))

            summary.closing_price_day_one = self._parse_float(
                self._get_text(ma_financial.get("ClosingPriceDayOne", {}))
            )
            summary.closing_price_day_five = self._parse_float(
                self._get_text(ma_financial.get("ClosingPriceDayFive", {}))
            )
            summary.closing_price_day_thirty = self._parse_float(
                self._get_text(ma_financial.get("ClosingPriceDayThirty", {}))
            )

        self.session.add(summary)


class SyncService:
    """Service for synchronizing Cortellis data to the database."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.engine = create_engine(config.database.connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def init_database(self):
        """Initialize database tables."""
        Base.metadata.create_all(self.engine)
        logger.info("Database tables created")

    def full_sync(self, batch_size: int = 30, use_cached_ids: bool = True) -> SyncLog:
        """
        Perform a full synchronization of all deals.

        Args:
            batch_size: Number of deals to fetch per API call (max 30)
            use_cached_ids: If True, use cached deal IDs file if it exists

        Returns:
            SyncLog with statistics
        """
        # Path for cached deal IDs (with metadata for resume)
        cache_dir = Path(self.config.contracts_dir).parent
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "deal_ids_cache.json"

        with self.SessionLocal() as session:
            sync_log = SyncLog(
                started_at=datetime.utcnow(),
                sync_type="full",
                status="running",
            )
            session.add(sync_log)
            session.commit()

            try:
                with CortellisClient(self.config.cortellis) as client:
                    all_ids = []

                    # Check for existing cache
                    cache_data = None
                    if use_cached_ids and cache_file.exists():
                        with open(cache_file, "r") as f:
                            cache_data = json.load(f)

                        # Check if cache is complete
                        if isinstance(cache_data, dict) and cache_data.get("complete"):
                            all_ids = cache_data["ids"]
                            logger.info(f"Loaded {len(all_ids)} deal IDs from complete cache")
                        elif isinstance(cache_data, dict):
                            # Resume from partial cache
                            all_ids = cache_data.get("ids", [])
                            resume_offset = cache_data.get("next_offset", 0)
                            total_expected = cache_data.get("total_expected", 0)
                            logger.info(f"Resuming from partial cache: {len(all_ids)} IDs collected, resuming from offset {resume_offset}")
                        elif isinstance(cache_data, list):
                            # Old format - assume complete
                            all_ids = cache_data
                            logger.info(f"Loaded {len(all_ids)} deal IDs from cache (legacy format)")
                            cache_data = {"complete": True}

                    # Fetch remaining IDs if needed
                    if not cache_data or not cache_data.get("complete"):
                        logger.info("Fetching deal IDs from API (saving incrementally)...")
                        offset = cache_data.get("next_offset", 0) if cache_data else 0
                        hits = 100
                        total_expected = cache_data.get("total_expected", 0) if cache_data else 0

                        while True:
                            result = client.search_deals(query="*", offset=offset, hits=hits)
                            if total_expected == 0:
                                total_expected = result.total_results

                            all_ids.extend(result.deal_ids)
                            logger.info(f"Fetched deals {offset} to {offset + len(result.deal_ids)} of {total_expected} ({len(all_ids)} total collected)")

                            # Save progress after each batch
                            is_complete = (offset + len(result.deal_ids)) >= total_expected
                            with open(cache_file, "w") as f:
                                json.dump({
                                    "ids": all_ids,
                                    "next_offset": offset + hits,
                                    "total_expected": total_expected,
                                    "complete": is_complete,
                                    "last_updated": datetime.utcnow().isoformat()
                                }, f)

                            if is_complete:
                                logger.info(f"Phase 1 complete: {len(all_ids)} deal IDs collected and cached")
                                break

                            offset += hits
                            import time
                            time.sleep(0.5)  # Rate limiting

                    # Process in batches
                    transformer = DealTransformer(session)
                    records_processed = 0
                    records_created = 0
                    records_updated = 0

                    for i in range(0, len(all_ids), batch_size):
                        batch_ids = all_ids[i:i + batch_size]
                        logger.info(f"Processing batch {i // batch_size + 1}: deals {i + 1} to {i + len(batch_ids)}")

                        try:
                            records = client.get_deal_records(batch_ids)
                            for record in records:
                                existing = session.get(Deal, record.id)
                                transformer.transform_deal(record)
                                records_processed += 1
                                if existing:
                                    records_updated += 1
                                else:
                                    records_created += 1

                            session.commit()
                        except Exception as e:
                            logger.exception(f"Error processing batch: {e}")
                            session.rollback()
                            continue

                    # Download contracts
                    contracts_downloaded = self._download_all_contracts(session, client)

                    sync_log.completed_at = datetime.utcnow()
                    sync_log.status = "completed"
                    sync_log.records_processed = records_processed
                    sync_log.records_created = records_created
                    sync_log.records_updated = records_updated
                    sync_log.contracts_downloaded = contracts_downloaded
                    session.commit()

                    logger.info(
                        f"Full sync completed: {records_processed} processed, "
                        f"{records_created} created, {records_updated} updated, "
                        f"{contracts_downloaded} contracts downloaded"
                    )

            except Exception as e:
                sync_log.completed_at = datetime.utcnow()
                sync_log.status = "failed"
                sync_log.error_message = str(e)
                session.commit()
                logger.error(f"Full sync failed: {e}")
                raise

            # Refresh and expunge to allow access after session closes
            session.refresh(sync_log)
            session.expunge(sync_log)
            return sync_log

    def incremental_sync(self, batch_size: int = 30) -> SyncLog:
        """
        Perform an incremental sync of recently updated deals.

        Args:
            batch_size: Number of deals to fetch per API call

        Returns:
            SyncLog with statistics
        """
        with self.SessionLocal() as session:
            # Find last successful sync
            last_sync = session.query(SyncLog).filter(
                SyncLog.status == "completed"
            ).order_by(SyncLog.completed_at.desc()).first()

            if not last_sync:
                logger.info("No previous sync found, performing full sync")
                return self.full_sync(batch_size)

            sync_log = SyncLog(
                started_at=datetime.utcnow(),
                sync_type="incremental",
                status="running",
            )
            session.add(sync_log)
            session.commit()

            try:
                with CortellisClient(self.config.cortellis) as client:
                    # Get updated deal IDs
                    since_date = last_sync.completed_at
                    logger.info(f"Fetching deals updated since {since_date}...")
                    updated_ids = list(client.get_updated_deals_since(since_date))
                    logger.info(f"Found {len(updated_ids)} updated deals")

                    if not updated_ids:
                        sync_log.completed_at = datetime.utcnow()
                        sync_log.status = "completed"
                        sync_log.records_processed = 0
                        sync_log.records_updated = 0
                        sync_log.contracts_downloaded = 0
                        session.commit()
                        session.refresh(sync_log)
                        session.expunge(sync_log)
                        return sync_log

                    # Process in batches
                    transformer = DealTransformer(session)
                    records_processed = 0
                    records_updated = 0

                    for i in range(0, len(updated_ids), batch_size):
                        batch_ids = updated_ids[i:i + batch_size]
                        logger.info(f"Processing batch: deals {i + 1} to {i + len(batch_ids)}")

                        try:
                            records = client.get_deal_records(batch_ids)
                            for record in records:
                                transformer.transform_deal(record)
                                records_processed += 1
                                records_updated += 1

                            session.commit()
                        except Exception as e:
                            logger.exception(f"Error processing batch: {e}")
                            session.rollback()
                            continue

                    # Download contracts for updated deals
                    contracts_downloaded = self._download_contracts_for_deals(
                        session, client, updated_ids
                    )

                    sync_log.completed_at = datetime.utcnow()
                    sync_log.status = "completed"
                    sync_log.records_processed = records_processed
                    sync_log.records_updated = records_updated
                    sync_log.contracts_downloaded = contracts_downloaded
                    session.commit()

                    logger.info(
                        f"Incremental sync completed: {records_processed} processed, "
                        f"{records_updated} updated, {contracts_downloaded} contracts downloaded"
                    )

            except Exception as e:
                sync_log.completed_at = datetime.utcnow()
                sync_log.status = "failed"
                sync_log.error_message = str(e)
                session.commit()
                logger.error(f"Incremental sync failed: {e}")
                raise

            # Refresh and expunge to allow access after session closes
            session.refresh(sync_log)
            session.expunge(sync_log)
            return sync_log

    def _download_all_contracts(self, session: Session, client: CortellisClient) -> int:
        """Download all contract documents."""
        deals_with_contracts = session.query(Deal).filter(Deal.has_contract == True).all()
        return self._download_contracts_for_deals(
            session, client, [d.id for d in deals_with_contracts]
        )

    def _download_contracts_for_deals(
        self,
        session: Session,
        client: CortellisClient,
        deal_ids: List[int],
    ) -> int:
        """Download contract documents for specific deals."""
        contracts_dir = Path(self.config.contracts_dir)
        contracts_dir.mkdir(parents=True, exist_ok=True)
        contracts_downloaded = 0

        for deal_id in deal_ids:
            try:
                contracts = client.get_deal_contracts(deal_id)
                if not contracts:
                    continue

                deal_dir = contracts_dir / str(deal_id)
                deal_dir.mkdir(exist_ok=True)

                for contract_data in contracts:
                    contract_id = contract_data["id"]

                    # Check if already in database
                    existing = session.query(DealContract).filter(
                        DealContract.id == contract_id
                    ).first()

                    if existing and existing.downloaded_at:
                        continue

                    # Create or update contract record
                    if not existing:
                        contract = DealContract(
                            id=contract_id,
                            deal_id=deal_id,
                            contract_types=",".join(contract_data.get("types", [])),
                            has_pdf=contract_data.get("has_pdf", False),
                            has_text=contract_data.get("has_text", False),
                            date_filing=self._parse_datetime(contract_data.get("date_filing")),
                            date_contract=self._parse_datetime(contract_data.get("date_contract")),
                            is_redacted=contract_data.get("is_redacted", False),
                        )
                        session.add(contract)
                    else:
                        contract = existing

                    # Download PDF if available
                    if contract_data.get("has_pdf"):
                        pdf_path = deal_dir / f"{contract_id}.pdf"
                        if client.download_contract_document(contract_id, "pdf", str(pdf_path)):
                            contract.pdf_file_path = str(pdf_path)
                            contracts_downloaded += 1

                    # Download text if available
                    if contract_data.get("has_text"):
                        txt_path = deal_dir / f"{contract_id}.txt"
                        if client.download_contract_document(contract_id, "txt", str(txt_path)):
                            contract.text_file_path = str(txt_path)
                            contracts_downloaded += 1

                    contract.downloaded_at = datetime.utcnow()
                    session.commit()

            except Exception as e:
                logger.warning(f"Error downloading contracts for deal {deal_id}: {e}")
                continue

        return contracts_downloaded

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def sync_contracts(self, workers: int = 5, resume: bool = True) -> Dict[str, int]:
        """
        Sync contract metadata and download contract documents.

        This is a separate process from the main deal sync because checking
        contracts requires an API call per deal.

        Args:
            workers: Number of parallel workers for checking contracts
            resume: Whether to resume from previous progress

        Returns:
            Dict with sync statistics
        """
        cache_file = Path(self.config.data_dir) / "contract_sync_progress.json"
        contracts_dir = Path(self.config.contracts_dir)
        contracts_dir.mkdir(parents=True, exist_ok=True)

        # Load progress cache
        checked_deals = set()
        if resume and cache_file.exists():
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
                checked_deals = set(cache_data.get("checked_deals", []))
                logger.info(f"Resuming from {len(checked_deals)} previously checked deals")

        # Get all deal IDs from database
        Session = sessionmaker(bind=self.engine)
        with Session() as session:
            all_deal_ids = [d.id for d in session.query(Deal.id).all()]

        # Filter out already checked deals
        deals_to_check = [d for d in all_deal_ids if d not in checked_deals]
        logger.info(f"Need to check {len(deals_to_check)} deals for contracts")

        if not deals_to_check:
            logger.info("All deals already checked for contracts")
            return {
                "deals_checked": len(checked_deals),
                "deals_with_contracts": 0,
                "contracts_downloaded": 0,
            }

        # Stats
        deals_with_contracts = 0
        contracts_downloaded = 0
        errors = 0

        def check_deal_contracts(deal_id: int) -> Dict:
            """Check a single deal for contracts and download if available."""
            result = {
                "deal_id": deal_id,
                "has_contracts": False,
                "contracts_downloaded": 0,
                "error": None,
            }

            try:
                with CortellisClient(self.config.cortellis) as client:
                    contracts = client.get_deal_contracts(deal_id)

                    if not contracts:
                        return result

                    result["has_contracts"] = True

                    # Create deal directory for contracts
                    deal_dir = contracts_dir / str(deal_id)
                    deal_dir.mkdir(exist_ok=True)

                    Session = sessionmaker(bind=self.engine)
                    with Session() as session:
                        # Update deal's has_contract flag
                        deal = session.get(Deal, deal_id)
                        if deal:
                            deal.has_contract = True

                        for contract_data in contracts:
                            contract_id = contract_data.get("id")
                            if not contract_id:
                                continue

                            # Check if already exists
                            existing = session.query(DealContract).filter(
                                DealContract.id == contract_id
                            ).first()

                            if existing and existing.downloaded_at:
                                continue

                            # Create or update contract record
                            if not existing:
                                contract = DealContract(
                                    id=contract_id,
                                    deal_id=deal_id,
                                    contract_types=",".join(contract_data.get("types", [])),
                                    has_pdf=contract_data.get("has_pdf", False),
                                    has_text=contract_data.get("has_text", False),
                                    date_filing=self._parse_contract_date(contract_data.get("date_filing")),
                                    date_contract=self._parse_contract_date(contract_data.get("date_contract")),
                                    is_redacted=contract_data.get("is_redacted", False),
                                )
                                session.add(contract)
                            else:
                                contract = existing

                            # Download PDF if available
                            if contract_data.get("has_pdf"):
                                pdf_path = deal_dir / f"{contract_id}.pdf"
                                if not pdf_path.exists():
                                    if client.download_contract_document(contract_id, "pdf", str(pdf_path)):
                                        contract.pdf_file_path = str(pdf_path)
                                        result["contracts_downloaded"] += 1

                            # Download text if available
                            if contract_data.get("has_text"):
                                txt_path = deal_dir / f"{contract_id}.txt"
                                if not txt_path.exists():
                                    if client.download_contract_document(contract_id, "txt", str(txt_path)):
                                        contract.text_file_path = str(txt_path)
                                        result["contracts_downloaded"] += 1

                            contract.downloaded_at = datetime.utcnow()

                        session.commit()

            except Exception as e:
                result["error"] = str(e)

            return result

        # Process deals with parallel workers
        batch_size = 100  # Save progress every 100 deals
        processed = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            future_to_deal = {
                executor.submit(check_deal_contracts, deal_id): deal_id
                for deal_id in deals_to_check
            }

            for future in as_completed(future_to_deal):
                deal_id = future_to_deal[future]
                try:
                    result = future.result()

                    if result["has_contracts"]:
                        deals_with_contracts += 1
                    contracts_downloaded += result["contracts_downloaded"]
                    if result["error"]:
                        errors += 1
                        logger.warning(f"Error checking deal {deal_id}: {result['error']}")

                    checked_deals.add(deal_id)
                    processed += 1

                    # Save progress periodically
                    if processed % batch_size == 0:
                        with open(cache_file, "w") as f:
                            json.dump({
                                "checked_deals": list(checked_deals),
                                "last_updated": datetime.utcnow().isoformat(),
                            }, f)
                        logger.info(
                            f"Progress: {processed}/{len(deals_to_check)} deals checked, "
                            f"{deals_with_contracts} with contracts, {contracts_downloaded} downloaded"
                        )

                    # Rate limiting
                    time.sleep(0.1)

                except Exception as e:
                    errors += 1
                    logger.error(f"Error processing deal {deal_id}: {e}")

        # Final save
        with open(cache_file, "w") as f:
            json.dump({
                "checked_deals": list(checked_deals),
                "completed": True,
                "last_updated": datetime.utcnow().isoformat(),
            }, f)

        logger.info(
            f"Contract sync completed: {len(checked_deals)} deals checked, "
            f"{deals_with_contracts} with contracts, {contracts_downloaded} downloaded, "
            f"{errors} errors"
        )

        return {
            "deals_checked": len(checked_deals),
            "deals_with_contracts": deals_with_contracts,
            "contracts_downloaded": contracts_downloaded,
        }

    def _parse_contract_date(self, value: Optional[str]) -> Optional[datetime]:
        """Parse contract date which may be in different formats."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None
