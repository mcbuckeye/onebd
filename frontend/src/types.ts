export type SearchMode = 'auto' | 'sql' | 'rag';

export interface SearchResult {
  deal_id: number;
  deal_title: string;
  contract_id?: number;
  snippet: string;
  relevance: number;
  contract_types?: string;
}

export interface ChatResponse {
  response: string;
  mode_used: string;
  sql_query?: string;
  results_count?: number;
  search_results?: SearchResult[];
  timestamp: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode?: string;
  sqlQuery?: string;
  searchResults?: SearchResult[];
  timestamp: Date;
}

export interface IndexStatus {
  total_text_contracts: number;
  indexed_for_fulltext: number;
  total_chunks: number;
  embedded_chunks: number;
  fulltext_pct: number;
  embedding_pct: number;
}

export interface CompanyInfo {
  id: number;
  name: string;
  role: string;
  company_type?: string;
  hq_location?: string;
}

export interface FinanceSummary {
  total_paid_amount?: number;
  total_paid_currency?: string;
  total_paid_unit?: string;
  total_paid_disclosure_status?: string;
  total_projected_current_amount?: number;
  total_projected_current_currency?: string;
  total_projected_current_unit?: string;
  total_projected_signing_amount?: number;
  total_projected_signing_currency?: string;
  total_projected_signing_unit?: string;
}

export interface TimelineEvent {
  event_date?: string;
  event_type?: string;
  stage?: string;
  summary?: string;
}

export interface EvidenceTimelineEvent {
  event_date?: string | null;
  date_precision?: string | null;
  date_type?: string | null;
  category: 'deal' | 'development' | 'regulatory' | 'clinical_trial' | 'clinical_status';
  event_type: string;
  stage?: string | null;
  summary?: string | null;
  source: string;
  source_record_id: string;
  source_url?: string | null;
  nct_id?: string | null;
  link_method?: string | null;
  citation_evidence: Array<{
    source_type: string;
    source_record_id: number;
    source_sha256: string;
    source_char_start: number;
    source_char_end: number;
    source_excerpt: string;
  }>;
}

export interface EvidenceTimelineSummary {
  event_count: number;
  cortellis_event_count: number;
  explicit_regulatory_event_count: number;
  exact_cited_trial_count: number;
  matched_registry_trial_count: number;
  link_method: string;
  parser_version: number;
}

export interface ContractInfo {
  id: number;
  contract_types?: string;
  date_filing?: string;
  date_contract?: string;
  has_pdf: boolean;
  has_text: boolean;
}

export interface DealSourceInfo {
  source_id: string;
  source_type: string;
}

// Entity types for clickable links
export interface EntityInfo {
  id: number;
  name: string;
}

export interface DrugInfo {
  id: number;
  name: string;
  phase_highest_now?: string;
}

export interface DealDetail {
  id: number;
  title: string;
  deal_type?: string;
  status?: string;
  therapy_area?: string;
  date_start?: string;
  date_end?: string;
  summary?: string;
  agreement_type?: string;
  asset_type?: string;
  transaction_type?: string;
  phase_highest_start?: string;
  phase_highest_now?: string;
  is_merger_acquisition?: boolean;
  companies: CompanyInfo[];
  indications: EntityInfo[];
  technologies: EntityInfo[];
  drugs: DrugInfo[];
  territories_included: string[];
  territories_excluded: string[];
  finance?: FinanceSummary;
  timeline: TimelineEvent[];
  evidence_timeline?: EvidenceTimelineEvent[];
  evidence_timeline_summary?: EvidenceTimelineSummary;
  contracts: ContractInfo[];
  sources?: DealSourceInfo[];
}

// Entity detail types for drill-down views
export interface DealSummary {
  id: number;
  title: string;
  status?: string;
  date_start?: string;
  total_value?: number;
}

export interface EntityDetail {
  id: number;
  name: string;
  entity_type: string;
  deal_count: number;
  deals: DealSummary[];
}

export interface DrugDetail {
  id: number;
  name: string;
  phase_highest_start?: string;
  phase_highest_now?: string;
  deal_count: number;
  deals: DealSummary[];
}

export interface CompanyDetail {
  id: number;
  name: string;
  company_type?: string;
  hq_location?: string;
  deal_count: number;
  deals_as_principal: DealSummary[];
  deals_as_partner: DealSummary[];
}

export type EntityType = 'indication' | 'technology' | 'drug' | 'company';

export interface SelectedEntity {
  type: EntityType;
  id: number;
}
