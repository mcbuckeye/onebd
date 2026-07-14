import axios from 'axios';

const API_BASE = '/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('bd_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 → redirect to login
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('bd_token');
      localStorage.removeItem('bd_user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

// Typed API helpers
export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
}

export interface DealSummary {
  id: number;
  title: string;
  deal_type: string | null;
  agreement_type: string | null;
  status: string | null;
  date_start: string | null;
  total_value: number | null;
  principal_company: string | null;
  partner_company: string | null;
  principal_company_id: number | null;
  partner_company_id: number | null;
}

export interface SearchFilters {
  therapy_area?: string;
  indication?: string[];
  technology?: string[];
  company?: string;
  deal_type?: string[];
  phase?: string[];
  date_from?: string;
  date_to?: string;
  value_min?: number;
  value_max?: number;
  disclosed_only?: boolean;
  status?: string[];
}

export interface SearchResponse {
  total: number;
  page: number;
  page_size: number;
  results: DealSummary[];
}

export interface FilterOptions {
  therapy_areas: string[];
  deal_types: string[];
  statuses: string[];
  phases: string[];
}

export interface CompanyProfile {
  company: {
    id: number;
    name: string;
    company_type: string;
    ticker: string | null;
  };
  deal_summary: {
    total_deals: number;
    as_principal: number;
    as_partner: number;
    avg_deal_value: number | null;
    total_deal_value: number | null;
  };
  deal_timeline: Array<{ year: number; count: number }>;
  top_partners: Array<{ name: string; deal_count: number }>;
  therapeutic_focus: Array<{ indication: string; count: number }>;
  recent_deals: DealSummary[];
  drugs: Array<{ id: number; name: string; phase: string }>;
  sec_filings: Array<{ id: number; doc_type: string; filing_date: string }>;
}

export interface DrugProfile {
  id: number;
  name: string;
  phase_highest_start: string | null;
  phase_highest_now: string | null;
  total_deals: number;
  total_deal_value: number | null;
  avg_deal_value: number | null;
  deals_with_disclosed_value: number;
  deals_by_year: Array<{
    year: number;
    deal_count: number;
    total_value: number | null;
  }>;
  rights_holders: Array<{
    territory: string;
    rights_holder: string | null;
    rights_holder_id: number | null;
    deal_id: number | null;
    deal_title: string | null;
  }>;
  deals: Array<{
    id: number;
    title: string | null;
    deal_type: string | null;
    status: string | null;
    date_start: string | null;
    total_value: number | null;
    principal_company: string | null;
    principal_company_id: number | null;
    partner_company: string | null;
    partner_company_id: number | null;
    indications: string[];
    territories: string[];
  }>;
  indications: string[];
  technologies: string[];
}

export interface PublicDrugBiology {
  drug: { id: number; name_display: string };
  identifiers: Array<{
    identifier_type: string;
    identifier_value: string;
    source: string;
    source_reference: string | null;
    evidence: Record<string, unknown> | null;
    confidence: number;
    review_status: string;
  }>;
  chembl_records: Array<{
    chembl_id: string;
    standard_inchi_key: string;
    preferred_name: string | null;
    molecule_type: string | null;
    max_phase: number | null;
    first_approval: number | null;
    source_version: string;
    source_url: string;
  }>;
  profiles: Array<{
    chembl_id: string;
    name: string;
    description: string | null;
    drug_type: string | null;
    maximum_clinical_stage: string | null;
    synonyms: Array<{ label: string; source: string }>;
    trade_names: Array<{ label: string; source: string }>;
    cross_references: Array<{ source: string; ids: string[] }>;
    source: string;
    source_version: string;
    source_url: string;
  }>;
  targets: Array<{
    ensembl_id: string;
    approved_symbol: string;
    approved_name: string;
    biotype: string | null;
    protein_ids: Array<{ id: string; source: string }>;
    chembl_id: string;
    mechanism_of_action: string | null;
    action_type: string | null;
    target_name: string | null;
    source_references: Array<Record<string, unknown>>;
    source: string;
    source_version: string;
    literature_count: number;
    uniprot_records: Array<{
      requested_accession: string;
      primary_accession: string;
      uniprot_id: string | null;
      protein_name: string | null;
      gene_symbol: string | null;
      function_text: string | null;
      source_version: string;
      source_url: string;
    }>;
  }>;
  diseases: Array<{
    disease_id: string;
    name: string;
    chembl_id: string;
    maximum_clinical_stage: string | null;
    source_record_id: string | null;
    source: string;
    source_version: string;
  }>;
}

export interface ClinicalTrialsResponse {
  total: number;
  limit: number;
  offset: number;
  trials: Array<{
    nct_id: string;
    brief_title: string;
    official_title: string | null;
    overall_status: string;
    phases: string[];
    study_type: string | null;
    enrollment: number | null;
    start_date: string | null;
    primary_completion_date: string | null;
    completion_date: string | null;
    last_update_posted: string | null;
    lead_sponsor_name: string | null;
    conditions: string[];
    interventions: Array<Record<string, unknown>>;
    has_results: boolean;
    source_url: string;
    linked_drugs: number;
    linked_companies: number;
  }>;
}

export interface DashboardData {
  market_pulse: {
    deal_count_30d: number;
    deal_count_prev_30d: number;
    avg_value_30d: number | null;
    top_therapy_areas: Array<{ name: string; count: number }>;
  };
  notable_deals: DealSummary[];
  alerts: Array<{ id: number; message: string; deal_id?: number; created_at: string }>;
  watchlist_summary: {
    total: number;
    status_changes: number;
  };
}

export interface ChatV2Response {
  answer: string;
  intent: string;
  confidence: {
    data_completeness: string;
    sample_size: number | null;
    disclosure_rate: number | null;
  };
  data: any[] | null;
  sql_query: string | null;
  follow_ups: string[];
  actions: Array<{ label: string; type: string; params: any }>;
}
