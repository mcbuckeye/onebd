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
  drug: {
    id: number;
    name: string;
    phase: string;
  };
  deal_history: DealSummary[];
  territory_rights: Array<{ territory: string; holder: string; deal_id: number }>;
  financial_summary: {
    total_value: number | null;
    deal_count: number;
  };
  related_companies: Array<{ id: number; name: string; role: string }>;
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
