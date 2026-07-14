"""Typed, evidence-aware advanced search for governed deals and assets."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import text

from unified_api.services.finance_parser import FINANCE_PARSER_VERSION


MatchMode = Literal["exact", "contains"]
MissingDataMode = Literal["exclude", "include_as_unknown", "require_known"]
Attribution = Literal["asset", "deal"]
Direction = Literal["asc", "desc"]
SortField = Literal[
    "id",
    "date_start",
    "date_change_last",
    "total_projected_current",
    "total_paid",
    "asset_name",
    "phase",
    "deal_count",
    "latest_deal_date",
    "maximum_projected_value",
]
DateField = Literal[
    "date_start",
    "date_end",
    "date_change_last",
    "date_added",
    "date_event_most_recent",
    "timeline_event_date",
    "contract_date",
    "active_during",
]
BoundedText = Annotated[str, StringConstraints(max_length=200)]
CurrencyText = Annotated[str, StringConstraints(max_length=10)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TextValues(StrictModel):
    """Text values for scalar fields such as deal type and status."""

    include: list[BoundedText] = Field(default_factory=list, max_length=50)
    exclude: list[BoundedText] = Field(default_factory=list, max_length=50)
    match_mode: MatchMode = "exact"

    @model_validator(mode="after")
    def normalize(self):
        self.include = _clean_strings(self.include)
        self.exclude = _clean_strings(self.exclude)
        return self


class RelatedTextValues(StrictModel):
    """Boolean matching for many-valued relationships."""

    any: list[BoundedText] = Field(default_factory=list, max_length=50)
    all: list[BoundedText] = Field(default_factory=list, max_length=25)
    exclude: list[BoundedText] = Field(default_factory=list, max_length=50)
    match_mode: MatchMode = "exact"

    @model_validator(mode="after")
    def normalize(self):
        self.any = _clean_strings(self.any)
        self.all = _clean_strings(self.all)
        self.exclude = _clean_strings(self.exclude)
        return self


class CompanyCriterion(StrictModel):
    id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[Literal["Principal", "Partner"]] = Field(
        default_factory=list, max_length=2
    )
    match_mode: MatchMode = "exact"

    @model_validator(mode="after")
    def require_one_identity(self):
        if (self.id is None) == (not self.name or not self.name.strip()):
            raise ValueError("A company criterion requires exactly one of id or name")
        if self.name:
            self.name = self.name.strip()
        return self


class CompanyFilters(StrictModel):
    any: list[CompanyCriterion] = Field(default_factory=list, max_length=50)
    all: list[CompanyCriterion] = Field(default_factory=list, max_length=25)
    exclude: list[CompanyCriterion] = Field(default_factory=list, max_length=50)


class AssetFilters(StrictModel):
    ids: list[int] = Field(default_factory=list, max_length=100)
    names: RelatedTextValues = Field(default_factory=RelatedTextValues)
    phases: TextValues = Field(default_factory=TextValues)
    modalities: RelatedTextValues = Field(default_factory=RelatedTextValues)
    asset_types: TextValues = Field(default_factory=TextValues)


class ConceptFilters(StrictModel):
    ids: list[BoundedText] = Field(default_factory=list, max_length=100)
    names: RelatedTextValues = Field(default_factory=RelatedTextValues)
    action_types: TextValues = Field(default_factory=TextValues)

    @model_validator(mode="after")
    def normalize(self):
        self.ids = _clean_strings(self.ids)
        return self


class DealFilters(StrictModel):
    types: TextValues = Field(default_factory=TextValues)
    agreement_types: TextValues = Field(default_factory=TextValues)
    transaction_types: TextValues = Field(default_factory=TextValues)
    statuses: TextValues = Field(default_factory=TextValues)
    phases: TextValues = Field(default_factory=TextValues)
    territories: RelatedTextValues = Field(default_factory=RelatedTextValues)
    is_optional: bool | None = None
    is_merger_acquisition: bool | None = None
    has_contract: bool | None = None


class DateRange(StrictModel):
    field: DateField
    gte: date | None = None
    lte: date | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.gte is None and self.lte is None:
            raise ValueError("A date range requires gte or lte")
        if self.gte and self.lte and self.gte > self.lte:
            raise ValueError("Date range gte cannot be after lte")
        return self


class NumericRange(StrictModel):
    gte: float | None = Field(default=None, ge=0)
    lte: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.gte is None and self.lte is None:
            raise ValueError("A numeric range requires gte or lte")
        if self.gte is not None and self.lte is not None and self.gte > self.lte:
            raise ValueError("Numeric range gte cannot be greater than lte")
        return self


class MoneyRange(NumericRange):
    currencies: list[CurrencyText] = Field(min_length=1, max_length=10)
    disclosure_status: list[BoundedText] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def normalize_money(self):
        self.currencies = [value.upper() for value in _clean_strings(self.currencies)]
        self.disclosure_status = _clean_strings(self.disclosure_status)
        if not self.currencies:
            raise ValueError("currencies must contain at least one non-blank value")
        return self


class TermRange(NumericRange):
    basis: list[Literal["paid", "projected_current", "projected_signing"]] = Field(
        default_factory=list, max_length=3
    )
    disclosure_status: list[BoundedText] = Field(
        default_factory=lambda: ["Known"], max_length=10
    )

    @model_validator(mode="after")
    def normalize_term(self):
        self.disclosure_status = _clean_strings(self.disclosure_status)
        return self


class RateRange(TermRange):
    @model_validator(mode="after")
    def validate_percentage(self):
        if self.gte is not None and self.gte > 100:
            raise ValueError("percentage gte cannot exceed 100")
        if self.lte is not None and self.lte > 100:
            raise ValueError("percentage lte cannot exceed 100")
        return self


class ValueFilters(StrictModel):
    total_paid_millions: MoneyRange | None = None
    total_projected_current_millions: MoneyRange | None = None
    total_projected_signing_millions: MoneyRange | None = None
    upfront_usd_millions: TermRange | None = None
    milestone_usd_millions: TermRange | None = None
    royalty_rate_pct: RateRange | None = None


class EvidenceFilters(StrictModel):
    allowed_attribution: list[Attribution] = Field(
        default_factory=lambda: ["asset", "deal"], min_length=1, max_length=2
    )
    sources: list[Literal["cortellis_deals", "public_biology"]] = Field(
        default_factory=lambda: ["cortellis_deals", "public_biology"],
        min_length=1,
        max_length=2,
    )
    missing_data: MissingDataMode = "exclude"


class SortSpec(StrictModel):
    field: SortField
    direction: Direction = "asc"


class AdvancedSearchRequest(StrictModel):
    query: str | None = Field(default=None, min_length=1, max_length=200)
    companies: CompanyFilters = Field(default_factory=CompanyFilters)
    assets: AssetFilters = Field(default_factory=AssetFilters)
    targets: ConceptFilters = Field(default_factory=ConceptFilters)
    diseases: ConceptFilters = Field(default_factory=ConceptFilters)
    deals: DealFilters = Field(default_factory=DealFilters)
    dates: list[DateRange] = Field(default_factory=list, max_length=8)
    values: ValueFilters = Field(default_factory=ValueFilters)
    evidence: EvidenceFilters = Field(default_factory=EvidenceFilters)
    sort: list[SortSpec] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2000)
    include_total: bool = False

    @model_validator(mode="after")
    def validate_concept_refinements(self):
        if self.query:
            self.query = self.query.strip()
            if not self.query:
                raise ValueError("query cannot be blank")
        if self.diseases.action_types.model_dump(exclude_defaults=True):
            raise ValueError("action_types is supported for targets, not diseases")
        target_values = [
            *self.targets.ids,
            *self.targets.names.any,
            *self.targets.names.all,
            *self.targets.names.exclude,
        ]
        if (
            self.targets.action_types.model_dump(exclude_defaults=True)
            and not target_values
        ):
            raise ValueError("target action_types requires a target id or name")
        filter_values = self.model_dump(exclude_none=True)

        def count_list_values(value: Any) -> int:
            if isinstance(value, list):
                return len(value) + sum(count_list_values(item) for item in value)
            if isinstance(value, dict):
                return sum(count_list_values(item) for item in value.values())
            return 0

        if count_list_values(filter_values) > 200:
            raise ValueError("advanced search accepts at most 200 list values")
        return self


DEAL_SORTS: dict[str, tuple[str, str]] = {
    "id": ("result.id", "id"),
    "date_start": ("result.date_start", "date_start"),
    "date_change_last": ("result.date_change_last", "date_change_last"),
    "total_projected_current": (
        "result.total_projected_current_millions",
        "total_projected_current_millions",
    ),
    "total_paid": ("result.total_paid_millions", "total_paid_millions"),
}

ASSET_SORTS: dict[str, tuple[str, str]] = {
    "id": ("result.id", "id"),
    "asset_name": ("result.name_display", "name_display"),
    "phase": ("result.phase_rank", "phase_rank"),
    "deal_count": ("result.deal_count", "deal_count"),
    "latest_deal_date": ("result.latest_deal_date", "latest_deal_date"),
    "maximum_projected_value": (
        "result.max_total_projected_current_millions",
        "max_total_projected_current_millions",
    ),
}


def _clean_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class _Params:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {"finance_parser_version": FINANCE_PARSER_VERSION}
        self.counter = 0

    def add(self, value: Any, prefix: str = "value") -> str:
        self.counter += 1
        key = f"{prefix}_{self.counter}"
        self.values[key] = value
        return f":{key}"


def _text_expression(column: str, value: str, mode: MatchMode, params: _Params) -> str:
    if mode == "exact":
        return f"LOWER({column}) = LOWER({params.add(value, 'text')})"
    return f"{column} ILIKE {params.add(f'%{value}%', 'text')}"


def _scalar_text_filter(
    column: str,
    values: TextValues,
    params: _Params,
) -> list[str]:
    conditions = []
    if values.include:
        matches = [
            _text_expression(column, value, values.match_mode, params)
            for value in values.include
        ]
        conditions.append(f"({' OR '.join(matches)})")
    if values.exclude:
        matches = [
            _text_expression(column, value, values.match_mode, params)
            for value in values.exclude
        ]
        conditions.append(f"({column} IS NULL OR NOT ({' OR '.join(matches)}))")
    return conditions


def _company_match(criterion: CompanyCriterion, params: _Params) -> str:
    parts = []
    if criterion.id is not None:
        parts.append(f"company.id = {params.add(criterion.id, 'company_id')}")
    else:
        name_match = _text_expression(
            "company.name", criterion.name or "", criterion.match_mode, params
        )
        alias_match = _text_expression(
            "alias.alias_value", criterion.name or "", criterion.match_mode, params
        )
        parts.append(
            f"({name_match} OR EXISTS ("
            "SELECT 1 FROM company_xref xref "
            "JOIN company_aliases alias ON alias.xref_id=xref.id "
            f"WHERE xref.cortellis_id=company.id AND {alias_match}))"
        )
    if criterion.roles:
        parts.append(f"company_link.role = ANY({params.add(criterion.roles, 'roles')})")
    return " AND ".join(parts)


def _company_filters(filters: CompanyFilters, params: _Params) -> list[str]:
    def exists(criterion: CompanyCriterion) -> str:
        return (
            "EXISTS (SELECT 1 FROM deal_companies company_link "
            "JOIN companies company ON company.id=company_link.company_id "
            "WHERE company_link.deal_id=deal.id AND "
            f"{_company_match(criterion, params)})"
        )

    conditions = []
    if filters.any:
        conditions.append(f"({' OR '.join(exists(item) for item in filters.any)})")
    conditions.extend(exists(item) for item in filters.all)
    if filters.exclude:
        conditions.append(
            f"NOT ({' OR '.join(exists(item) for item in filters.exclude)})"
        )
    return conditions


def _asset_identity_match(
    value: str,
    mode: MatchMode,
    params: _Params,
    *,
    drug_alias: str,
) -> str:
    name = _text_expression(f"{drug_alias}.name_display", value, mode, params)
    alias = _text_expression("asset_alias.alias_value", value, mode, params)
    return (
        f"({name} OR EXISTS (SELECT 1 FROM drug_aliases asset_alias "
        f"WHERE asset_alias.drug_id={drug_alias}.id AND {alias}))"
    )


def _related_text_condition(
    values: RelatedTextValues,
    match_sql,
) -> list[str]:
    conditions = []
    if values.any:
        conditions.append(f"({' OR '.join(match_sql(value) for value in values.any)})")
    conditions.extend(match_sql(value) for value in values.all)
    if values.exclude:
        conditions.append(
            f"NOT ({' OR '.join(match_sql(value) for value in values.exclude)})"
        )
    return conditions


def _asset_filters(
    filters: AssetFilters,
    params: _Params,
    *,
    asset_search: bool,
) -> list[str]:
    drug_alias = "drug" if asset_search else "candidate_drug"

    def identity(value: str) -> str:
        match = _asset_identity_match(
            value, filters.names.match_mode, params, drug_alias=drug_alias
        )
        if asset_search:
            return match
        return (
            "EXISTS (SELECT 1 FROM deal_drugs identity_link "
            "JOIN drugs candidate_drug ON candidate_drug.id=identity_link.drug_id "
            f"WHERE identity_link.deal_id=deal.id AND {match})"
        )

    conditions = []
    if filters.ids:
        placeholder = params.add(filters.ids, "asset_ids")
        if asset_search:
            conditions.append(f"drug.id = ANY({placeholder})")
        else:
            conditions.append(
                "EXISTS (SELECT 1 FROM deal_drugs asset_id_link "
                f"WHERE asset_id_link.deal_id=deal.id AND asset_id_link.drug_id=ANY({placeholder}))"
            )
    conditions.extend(_related_text_condition(filters.names, identity))

    phase_column = (
        "drug.phase_highest_now" if asset_search else "phase_drug.phase_highest_now"
    )

    def phase_exists(value: str) -> str:
        expression = _text_expression(
            phase_column, value, filters.phases.match_mode, params
        )
        if asset_search:
            return expression
        return (
            "EXISTS (SELECT 1 FROM deal_drugs phase_link "
            "JOIN drugs phase_drug ON phase_drug.id=phase_link.drug_id "
            f"WHERE phase_link.deal_id=deal.id AND {expression})"
        )

    if asset_search:
        conditions.extend(_scalar_text_filter(phase_column, filters.phases, params))
    else:
        if filters.phases.include:
            conditions.append(
                f"({' OR '.join(phase_exists(value) for value in filters.phases.include)})"
            )
        if filters.phases.exclude:
            conditions.append(
                f"NOT ({' OR '.join(phase_exists(value) for value in filters.phases.exclude)})"
            )

    conditions.extend(
        _scalar_text_filter("deal.asset_type", filters.asset_types, params)
    )
    return conditions


def _modality_filters(
    filters: RelatedTextValues,
    params: _Params,
    *,
    asset_search: bool,
    allow_asset: bool,
    allow_deal: bool,
    allow_public: bool,
) -> list[str]:
    def match(value: str) -> str:
        matches = []
        if allow_deal:
            technology = _text_expression(
                "technology.name", value, filters.match_mode, params
            )
            matches.append(
                "EXISTS (SELECT 1 FROM deal_technologies modality_link "
                "JOIN technologies technology ON technology.id=modality_link.technology_id "
                f"WHERE modality_link.deal_id=deal.id AND {technology})"
            )
        if allow_asset and allow_public:
            public_drug = "drug" if asset_search else "modality_drug"
            public_type = _text_expression(
                "profile.drug_type", value, filters.match_mode, params
            )
            chembl_type = _text_expression(
                "chembl.molecule_type", value, filters.match_mode, params
            )
            public_match = (
                f"(EXISTS (SELECT 1 FROM public_drug_profiles profile WHERE profile.drug_id={public_drug}.id "
                f"AND {public_type}) OR EXISTS (SELECT 1 FROM drug_chembl_records chembl "
                f"WHERE chembl.drug_id={public_drug}.id AND {chembl_type}))"
            )
            if asset_search:
                matches.append(public_match)
            else:
                matches.append(
                    "EXISTS (SELECT 1 FROM deal_drugs modality_asset_link "
                    "JOIN drugs modality_drug ON modality_drug.id=modality_asset_link.drug_id "
                    f"WHERE modality_asset_link.deal_id=deal.id AND {public_match})"
                )
        return f"({' OR '.join(matches)})" if matches else "FALSE"

    return _related_text_condition(filters, match)


def _concept_filters(
    filters: ConceptFilters,
    params: _Params,
    *,
    concept: Literal["target", "disease"],
    asset_search: bool,
    allow_asset: bool,
    allow_deal: bool,
    allow_public: bool,
) -> list[str]:
    def public_match(value: str, mode: MatchMode) -> str:
        drug_alias = "drug" if asset_search else f"{concept}_drug"
        if concept == "target":
            value_match = (
                f"(target.ensembl_id = {params.add(value, 'target_id')} OR "
                f"{_text_expression('target.approved_symbol', value, mode, params)} OR "
                f"{_text_expression('target.approved_name', value, mode, params)})"
            )
            action_conditions = _scalar_text_filter(
                "target_link.action_type", filters.action_types, params
            )
            extra = (
                f" AND {' AND '.join(action_conditions)}" if action_conditions else ""
            )
            exists = (
                "EXISTS (SELECT 1 FROM public_drug_target_links target_link "
                "JOIN public_targets target ON target.ensembl_id=target_link.ensembl_id "
                f"WHERE target_link.drug_id={drug_alias}.id AND {value_match}{extra})"
            )
        else:
            value_match = (
                f"(disease.disease_id = {params.add(value, 'disease_id')} OR "
                f"{_text_expression('disease.name', value, mode, params)})"
            )
            exists = (
                "EXISTS (SELECT 1 FROM public_drug_disease_links disease_link "
                "JOIN public_diseases disease ON disease.disease_id=disease_link.disease_id "
                f"WHERE disease_link.drug_id={drug_alias}.id AND {value_match})"
            )
        if asset_search:
            return exists
        return (
            f"EXISTS (SELECT 1 FROM deal_drugs {concept}_asset_link "
            f"JOIN drugs {drug_alias} ON {drug_alias}.id={concept}_asset_link.drug_id "
            f"WHERE {concept}_asset_link.deal_id=deal.id AND {exists})"
        )

    def deal_match(value: str, mode: MatchMode) -> str:
        if concept == "target":
            expression = _text_expression("action.name", value, mode, params)
            action_conditions = _scalar_text_filter(
                "action_link.action_type", filters.action_types, params
            )
            extra = (
                f" AND {' AND '.join(action_conditions)}" if action_conditions else ""
            )
            return (
                "EXISTS (SELECT 1 FROM deal_actions action_link "
                "JOIN actions action ON action.id=action_link.action_id "
                f"WHERE action_link.deal_id=deal.id AND {expression}{extra})"
            )
        expression = _text_expression("indication.name", value, mode, params)
        return (
            "EXISTS (SELECT 1 FROM deal_indications indication_link "
            "JOIN indications indication ON indication.id=indication_link.indication_id "
            f"WHERE indication_link.deal_id=deal.id AND {expression})"
        )

    def match(value: str, mode: MatchMode) -> str:
        matches = []
        if allow_asset and allow_public:
            matches.append(public_match(value, mode))
        if allow_deal:
            matches.append(deal_match(value, mode))
        return f"({' OR '.join(matches)})" if matches else "FALSE"

    values = RelatedTextValues(
        any=[*filters.ids, *filters.names.any],
        all=filters.names.all,
        exclude=filters.names.exclude,
        match_mode=filters.names.match_mode,
    )
    return _related_text_condition(
        values, lambda value: match(value, values.match_mode)
    )


def _deal_filters(filters: DealFilters, params: _Params) -> list[str]:
    conditions = []
    for column, values in (
        ("deal.deal_type", filters.types),
        ("deal.agreement_type", filters.agreement_types),
        ("deal.transaction_type", filters.transaction_types),
        ("deal.status", filters.statuses),
        ("deal.phase_highest_now", filters.phases),
    ):
        conditions.extend(_scalar_text_filter(column, values, params))

    def territory(value: str) -> str:
        expression = (
            f"(territory.id = {params.add(value.upper(), 'territory_id')} OR "
            f"{_text_expression('territory.name', value, filters.territories.match_mode, params)})"
        )
        return (
            "EXISTS (SELECT 1 FROM deal_territories territory_link "
            "JOIN territories territory ON territory.id=territory_link.territory_id "
            f"WHERE territory_link.deal_id=deal.id AND {expression})"
        )

    conditions.extend(_related_text_condition(filters.territories, territory))
    for column, value in (
        ("deal.is_optional", filters.is_optional),
        ("deal.is_merger_acquisition", filters.is_merger_acquisition),
        ("deal.has_contract", filters.has_contract),
    ):
        if value is not None:
            conditions.append(f"{column} IS {str(value).upper()}")
    return conditions


def _date_filters(ranges: list[DateRange], params: _Params) -> list[str]:
    conditions = []
    columns = {
        "date_start": "deal.date_start",
        "date_end": "deal.date_end",
        "date_change_last": "deal.date_change_last",
        "date_added": "deal.date_added",
        "date_event_most_recent": "deal.date_event_most_recent",
    }
    for item in ranges:
        if item.field in columns:
            column = columns[item.field]
            parts = []
            if item.gte:
                parts.append(f"{column}::date >= {params.add(item.gte, 'date_gte')}")
            if item.lte:
                parts.append(f"{column}::date <= {params.add(item.lte, 'date_lte')}")
            conditions.append(" AND ".join(parts))
        elif item.field == "active_during":
            parts = []
            if item.lte:
                parts.append(
                    f"deal.date_start::date <= {params.add(item.lte, 'active_lte')}"
                )
            if item.gte:
                parts.append(
                    "(deal.date_end IS NULL OR deal.date_end::date >= "
                    f"{params.add(item.gte, 'active_gte')})"
                )
            conditions.append(" AND ".join(parts))
        elif item.field == "timeline_event_date":
            parts = ["timeline.deal_id=deal.id"]
            if item.gte:
                parts.append(
                    f"timeline.event_date::date >= {params.add(item.gte, 'timeline_gte')}"
                )
            if item.lte:
                parts.append(
                    f"timeline.event_date::date <= {params.add(item.lte, 'timeline_lte')}"
                )
            conditions.append(
                f"EXISTS (SELECT 1 FROM deal_timeline_events timeline WHERE {' AND '.join(parts)})"
            )
        else:
            parts = ["contract.deal_id=deal.id"]
            contract_date = "COALESCE(contract.date_contract, contract.date_filing)"
            if item.gte:
                parts.append(
                    f"{contract_date}::date >= {params.add(item.gte, 'contract_gte')}"
                )
            if item.lte:
                parts.append(
                    f"{contract_date}::date <= {params.add(item.lte, 'contract_lte')}"
                )
            conditions.append(
                f"EXISTS (SELECT 1 FROM deal_contracts contract WHERE {' AND '.join(parts)})"
            )
    return conditions


def _range_parts(expression: str, item: NumericRange, params: _Params) -> list[str]:
    parts = []
    if item.gte is not None:
        parts.append(f"{expression} >= {params.add(item.gte, 'number_gte')}")
    if item.lte is not None:
        parts.append(f"{expression} <= {params.add(item.lte, 'number_lte')}")
    return parts


def _millions_expression(amount: str, unit: str) -> str:
    """Normalize Cortellis K/M/B summary values into millions."""
    return (
        "(CASE UPPER(COALESCE(" + unit + ", '')) "
        f"WHEN 'B' THEN {amount} * 1000 "
        f"WHEN 'BILLION' THEN {amount} * 1000 "
        f"WHEN 'K' THEN {amount} / 1000 "
        f"WHEN 'THOUSAND' THEN {amount} / 1000 "
        f"WHEN 'M' THEN {amount} "
        f"WHEN 'MILLION' THEN {amount} "
        "ELSE NULL END)"
    )


def _value_filters(
    filters: ValueFilters,
    params: _Params,
    missing_data: MissingDataMode,
) -> list[str]:
    conditions = []
    summaries = (
        (
            filters.total_paid_millions,
            "finance.total_paid_amount",
            "finance.total_paid_unit",
            "finance.total_paid_currency",
            "finance.total_paid_disclosure_status",
        ),
        (
            filters.total_projected_current_millions,
            "finance.total_projected_current_amount",
            "finance.total_projected_current_unit",
            "finance.total_projected_current_currency",
            "finance.total_projected_current_disclosure_status",
        ),
        (
            filters.total_projected_signing_millions,
            "finance.total_projected_signing_amount",
            "finance.total_projected_signing_unit",
            "finance.total_projected_signing_currency",
            "finance.total_projected_signing_disclosure_status",
        ),
    )
    for item, amount, unit, currency, disclosure in summaries:
        if item is None:
            continue
        parts = _range_parts(_millions_expression(amount, unit), item, params)
        parts.append(
            f"UPPER({currency}) = ANY({params.add(item.currencies, 'currencies')})"
        )
        if item.disclosure_status:
            parts.append(
                f"{disclosure} = ANY({params.add(item.disclosure_status, 'disclosure')})"
            )
        condition = f"({' AND '.join(parts)})"
        if missing_data == "include_as_unknown":
            condition = f"({condition} OR {amount} IS NULL)"
        conditions.append(condition)

    for item, term_type, expression in (
        (filters.upfront_usd_millions, "upfront_payment", "term.amount_usd_millions"),
        (filters.milestone_usd_millions, "milestone_total", "term.amount_usd_millions"),
        (
            filters.royalty_rate_pct,
            "royalty_rate",
            "GREATEST(term.rate_min_pct, term.rate_max_pct)",
        ),
    ):
        if item is None:
            continue
        parts = [
            "term.deal_id=deal.id",
            f"term.parser_version={params.add(FINANCE_PARSER_VERSION, 'parser_version')}",
            f"term.term_type={params.add(term_type, 'term_type')}",
            *_range_parts(expression, item, params),
        ]
        if item.basis:
            parts.append(f"term.basis=ANY({params.add(item.basis, 'term_basis')})")
        if item.disclosure_status:
            parts.append(
                "term.disclosure_status=ANY("
                f"{params.add(item.disclosure_status, 'term_disclosure')})"
            )
        exists = (
            "EXISTS (SELECT 1 FROM deal_financial_terms term WHERE "
            f"{' AND '.join(parts)})"
        )
        if missing_data == "include_as_unknown":
            known = (
                "EXISTS (SELECT 1 FROM deal_financial_terms known_term WHERE "
                "known_term.deal_id=deal.id AND "
                f"known_term.parser_version={params.add(FINANCE_PARSER_VERSION, 'known_parser')} "
                f"AND known_term.term_type={params.add(term_type, 'known_type')})"
            )
            exists = f"({exists} OR NOT {known})"
        conditions.append(exists)
    return conditions


def _active_filter_categories(request: AdvancedSearchRequest) -> list[str]:
    categories = []
    if request.query:
        categories.append("query")
    for name in ("companies", "assets", "targets", "diseases", "deals", "values"):
        value = getattr(request, name)
        if value.model_dump(exclude_defaults=True, exclude_none=True):
            categories.append(name)
    if request.dates:
        categories.append("dates")
    if request.evidence != EvidenceFilters():
        categories.append("evidence")
    return categories


def _validate_monetary_sort(
    request: AdvancedSearchRequest,
    endpoint: Literal["deals", "assets"],
) -> None:
    """Prevent comparisons that mix source currencies."""
    sorts = request.sort or []
    for sort in sorts:
        money_filter: MoneyRange | None = None
        if sort.field == "total_paid":
            money_filter = request.values.total_paid_millions
        elif sort.field in {"total_projected_current", "maximum_projected_value"}:
            money_filter = request.values.total_projected_current_millions
        else:
            continue
        if money_filter is None or len(money_filter.currencies) != 1:
            raise ValueError(
                f"Sort field {sort.field} requires the corresponding value filter "
                "with exactly one currency"
            )
        if endpoint == "assets" and sort.field == "total_projected_current":
            raise ValueError(
                "Sort field total_projected_current is not valid for assets search"
            )


def _query_hash(request: AdvancedSearchRequest, endpoint: str) -> str:
    payload = request.model_dump(mode="json", exclude_none=True)
    payload.pop("cursor", None)
    canonical = json.dumps(
        {"endpoint": endpoint, "request": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()[:24]


def _encode_cursor(
    endpoint: str, query_hash: str, values: list[Any], row_id: int
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "endpoint": endpoint,
            "query_hash": query_hash,
            "values": values,
            "id": row_id,
        },
        default=str,
        separators=(",", ":"),
    ).encode()
    return urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str, endpoint: str, query_hash: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid search cursor") from exc
    if (
        payload.get("v") != 1
        or payload.get("endpoint") != endpoint
        or payload.get("query_hash") != query_hash
        or not isinstance(payload.get("values"), list)
        or not isinstance(payload.get("id"), int)
    ):
        raise ValueError("Search cursor does not match this query")
    return payload


def _sort_clause(
    request: AdvancedSearchRequest,
    endpoint: Literal["deals", "assets"],
    params: _Params,
    query_hash: str,
) -> tuple[str, str, list[tuple[str, str]]]:
    allowed = DEAL_SORTS if endpoint == "deals" else ASSET_SORTS
    defaults = (
        [SortSpec(field="date_change_last", direction="desc")]
        if endpoint == "deals"
        else [SortSpec(field="asset_name", direction="asc")]
    )
    specs = request.sort or defaults
    resolved = []
    for spec in specs:
        if spec.field not in allowed:
            raise ValueError(
                f"Sort field {spec.field} is not valid for {endpoint} search"
            )
        expression, key = allowed[spec.field]
        resolved.append((expression, key, spec.direction))

    cursor_condition = ""
    if request.cursor:
        cursor = _decode_cursor(request.cursor, endpoint, query_hash)
        if len(cursor["values"]) != len(resolved):
            raise ValueError("Search cursor sort does not match this query")
        after_terms = []
        equal_prefix = []
        for index, ((expression, _key, direction), value) in enumerate(
            zip(resolved, cursor["values"])
        ):
            placeholder = params.add(value, f"cursor_{index}")
            if value is None:
                after = "FALSE"
                equal = f"{expression} IS NULL"
            else:
                operator = ">" if direction == "asc" else "<"
                after = (
                    f"({expression} {operator} {placeholder} OR {expression} IS NULL)"
                )
                equal = f"{expression} = {placeholder}"
            prefix = " AND ".join(equal_prefix)
            after_terms.append(f"({prefix} AND {after})" if prefix else after)
            equal_prefix.append(equal)
        id_after = f"result.id > {params.add(cursor['id'], 'cursor_id')}"
        prefix = " AND ".join(equal_prefix)
        after_terms.append(f"({prefix} AND {id_after})" if prefix else id_after)
        cursor_condition = f"WHERE {' OR '.join(after_terms)}"

    order = ", ".join(
        f"{expression} {direction.upper()} NULLS LAST"
        for expression, _key, direction in resolved
    )
    order += ", result.id ASC"
    return (
        cursor_condition,
        order,
        [(key, direction) for _expr, key, direction in resolved],
    )


def _deal_predicates(
    request: AdvancedSearchRequest,
    params: _Params,
    *,
    asset_search: bool,
    allow_public_biology: bool,
) -> list[str]:
    attribution = set(request.evidence.allowed_attribution)
    sources = set(request.evidence.sources)
    allow_public = allow_public_biology and "public_biology" in sources
    conditions = ["TRUE"]
    if request.query:
        query = params.add(f"%{request.query}%", "query")
        if asset_search:
            conditions.append(
                "(deal.title ILIKE {query} OR deal.summary ILIKE {query} OR "
                "drug.name_display ILIKE {query} OR EXISTS (SELECT 1 FROM "
                "drug_aliases query_alias WHERE query_alias.drug_id=drug.id "
                "AND query_alias.alias_value ILIKE {query}))".format(query=query)
            )
        else:
            conditions.append(
                "(deal.title ILIKE {query} OR deal.summary ILIKE {query} OR "
                "EXISTS (SELECT 1 FROM deal_drugs query_link JOIN drugs query_drug "
                "ON query_drug.id=query_link.drug_id WHERE query_link.deal_id=deal.id "
                "AND (query_drug.name_display ILIKE {query} OR EXISTS (SELECT 1 "
                "FROM drug_aliases query_alias WHERE "
                "query_alias.drug_id=query_drug.id AND "
                "query_alias.alias_value ILIKE {query}))) OR EXISTS (SELECT 1 "
                "FROM deal_companies query_company_link JOIN companies query_company "
                "ON query_company.id=query_company_link.company_id WHERE "
                "query_company_link.deal_id=deal.id AND "
                "query_company.name ILIKE {query}))".format(query=query)
            )
    conditions.extend(_company_filters(request.companies, params))
    conditions.extend(_asset_filters(request.assets, params, asset_search=asset_search))
    conditions.extend(
        _modality_filters(
            request.assets.modalities,
            params,
            asset_search=asset_search,
            allow_asset="asset" in attribution,
            allow_deal="deal" in attribution and "cortellis_deals" in sources,
            allow_public=allow_public,
        )
    )
    conditions.extend(
        _concept_filters(
            request.targets,
            params,
            concept="target",
            asset_search=asset_search,
            allow_asset="asset" in attribution,
            allow_deal="deal" in attribution and "cortellis_deals" in sources,
            allow_public=allow_public,
        )
    )
    conditions.extend(
        _concept_filters(
            request.diseases,
            params,
            concept="disease",
            asset_search=asset_search,
            allow_asset="asset" in attribution,
            allow_deal="deal" in attribution and "cortellis_deals" in sources,
            allow_public=allow_public,
        )
    )
    conditions.extend(_deal_filters(request.deals, params))
    conditions.extend(_date_filters(request.dates, params))
    conditions.extend(
        _value_filters(request.values, params, request.evidence.missing_data)
    )
    return conditions


def _deal_result_sql(
    where: str,
    *,
    include_public_biology: bool,
    include_deal_evidence: bool,
) -> str:
    public_asset_fields = (
        """,
                  'targets', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', public_target.ensembl_id,
                    'name', public_target.approved_symbol,
                    'action_type', public_target_link.action_type,
                    'source', public_target_link.source,
                    'attribution', 'asset'
                  ) ORDER BY public_target.approved_symbol)
                  FROM public_drug_target_links public_target_link
                  JOIN public_targets public_target
                    ON public_target.ensembl_id=public_target_link.ensembl_id
                  WHERE public_target_link.drug_id=drug.id), '[]'::jsonb),
                  'diseases', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', public_disease.disease_id,
                    'name', public_disease.name,
                    'source', public_disease_link.source,
                    'attribution', 'asset'
                  ) ORDER BY public_disease.name)
                  FROM public_drug_disease_links public_disease_link
                  JOIN public_diseases public_disease
                    ON public_disease.disease_id=public_disease_link.disease_id
                  WHERE public_disease_link.drug_id=drug.id), '[]'::jsonb),
                  'modalities', COALESCE((SELECT jsonb_agg(
                    DISTINCT to_jsonb(public_modality))
                  FROM (
                    SELECT profile.drug_type::text AS name,
                           profile.source::text AS source,
                           'asset'::text AS attribution
                    FROM public_drug_profiles profile
                    WHERE profile.drug_id=drug.id
                      AND NULLIF(BTRIM(profile.drug_type), '') IS NOT NULL
                    UNION
                    SELECT chembl.molecule_type::text AS name,
                           'ChEMBL'::text AS source,
                           'asset'::text AS attribution
                    FROM drug_chembl_records chembl
                    WHERE chembl.drug_id=drug.id
                      AND NULLIF(BTRIM(chembl.molecule_type), '') IS NOT NULL
                  ) public_modality), '[]'::jsonb)
        """
        if include_public_biology
        else ""
    )
    deal_diseases = (
        """COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', indication.id, 'name', indication.name,
                  'is_principal', link.is_principal,
                  'attribution', 'deal'
              ) ORDER BY link.is_principal DESC, indication.name)
              FROM deal_indications link JOIN indications indication
                ON indication.id=link.indication_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb)"""
        if include_deal_evidence
        else "'[]'::jsonb"
    )
    deal_modalities = (
        """COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', technology.id, 'name', technology.name,
                  'is_principal', link.is_principal,
                  'attribution', 'deal'
              ) ORDER BY link.is_principal DESC, technology.name)
              FROM deal_technologies link JOIN technologies technology
                ON technology.id=link.technology_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb)"""
        if include_deal_evidence
        else "'[]'::jsonb"
    )
    deal_targets = (
        """COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', action.id, 'name', action.name,
                  'action_type', link.action_type,
                  'attribution', 'deal'
              ) ORDER BY link.action_type, action.name)
              FROM deal_actions link JOIN actions action ON action.id=link.action_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb)"""
        if include_deal_evidence
        else "'[]'::jsonb"
    )
    return f"""
        WITH filtered AS (
            SELECT deal.id, deal.title, deal.summary, deal.deal_type,
                   deal.agreement_type, deal.transaction_type, deal.asset_type,
                   deal.status, deal.is_optional, deal.is_merger_acquisition,
                   deal.has_contract, deal.phase_highest_start,
                   deal.phase_highest_now, deal.date_start, deal.date_end,
                   deal.date_event_most_recent, deal.date_change_last,
                   deal.date_added,
                   finance.total_paid_amount, finance.total_paid_unit,
                   finance.total_paid_currency,
                   finance.total_paid_disclosure_status,
                   {_millions_expression("finance.total_paid_amount", "finance.total_paid_unit")}
                     AS total_paid_millions,
                   finance.total_projected_current_amount,
                   finance.total_projected_current_unit,
                   finance.total_projected_current_currency,
                   finance.total_projected_current_disclosure_status,
                   {_millions_expression("finance.total_projected_current_amount", "finance.total_projected_current_unit")}
                     AS total_projected_current_millions,
                   finance.total_projected_signing_amount,
                   finance.total_projected_signing_unit,
                   finance.total_projected_signing_currency,
                   finance.total_projected_signing_disclosure_status,
                   {_millions_expression("finance.total_projected_signing_amount", "finance.total_projected_signing_unit")}
                     AS total_projected_signing_millions
            FROM deals deal
            LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
            WHERE {where}
        ),
        result AS (
            SELECT filtered.*,
              COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', company.id, 'name', company.name, 'role', link.role
              ) ORDER BY link.role, company.name)
              FROM deal_companies link JOIN companies company
                ON company.id=link.company_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb) AS companies,
              COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', drug.id, 'name', drug.name_display,
                  'phase', drug.phase_highest_now,
                  'attribution', 'asset'
                  {public_asset_fields}
              ) ORDER BY drug.name_display, drug.id)
              FROM deal_drugs link JOIN drugs drug ON drug.id=link.drug_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb) AS assets,
              {deal_diseases} AS diseases,
              {deal_modalities} AS modalities,
              {deal_targets} AS targets,
              COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'id', territory.id, 'name', territory.name,
                  'territory_type', link.territory_type
              ) ORDER BY link.territory_type, territory.name)
              FROM deal_territories link JOIN territories territory
                ON territory.id=link.territory_id
              WHERE link.deal_id=filtered.id), '[]'::jsonb) AS territories,
              COALESCE((SELECT jsonb_agg(jsonb_build_object(
                  'source_id', source.source_id,
                  'source_type', source.source_type
              ) ORDER BY source.source_type, source.source_id)
              FROM cortellis_deal_sources source
              WHERE source.deal_id=filtered.id AND source.is_current=TRUE),
              '[]'::jsonb) AS source_citations
            FROM filtered
        )
    """


def _asset_result_sql(
    where: str,
    *,
    include_public_biology: bool,
    include_deal_evidence: bool,
) -> str:
    target_queries = []
    disease_queries = []
    modality_queries = []
    if include_public_biology:
        target_queries.append("""
        SELECT target.ensembl_id::text AS id,
               target.approved_symbol AS name,
               target_link.action_type AS action_type,
               'asset'::text AS attribution,
               target_link.source::text AS source
        FROM public_drug_target_links target_link
        JOIN public_targets target ON target.ensembl_id=target_link.ensembl_id
        WHERE target_link.drug_id=drug.id
        """)
        disease_queries.append("""
        SELECT disease.disease_id::text AS id, disease.name,
               'asset'::text AS attribution,
               disease_link.source::text AS source
        FROM public_drug_disease_links disease_link
        JOIN public_diseases disease ON disease.disease_id=disease_link.disease_id
        WHERE disease_link.drug_id=drug.id
        """)
        modality_queries.extend(
            [
                """
        SELECT profile.drug_type::text AS name,
               'asset'::text AS attribution,
               profile.source::text AS source
        FROM public_drug_profiles profile
        WHERE profile.drug_id=drug.id AND NULLIF(BTRIM(profile.drug_type), '') IS NOT NULL
        """,
                """
        SELECT chembl.molecule_type::text AS name,
               'asset'::text AS attribution,
               'ChEMBL'::text AS source
        FROM drug_chembl_records chembl
        WHERE chembl.drug_id=drug.id AND NULLIF(BTRIM(chembl.molecule_type), '') IS NOT NULL
        """,
            ]
        )
    if include_deal_evidence:
        target_queries.append("""
        SELECT action.id::text AS id, action.name::text AS name,
               action_link.action_type::text AS action_type,
               'deal'::text AS attribution,
               'Cortellis Deals'::text AS source
        FROM matched target_match
        JOIN deal_actions action_link
          ON action_link.deal_id=target_match.deal_id
        JOIN actions action ON action.id=action_link.action_id
        WHERE target_match.asset_id=drug.id
        """)
        disease_queries.append("""
        SELECT indication.id::text AS id, indication.name::text AS name,
               'deal'::text AS attribution,
               'Cortellis Deals'::text AS source
        FROM matched disease_match
        JOIN deal_indications disease_link
          ON disease_link.deal_id=disease_match.deal_id
        JOIN indications indication
          ON indication.id=disease_link.indication_id
        WHERE disease_match.asset_id=drug.id
        """)
        modality_queries.append("""
        SELECT technology.name::text AS name,
               'deal'::text AS attribution,
               'Cortellis Deals'::text AS source
        FROM matched modality_match
        JOIN deal_technologies modality_link
          ON modality_link.deal_id=modality_match.deal_id
        JOIN technologies technology
          ON technology.id=modality_link.technology_id
        WHERE modality_match.asset_id=drug.id
        """)
    targets_sql = " UNION ".join(target_queries) or (
        "SELECT NULL::text AS id, NULL::text AS name, NULL::text AS action_type, "
        "NULL::text AS attribution, NULL::text AS source WHERE FALSE"
    )
    diseases_sql = " UNION ".join(disease_queries) or (
        "SELECT NULL::text AS id, NULL::text AS name, NULL::text AS attribution, "
        "NULL::text AS source WHERE FALSE"
    )
    modalities_sql = " UNION ".join(modality_queries) or (
        "SELECT NULL::text AS name, NULL::text AS attribution, "
        "NULL::text AS source WHERE FALSE"
    )
    return f"""
        WITH matched AS (
            SELECT DISTINCT drug.id AS asset_id, deal.id AS deal_id,
                   deal.date_start, deal.date_change_last,
                   finance.total_projected_current_amount,
                   finance.total_projected_current_unit,
                   {_millions_expression("finance.total_projected_current_amount", "finance.total_projected_current_unit")}
                     AS total_projected_current_millions,
                   finance.total_projected_current_currency
            FROM deal_drugs seed_link
            JOIN drugs drug ON drug.id=seed_link.drug_id
            JOIN deals deal ON deal.id=seed_link.deal_id
            LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
            WHERE {where}
        ),
        result AS (
            SELECT drug.id, drug.name_display, drug.phase_highest_start,
                   drug.phase_highest_now,
                   CASE drug.phase_highest_now
                     WHEN 'Discovery' THEN 1 WHEN 'Preclinical' THEN 2
                     WHEN 'Phase 1 Clinical' THEN 3 WHEN 'Clinical' THEN 3
                     WHEN 'Phase 2 Clinical' THEN 4
                     WHEN 'Phase 3 Clinical' THEN 5
                     WHEN 'Pre-registration' THEN 6 WHEN 'Registered' THEN 7
                     WHEN 'Launched' THEN 8 ELSE 0 END AS phase_rank,
                   COUNT(DISTINCT matched.deal_id)::int AS deal_count,
                   MAX(matched.date_start) AS latest_deal_date,
                   MAX(matched.date_change_last) AS latest_deal_change,
                   CASE WHEN COUNT(DISTINCT
                     matched.total_projected_current_currency)
                     FILTER (WHERE matched.total_projected_current_millions
                       IS NOT NULL) <= 1
                   THEN MAX(matched.total_projected_current_millions)
                   ELSE NULL END AS max_total_projected_current_millions,
                   ARRAY_REMOVE(ARRAY_AGG(DISTINCT
                     matched.total_projected_current_currency), NULL)
                     AS projected_value_currencies,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                     'currency', projected.currency,
                     'maximum_millions', projected.maximum_millions
                   ) ORDER BY projected.currency)
                   FROM (
                     SELECT value_match.total_projected_current_currency AS currency,
                            MAX(value_match.total_projected_current_millions)
                              AS maximum_millions
                     FROM matched value_match
                     WHERE value_match.asset_id=drug.id
                       AND value_match.total_projected_current_millions IS NOT NULL
                       AND value_match.total_projected_current_currency IS NOT NULL
                     GROUP BY value_match.total_projected_current_currency
                   ) projected), '[]'::jsonb) AS projected_values_by_currency,
                   ARRAY_AGG(DISTINCT matched.deal_id ORDER BY matched.deal_id)
                     AS evidence_deal_ids,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                     'value', alias.alias_value, 'type', alias.alias_type,
                     'source', alias.source, 'confidence', alias.confidence,
                     'review_status', alias.review_status
                   ) ORDER BY alias.alias_value)
                   FROM drug_aliases alias WHERE alias.drug_id=drug.id),
                   '[]'::jsonb) AS aliases,
                   COALESCE((SELECT jsonb_agg(DISTINCT jsonb_build_object(
                     'id', company.id, 'name', company.name, 'role', company_link.role,
                     'relationship_basis', 'deal_referenced',
                     'ownership_or_control_established', false
                   )) FROM matched company_match
                   JOIN deal_companies company_link
                     ON company_link.deal_id=company_match.deal_id
                   JOIN companies company ON company.id=company_link.company_id
                   WHERE company_match.asset_id=drug.id), '[]'::jsonb) AS companies,
                   COALESCE((SELECT jsonb_agg(DISTINCT to_jsonb(modality_row))
                   FROM ({modalities_sql}) modality_row), '[]'::jsonb) AS modalities,
                   COALESCE((SELECT jsonb_agg(DISTINCT to_jsonb(target_row))
                   FROM ({targets_sql}) target_row), '[]'::jsonb) AS targets,
                   COALESCE((SELECT jsonb_agg(DISTINCT to_jsonb(disease_row))
                   FROM ({diseases_sql}) disease_row), '[]'::jsonb) AS diseases
            FROM matched JOIN drugs drug ON drug.id=matched.asset_id
            GROUP BY drug.id
        )
    """


def _execute_search(
    session,
    request: AdvancedSearchRequest,
    *,
    endpoint: Literal["deals", "assets"],
    allow_public_biology: bool,
) -> dict[str, Any]:
    _validate_monetary_sort(request, endpoint)
    requested_sources = set(request.evidence.sources)
    requested_attribution = set(request.evidence.allowed_attribution)
    include_public_biology = (
        allow_public_biology
        and "public_biology" in requested_sources
        and "asset" in requested_attribution
    )
    include_deal_evidence = (
        "cortellis_deals" in requested_sources and "deal" in requested_attribution
    )
    params = _Params()
    query_hash = _query_hash(request, endpoint)
    conditions = _deal_predicates(
        request,
        params,
        asset_search=endpoint == "assets",
        allow_public_biology=allow_public_biology,
    )
    where = " AND ".join(f"({condition})" for condition in conditions)
    cte = (
        _deal_result_sql(
            where,
            include_public_biology=include_public_biology,
            include_deal_evidence=include_deal_evidence,
        )
        if endpoint == "deals"
        else _asset_result_sql(
            where,
            include_public_biology=include_public_biology,
            include_deal_evidence=include_deal_evidence,
        )
    )
    cursor_condition, order, sort_keys = _sort_clause(
        request, endpoint, params, query_hash
    )
    params.values["limit"] = request.limit + 1
    rows = (
        session.execute(
            text(f"""
        {cte}
        SELECT * FROM result
        {cursor_condition}
        ORDER BY {order}
        LIMIT :limit
    """),
            params.values,
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > request.limit
    items = [dict(row) for row in rows[: request.limit]]
    active_filters = _active_filter_categories(request)
    for item in items:
        item["matched_filter_categories"] = active_filters
        item["evidence_policy"] = {
            "allowed_attribution": request.evidence.allowed_attribution,
            "sources": request.evidence.sources,
            "public_biology_included": include_public_biology,
            "deal_evidence_included": include_deal_evidence,
            "missing_data": request.evidence.missing_data,
        }

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(
            endpoint,
            query_hash,
            [last[key] for key, _direction in sort_keys],
            int(last["id"]),
        )

    total = None
    if request.include_total:
        total = int(
            session.execute(
                text(f"""
            {cte}
            SELECT COUNT(*) FROM result
        """),
                params.values,
            ).scalar()
            or 0
        )

    return {
        "entity": endpoint[:-1] if endpoint.endswith("s") else endpoint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_hash": query_hash,
        "matched_filter_categories": active_filters,
        "items": items,
        "limit": request.limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "total": total,
        "limitations": [
            "Deal-level modalities, targets, and diseases can describe a multi-asset "
            "program and are labeled with attribution=deal.",
            "Company participation in a deal does not establish asset ownership or "
            "control.",
            "Non-normalized deal totals are compared only within explicitly requested "
            "source currencies; term-level upfront and milestone amounts are USD-normalized.",
            "Unknown or absent evidence is not proof that an event or relationship did "
            "not occur.",
        ],
    }


def search_deals(
    session,
    request: AdvancedSearchRequest,
    *,
    allow_public_biology: bool = True,
) -> dict[str, Any]:
    return _execute_search(
        session,
        request,
        endpoint="deals",
        allow_public_biology=allow_public_biology,
    )


def search_assets(
    session,
    request: AdvancedSearchRequest,
    *,
    allow_public_biology: bool = True,
) -> dict[str, Any]:
    return _execute_search(
        session,
        request,
        endpoint="assets",
        allow_public_biology=allow_public_biology,
    )
