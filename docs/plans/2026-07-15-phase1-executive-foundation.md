# Phase 1: Executive Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the BD Intelligence Platform from a chat-only interface into a multi-modal application with executive dashboard, enhanced conversational intelligence, authentication, advanced search UI, and company/drug profile pages.

**Architecture:** The backend (FastAPI, 50+ endpoints) is mostly built. This phase is ~70% frontend work (React + TypeScript + Tailwind) and ~30% backend enhancements (auth system, chat v2 synthesis layer, dashboard aggregation endpoint). The frontend gets a full rebuild from 5 components to ~25+ components with React Router for navigation, Recharts for charts, and TanStack Table for data grids.

**Tech Stack:**
- Frontend: React 18, TypeScript, Vite, Tailwind CSS, React Router v6, Recharts, TanStack Table v8, Lucide icons
- Backend: FastAPI, SQLAlchemy, JWT (python-jose + passlib), OpenAI GPT-4o
- Existing: PostgreSQL 16 + pgvector, Redis, Neo4j, Docker Compose

**Working Directory:** `/Users/kayleighbot/Projects/cortellis`

---

**Methodology:** TDD (Test-Driven Development). For every backend task: write failing tests FIRST, then implement the minimum code to pass, then refactor. Frontend tasks get component tests where meaningful. The existing test infrastructure (`unified_api/tests/`, pytest + httpx + pytest-asyncio) is used throughout.

---

## Overview of Tasks

| Task | Component | Type | Estimated Time |
|------|-----------|------|---------------|
| 1 | Frontend scaffolding + routing | Frontend | 15 min |
| 2A | Authentication backend — TESTS FIRST | Backend/Test | 10 min |
| 2B | Authentication backend — IMPLEMENTATION | Backend | 10 min |
| 3 | Authentication frontend | Frontend | 10 min |
| 4A | Executive dashboard backend — TESTS FIRST | Backend/Test | 10 min |
| 4B | Executive dashboard backend — IMPLEMENTATION | Backend | 10 min |
| 5 | Executive dashboard frontend | Frontend | 20 min |
| 6 | Advanced search page | Frontend | 20 min |
| 7 | Company profile page | Frontend | 15 min |
| 8 | Drug profile page | Frontend | 10 min |
| 9A | Enhanced chat (v2 synthesis) — TESTS FIRST | Backend/Test | 10 min |
| 9B | Enhanced chat (v2 synthesis) — IMPLEMENTATION | Backend | 15 min |
| 10 | Enhanced chat UI | Frontend | 15 min |
| 11 | Integration tests + Docker build verification | Test/DevOps | 15 min |

---

## Task 1: Frontend Scaffolding + Routing

**Files:**
- Modify: `frontend/package.json` — add dependencies
- Create: `frontend/src/router.tsx` — React Router config
- Create: `frontend/src/layouts/MainLayout.tsx` — app shell with sidebar nav
- Create: `frontend/src/components/Sidebar.tsx` — replace existing sidebar (new nav structure)
- Create: `frontend/src/components/GlobalSearchBar.tsx` — "Ask anything..." bar
- Create: `frontend/src/pages/DashboardPage.tsx` — placeholder
- Create: `frontend/src/pages/SearchPage.tsx` — placeholder
- Create: `frontend/src/pages/AnalyticsPage.tsx` — placeholder
- Create: `frontend/src/pages/CompetitorsPage.tsx` — placeholder
- Create: `frontend/src/pages/GraphPage.tsx` — placeholder
- Create: `frontend/src/pages/FilingsPage.tsx` — placeholder
- Create: `frontend/src/pages/ContractsPage.tsx` — placeholder
- Create: `frontend/src/pages/MyDealsPage.tsx` — placeholder
- Create: `frontend/src/pages/ChatPage.tsx` — move existing chat here
- Create: `frontend/src/pages/LoginPage.tsx` — placeholder
- Create: `frontend/src/contexts/AuthContext.tsx` — auth state management
- Create: `frontend/src/lib/api.ts` — typed API client with auth headers
- Modify: `frontend/src/App.tsx` — replace with router mount
- Modify: `frontend/src/main.tsx` — wrap with providers

**Step 1: Install new dependencies**

```bash
cd frontend
npm install react-router-dom@6 recharts @tanstack/react-table axios
npm install -D @types/recharts
```

**Step 2: Create the API client**

Create `frontend/src/lib/api.ts`:
```typescript
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
```

**Step 3: Create AuthContext**

Create `frontend/src/contexts/AuthContext.tsx`:
```typescript
import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import api, { User } from '../lib/api';

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem('bd_user');
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem('bd_token')
  );
  const [isLoading, setIsLoading] = useState(false);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const res = await api.post('/auth/login', { email, password });
      const { access_token, user: userData } = res.data;
      localStorage.setItem('bd_token', access_token);
      localStorage.setItem('bd_user', JSON.stringify(userData));
      setToken(access_token);
      setUser(userData);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('bd_token');
    localStorage.removeItem('bd_user');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

**Step 4: Create MainLayout with sidebar navigation**

Create `frontend/src/layouts/MainLayout.tsx`:
```typescript
import { useState } from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Search, BarChart3, Building2,
  Network, FileText, ScrollText, Star, MessageSquare,
  Menu, X, Bell, LogOut, ChevronLeft
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/search', icon: Search, label: 'Search' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/competitors', icon: Building2, label: 'Competitors' },
  { to: '/graph', icon: Network, label: 'Network' },
  { to: '/filings', icon: FileText, label: 'Filings' },
  { to: '/contracts', icon: ScrollText, label: 'Contracts' },
  { to: '/my-deals', icon: Star, label: 'My Deals' },
  { to: '/chat', icon: MessageSquare, label: 'Ask' },
];

export default function MainLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [askQuery, setAskQuery] = useState('');

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (askQuery.trim()) {
      navigate(`/chat?q=${encodeURIComponent(askQuery.trim())}`);
      setAskQuery('');
    }
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 bg-black/50 z-30" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed lg:relative inset-y-0 left-0 z-40
        flex flex-col bg-slate-900 border-r border-slate-800
        transition-all duration-200
        ${sidebarCollapsed ? 'w-16' : 'w-56'}
        ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
      `}>
        {/* Logo */}
        <div className="flex items-center h-14 px-4 border-b border-slate-800">
          {!sidebarCollapsed && (
            <span className="font-semibold text-sm text-slate-200 truncate">BD Intelligence</span>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="ml-auto p-1 rounded hover:bg-slate-800 hidden lg:block"
          >
            <ChevronLeft className={`w-4 h-4 text-slate-400 transition-transform ${sidebarCollapsed ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `
                flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm
                transition-colors
                ${isActive
                  ? 'bg-blue-600/20 text-blue-400'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}
              `}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {!sidebarCollapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User */}
        <div className="p-3 border-t border-slate-800">
          {!sidebarCollapsed && user && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500 truncate">{user.name || user.email}</span>
              <button onClick={logout} className="p-1 rounded hover:bg-slate-800">
                <LogOut className="w-4 h-4 text-slate-500" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 h-14 px-4 border-b border-slate-800 bg-slate-900/50">
          <button onClick={() => setMobileOpen(true)} className="lg:hidden p-1">
            <Menu className="w-5 h-5 text-slate-400" />
          </button>

          {/* Global search */}
          <form onSubmit={handleAsk} className="flex-1 max-w-2xl">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                value={askQuery}
                onChange={(e) => setAskQuery(e.target.value)}
                placeholder="Ask anything..."
                className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>
          </form>

          {/* Notifications */}
          <button className="relative p-2 rounded-lg hover:bg-slate-800">
            <Bell className="w-5 h-5 text-slate-400" />
          </button>

          {/* User avatar */}
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-medium">
            {user?.name?.[0] || user?.email?.[0] || '?'}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

**Step 5: Create router**

Create `frontend/src/router.tsx`:
```typescript
import { createBrowserRouter, Navigate } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import SearchPage from './pages/SearchPage';
import AnalyticsPage from './pages/AnalyticsPage';
import CompetitorsPage from './pages/CompetitorsPage';
import GraphPage from './pages/GraphPage';
import FilingsPage from './pages/FilingsPage';
import ContractsPage from './pages/ContractsPage';
import MyDealsPage from './pages/MyDealsPage';
import ChatPage from './pages/ChatPage';
import CompanyProfilePage from './pages/CompanyProfilePage';
import DrugProfilePage from './pages/DrugProfilePage';

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'analytics', element: <AnalyticsPage /> },
      { path: 'competitors', element: <CompetitorsPage /> },
      { path: 'graph', element: <GraphPage /> },
      { path: 'filings', element: <FilingsPage /> },
      { path: 'contracts', element: <ContractsPage /> },
      { path: 'my-deals', element: <MyDealsPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'company/:companyId', element: <CompanyProfilePage /> },
      { path: 'drug/:drugId', element: <DrugProfilePage /> },
    ],
  },
]);
```

**Step 6: Create placeholder pages**

Create each page file as a simple placeholder. Example for `frontend/src/pages/DashboardPage.tsx`:
```typescript
export default function DashboardPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-100">Dashboard</h1>
      <p className="text-slate-400 mt-2">Executive overview — coming soon</p>
    </div>
  );
}
```

Create identical placeholders (with appropriate title/description) for:
- `SearchPage.tsx`
- `AnalyticsPage.tsx`
- `CompetitorsPage.tsx`
- `GraphPage.tsx`
- `FilingsPage.tsx`
- `ContractsPage.tsx`
- `MyDealsPage.tsx`
- `ChatPage.tsx`
- `CompanyProfilePage.tsx`
- `DrugProfilePage.tsx`
- `LoginPage.tsx`

**Step 7: Update App.tsx and main.tsx**

Replace `frontend/src/App.tsx`:
```typescript
import { RouterProvider } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { router } from './router';

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
```

Update `frontend/src/main.tsx`:
```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

**Step 8: Verify build**

```bash
cd frontend && npm run build
```

Expected: Build succeeds with no TypeScript errors.

**Step 9: Commit**

```bash
git add -A
git commit -m "feat: frontend scaffolding with React Router, sidebar nav, auth context, API client"
```

---

## Task 2A: Authentication Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_auth.py` — unit tests for auth service
- Create: `unified_api/tests/integration/test_auth_endpoints.py` — API endpoint tests

**Step 1: Write auth service unit tests**

Create `unified_api/tests/unit/test_auth.py`:
```python
"""
TDD: Auth service tests — write these FIRST, then implement.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_hash_password_returns_string(self):
        from unified_api.services.auth import hash_password
        result = hash_password("testpassword123")
        assert isinstance(result, str)
        assert len(result) > 20  # bcrypt hashes are ~60 chars

    def test_hash_password_not_plaintext(self):
        from unified_api.services.auth import hash_password
        result = hash_password("testpassword123")
        assert result != "testpassword123"

    def test_verify_password_correct(self):
        from unified_api.services.auth import hash_password, verify_password
        hashed = hash_password("testpassword123")
        assert verify_password("testpassword123", hashed) is True

    def test_verify_password_incorrect(self):
        from unified_api.services.auth import hash_password, verify_password
        hashed = hash_password("testpassword123")
        assert verify_password("wrongpassword", hashed) is False

    def test_different_passwords_different_hashes(self):
        from unified_api.services.auth import hash_password
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2


class TestJWTTokens:
    """Test JWT token creation and decoding."""

    def test_create_access_token_returns_string(self):
        from unified_api.services.auth import create_access_token
        token = create_access_token(user_id=1, email="test@test.com", role="analyst")
        assert isinstance(token, str)
        assert len(token) > 50  # JWT tokens are long

    def test_decode_valid_token(self):
        from unified_api.services.auth import create_access_token, decode_token
        token = create_access_token(user_id=42, email="jvo@beigene.com", role="ceo")
        data = decode_token(token)
        assert data is not None
        assert data.user_id == 42
        assert data.email == "jvo@beigene.com"
        assert data.role == "ceo"

    def test_decode_invalid_token_returns_none(self):
        from unified_api.services.auth import decode_token
        data = decode_token("this.is.not.a.valid.token")
        assert data is None

    def test_decode_expired_token_returns_none(self):
        from unified_api.services.auth import decode_token, SECRET_KEY, ALGORITHM
        from jose import jwt
        from datetime import datetime, timedelta, timezone
        expired_payload = {
            "sub": "1",
            "email": "test@test.com",
            "role": "analyst",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        data = decode_token(expired_token)
        assert data is None

    def test_token_contains_correct_claims(self):
        from unified_api.services.auth import create_access_token, SECRET_KEY, ALGORITHM
        from jose import jwt
        token = create_access_token(user_id=5, email="analyst@company.com", role="analyst")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "5"
        assert payload["email"] == "analyst@company.com"
        assert payload["role"] == "analyst"
        assert "exp" in payload
```

**Step 2: Write auth endpoint integration tests**

Create `unified_api/tests/integration/test_auth_endpoints.py`:
```python
"""
TDD: Auth endpoint tests — write these FIRST, then implement.
Tests use the FastAPI TestClient against the real app.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestRegisterEndpoint:
    """Test POST /api/auth/register"""

    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "testuser_tdd@test.com",
            "password": "SecurePass123!",
            "name": "TDD Test User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "testuser_tdd@test.com"
        assert data["user"]["name"] == "TDD Test User"
        assert data["user"]["role"] == "analyst"  # default role

    def test_register_duplicate_email_fails(self, client):
        # Register first time
        client.post("/api/auth/register", json={
            "email": "duplicate_tdd@test.com",
            "password": "Pass123!",
            "name": "First User",
        })
        # Try duplicate
        resp = client.post("/api/auth/register", json={
            "email": "duplicate_tdd@test.com",
            "password": "Pass456!",
            "name": "Second User",
        })
        assert resp.status_code == 400

    def test_register_missing_fields_fails(self, client):
        resp = client.post("/api/auth/register", json={"email": "incomplete@test.com"})
        assert resp.status_code == 422  # Pydantic validation error


class TestLoginEndpoint:
    """Test POST /api/auth/login"""

    def test_login_success(self, client):
        # Register first
        client.post("/api/auth/register", json={
            "email": "logintest_tdd@test.com",
            "password": "MyPass123!",
            "name": "Login Test",
        })
        # Login
        resp = client.post("/api/auth/login", json={
            "email": "logintest_tdd@test.com",
            "password": "MyPass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "logintest_tdd@test.com"

    def test_login_wrong_password_fails(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "logintest_tdd@test.com",
            "password": "WrongPass!",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user_fails(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody_tdd@test.com",
            "password": "whatever",
        })
        assert resp.status_code == 401


class TestMeEndpoint:
    """Test GET /api/auth/me"""

    def test_me_with_valid_token(self, client):
        # Register and get token
        reg = client.post("/api/auth/register", json={
            "email": "metest_tdd@test.com",
            "password": "Pass123!",
            "name": "Me Test",
        })
        token = reg.json()["access_token"]

        # Call /me
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "metest_tdd@test.com"

    def test_me_without_token_fails(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_fails(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401
```

**Step 3: Run tests — verify they FAIL**

```bash
cd /Users/kayleighbot/Projects/cortellis
python -m pytest unified_api/tests/unit/test_auth.py -v
python -m pytest unified_api/tests/integration/test_auth_endpoints.py -v
```

Expected: All tests FAIL (ImportError — modules don't exist yet).

**Step 4: Commit failing tests**

```bash
git add unified_api/tests/unit/test_auth.py unified_api/tests/integration/test_auth_endpoints.py
git commit -m "test: auth tests (TDD red phase — all failing)"
```

---

## Task 2B: Authentication Backend — IMPLEMENTATION

Now implement the minimum code to make all Task 2A tests pass.

## Task 2: Authentication Backend

**Files:**
- Create: `unified_api/routers/auth.py` — login/register/me endpoints
- Create: `unified_api/services/auth.py` — JWT + password hashing
- Modify: `unified_api/main.py` — register auth router
- Modify: `unified_api/requirements.txt` — add python-jose, passlib, bcrypt

**Step 1: Add dependencies**

Add to `unified_api/requirements.txt`:
```
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.0.1
```

**Step 2: Create auth service**

Create `unified_api/services/auth.py`:
```python
"""
Authentication service - JWT tokens and password hashing.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
import os

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "bd-intelligence-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenData(BaseModel):
    user_id: int
    email: str
    role: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenData(
            user_id=int(payload["sub"]),
            email=payload["email"],
            role=payload.get("role", "analyst"),
        )
    except JWTError:
        return None
```

**Step 3: Create auth router**

Create `unified_api/routers/auth.py`:
```python
"""
Authentication endpoints: register, login, get current user.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import (
    hash_password, verify_password, create_access_token, decode_token, TokenData
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "analyst"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def get_current_user(authorization: Optional[str] = Header(None)) -> TokenData:
    """Extract and validate JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    data = decode_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return data


def _ensure_users_table(session):
    """Create users table if it doesn't exist."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'analyst',
            preferences JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP
        )
    """))
    session.commit()


@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest):
    """Register a new user account."""
    with get_cortellis_session() as session:
        _ensure_users_table(session)

        # Check if email exists
        existing = session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": req.email}
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        # Create user
        result = session.execute(
            text("""
                INSERT INTO users (email, password_hash, name, role)
                VALUES (:email, :password_hash, :name, :role)
                RETURNING id
            """),
            {
                "email": req.email,
                "password_hash": hash_password(req.password),
                "name": req.name,
                "role": req.role,
            }
        )
        user_id = result.fetchone()[0]
        session.commit()

    token = create_access_token(user_id, req.email, req.role)
    return LoginResponse(
        access_token=token,
        user=UserResponse(id=user_id, email=req.email, name=req.name, role=req.role),
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Login with email and password."""
    with get_cortellis_session() as session:
        _ensure_users_table(session)

        row = session.execute(
            text("SELECT id, email, password_hash, name, role FROM users WHERE email = :email"),
            {"email": req.email}
        ).fetchone()

        if not row or not verify_password(req.password, row.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Update last_login
        session.execute(
            text("UPDATE users SET last_login = NOW() WHERE id = :id"),
            {"id": row.id}
        )
        session.commit()

    token = create_access_token(row.id, row.email, row.role)
    return LoginResponse(
        access_token=token,
        user=UserResponse(id=row.id, email=row.email, name=row.name, role=row.role),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """Get current authenticated user."""
    with get_cortellis_session() as session:
        row = session.execute(
            text("SELECT id, email, name, role FROM users WHERE id = :id"),
            {"id": current_user.user_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(id=row.id, email=row.email, name=row.name, role=row.role)
```

**Step 4: Register auth router in main.py**

Add to imports in `unified_api/main.py`:
```python
from unified_api.routers import health, chat, search, entities, graph, analytics, export, xref, edgar, watchlist, contracts, auth
```

Add router registration (after the existing router includes):
```python
app.include_router(auth.router, prefix="/api")
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: JWT authentication backend (register, login, me)"
```

---

## Task 3: Authentication Frontend (Login Page)

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx` — login/register form
- Modify: `frontend/src/router.tsx` — add auth guard

**Step 1: Build LoginPage**

Replace `frontend/src/pages/LoginPage.tsx`:
```typescript
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { BarChart3 } from 'lucide-react';

export default function LoginPage() {
  const { login, isLoading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await login(email, password);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <BarChart3 className="w-12 h-12 text-blue-500 mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-slate-100">BD Intelligence</h1>
          <p className="text-slate-500 text-sm mt-1">Pharmaceutical Deal Intelligence Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-slate-900 rounded-xl p-6 border border-slate-800">
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          <div className="mb-4">
            <label className="block text-sm text-slate-400 mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="mb-6">
            <label className="block text-sm text-slate-400 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
```

**Step 2: Add auth guard to router**

Update `frontend/src/router.tsx` — wrap MainLayout children with auth check:

Add to `frontend/src/layouts/MainLayout.tsx` at the top of the component:
```typescript
const { user } = useAuth();
if (!user) {
  return <Navigate to="/login" replace />;
}
```

Add import: `import { Navigate } from 'react-router-dom';`

**Step 3: Verify build**

```bash
cd frontend && npm run build
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: login page and auth guard"
```

---

## Task 4A: Executive Dashboard Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/integration/test_dashboard.py`

**Step 1: Write dashboard endpoint tests**

Create `unified_api/tests/integration/test_dashboard.py`:
```python
"""
TDD: Dashboard endpoint tests — write these FIRST, then implement.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestExecutiveDashboard:
    """Test GET /api/dashboard/executive"""

    def test_dashboard_returns_200(self, client):
        resp = client.get("/api/dashboard/executive")
        assert resp.status_code == 200

    def test_dashboard_has_market_pulse(self, client):
        data = client.get("/api/dashboard/executive").json()
        assert "market_pulse" in data
        pulse = data["market_pulse"]
        assert "deal_count_30d" in pulse
        assert "deal_count_prev_30d" in pulse
        assert "avg_value_30d" in pulse
        assert "top_therapy_areas" in pulse
        assert "monthly_trend" in pulse

    def test_dashboard_deal_counts_are_integers(self, client):
        pulse = client.get("/api/dashboard/executive").json()["market_pulse"]
        assert isinstance(pulse["deal_count_30d"], int)
        assert isinstance(pulse["deal_count_prev_30d"], int)
        assert pulse["deal_count_30d"] >= 0

    def test_dashboard_has_notable_deals(self, client):
        data = client.get("/api/dashboard/executive").json()
        assert "notable_deals" in data
        assert isinstance(data["notable_deals"], list)

    def test_notable_deals_have_required_fields(self, client):
        deals = client.get("/api/dashboard/executive").json()["notable_deals"]
        if len(deals) > 0:
            deal = deals[0]
            assert "id" in deal
            assert "title" in deal
            assert "date_start" in deal
            # total_value can be null

    def test_monthly_trend_ordered_chronologically(self, client):
        trend = client.get("/api/dashboard/executive").json()["market_pulse"]["monthly_trend"]
        if len(trend) > 1:
            months = [t["month"] for t in trend]
            assert months == sorted(months)

    def test_top_therapy_areas_limited(self, client):
        areas = client.get("/api/dashboard/executive").json()["market_pulse"]["top_therapy_areas"]
        assert len(areas) <= 5

    def test_top_therapy_areas_sorted_by_count(self, client):
        areas = client.get("/api/dashboard/executive").json()["market_pulse"]["top_therapy_areas"]
        if len(areas) > 1:
            counts = [a["count"] for a in areas]
            assert counts == sorted(counts, reverse=True)

    def test_dashboard_is_cached_on_second_call(self, client):
        """Second call should be faster (cached). Just verify it returns same data."""
        resp1 = client.get("/api/dashboard/executive").json()
        resp2 = client.get("/api/dashboard/executive").json()
        assert resp1["market_pulse"]["deal_count_30d"] == resp2["market_pulse"]["deal_count_30d"]
```

**Step 2: Run tests — verify they FAIL**

```bash
python -m pytest unified_api/tests/integration/test_dashboard.py -v
```

Expected: FAIL (404 — endpoint doesn't exist).

**Step 3: Commit failing tests**

```bash
git add unified_api/tests/integration/test_dashboard.py
git commit -m "test: dashboard tests (TDD red phase — all failing)"
```

---

## Task 4B: Executive Dashboard Backend — IMPLEMENTATION

Now implement the minimum code to make all Task 4A tests pass.

## Task 4: Executive Dashboard Backend

**Files:**
- Create: `unified_api/routers/dashboard.py` — aggregated dashboard endpoint
- Modify: `unified_api/main.py` — register dashboard router

**Step 1: Create dashboard router**

Create `unified_api/routers/dashboard.py`:
```python
"""
Executive dashboard endpoint.
Returns pre-aggregated data for the landing page.
"""
from fastapi import APIRouter
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.cache import cache_get, cache_set, cache_key

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/executive")
async def get_executive_dashboard():
    """
    Pre-aggregated executive dashboard data.
    Cached for 30 minutes.
    """
    key = cache_key("dashboard_executive")
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        # Deal count last 30 days vs previous 30 days
        pulse = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE date_start >= CURRENT_DATE - INTERVAL '30 days') as count_30d,
                COUNT(*) FILTER (WHERE date_start >= CURRENT_DATE - INTERVAL '60 days'
                                  AND date_start < CURRENT_DATE - INTERVAL '30 days') as count_prev_30d
            FROM deals
            WHERE date_start IS NOT NULL
        """)).fetchone()

        # Average deal value last 30 days (disclosed only)
        avg_val = session.execute(text("""
            SELECT AVG(f.total_projected_current_amount) as avg_value,
                   COUNT(*) as disclosed_count
            FROM deals d
            JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '30 days'
              AND f.total_projected_current_amount IS NOT NULL
        """)).fetchone()

        # Top therapy areas (last 90 days)
        therapy_areas = session.execute(text("""
            SELECT ta.name, COUNT(*) as count
            FROM deals d
            JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '90 days'
              AND ta.name IS NOT NULL
            GROUP BY ta.name
            ORDER BY count DESC
            LIMIT 5
        """)).fetchall()

        # Notable deals (highest value, last 60 days)
        notable = session.execute(text("""
            SELECT
                d.id, d.title, d.agreement_type, d.status,
                d.date_start::text,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '60 days'
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT 10
        """)).fetchall()

        # Deal count by month (last 12 months) for sparkline
        monthly_trend = session.execute(text("""
            SELECT
                DATE_TRUNC('month', date_start)::date::text as month,
                COUNT(*) as count
            FROM deals
            WHERE date_start >= CURRENT_DATE - INTERVAL '12 months'
              AND date_start IS NOT NULL
            GROUP BY DATE_TRUNC('month', date_start)
            ORDER BY month
        """)).fetchall()

    result = {
        "market_pulse": {
            "deal_count_30d": pulse.count_30d if pulse else 0,
            "deal_count_prev_30d": pulse.count_prev_30d if pulse else 0,
            "avg_value_30d": float(avg_val.avg_value) if avg_val and avg_val.avg_value else None,
            "disclosed_count_30d": avg_val.disclosed_count if avg_val else 0,
            "top_therapy_areas": [{"name": r.name, "count": r.count} for r in therapy_areas],
            "monthly_trend": [{"month": r.month, "count": r.count} for r in monthly_trend],
        },
        "notable_deals": [
            {
                "id": r.id,
                "title": r.title,
                "agreement_type": r.agreement_type,
                "status": r.status,
                "date_start": r.date_start,
                "total_value": float(r.total_value) if r.total_value else None,
                "principal_company": r.principal,
                "partner_company": r.partner,
            }
            for r in notable
        ],
    }

    cache_set(key, result, ttl=1800)  # 30 min
    return result
```

**Step 2: Register in main.py**

Add `dashboard` to imports and `app.include_router(dashboard.router, prefix="/api")`.

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: executive dashboard aggregation endpoint"
```

---

## Task 5: Executive Dashboard Frontend

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx` — full dashboard implementation

**Step 1: Build the dashboard page**

Replace `frontend/src/pages/DashboardPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Minus, ArrowRight, DollarSign, Activity, Layers } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import api, { DealSummary } from '../lib/api';

interface DashboardData {
  market_pulse: {
    deal_count_30d: number;
    deal_count_prev_30d: number;
    avg_value_30d: number | null;
    disclosed_count_30d: number;
    top_therapy_areas: Array<{ name: string; count: number }>;
    monthly_trend: Array<{ month: string; count: number }>;
  };
  notable_deals: Array<DealSummary & { agreement_type?: string }>;
}

function StatCard({ label, value, subtext, trend, icon: Icon }: {
  label: string; value: string; subtext?: string;
  trend?: 'up' | 'down' | 'flat';
  icon: any;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-slate-500">{label}</span>
        <Icon className="w-5 h-5 text-slate-600" />
      </div>
      <div className="text-2xl font-bold text-slate-100">{value}</div>
      {subtext && (
        <div className="flex items-center gap-1 mt-1.5">
          {trend === 'up' && <TrendingUp className="w-3.5 h-3.5 text-green-400" />}
          {trend === 'down' && <TrendingDown className="w-3.5 h-3.5 text-red-400" />}
          {trend === 'flat' && <Minus className="w-3.5 h-3.5 text-slate-500" />}
          <span className={`text-xs ${
            trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : 'text-slate-500'
          }`}>{subtext}</span>
        </div>
      )}
    </div>
  );
}

function formatValue(v: number | null): string {
  if (v === null) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/dashboard/executive')
      .then(res => setData(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 animate-pulse">
        <div className="h-8 w-48 bg-slate-800 rounded mb-6" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map(i => <div key={i} className="h-28 bg-slate-800 rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-6 text-slate-400">Failed to load dashboard</div>;

  const { market_pulse: pulse, notable_deals } = data;
  const dealChange = pulse.deal_count_prev_30d > 0
    ? ((pulse.deal_count_30d - pulse.deal_count_prev_30d) / pulse.deal_count_prev_30d * 100)
    : 0;
  const dealTrend = dealChange > 5 ? 'up' : dealChange < -5 ? 'down' : 'flat';

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Market Pulse</h1>
        <p className="text-sm text-slate-500 mt-1">Pharmaceutical deal activity overview</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatCard
          label="Deals (30d)"
          value={pulse.deal_count_30d.toLocaleString()}
          subtext={`${dealChange >= 0 ? '+' : ''}${dealChange.toFixed(0)}% vs prior 30d`}
          trend={dealTrend}
          icon={Activity}
        />
        <StatCard
          label="Avg Deal Value (30d)"
          value={formatValue(pulse.avg_value_30d)}
          subtext={`${pulse.disclosed_count_30d} disclosed deals`}
          icon={DollarSign}
        />
        <StatCard
          label="Top Therapy Area"
          value={pulse.top_therapy_areas[0]?.name || 'N/A'}
          subtext={`${pulse.top_therapy_areas[0]?.count || 0} deals (90d)`}
          icon={Layers}
        />
      </div>

      {/* Deal Volume Trend */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
        <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Volume (12 months)</h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={pulse.monthly_trend}>
            <XAxis
              dataKey="month"
              tickFormatter={(v) => new Date(v).toLocaleDateString('en', { month: 'short' })}
              stroke="#475569"
              fontSize={12}
            />
            <YAxis stroke="#475569" fontSize={12} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
              labelFormatter={(v) => new Date(v).toLocaleDateString('en', { month: 'long', year: 'numeric' })}
            />
            <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Notable Deals */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-slate-400">Notable Deals (60d)</h2>
            <Link to="/search" className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
              View all <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="pb-2 pr-4">Deal</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Value</th>
                  <th className="pb-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {notable_deals.map(deal => (
                  <tr key={deal.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="py-2.5 pr-4">
                      <div className="text-slate-200 font-medium truncate max-w-xs">{deal.title}</div>
                      <div className="text-xs text-slate-500">
                        {deal.principal_company} → {deal.partner_company}
                      </div>
                    </td>
                    <td className="py-2.5 pr-4 text-slate-400 text-xs">{deal.agreement_type || deal.deal_type || '—'}</td>
                    <td className="py-2.5 pr-4 text-slate-300">
                      {deal.total_value ? formatValue(deal.total_value) : '—'}
                    </td>
                    <td className="py-2.5 text-slate-500 text-xs">{deal.date_start || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Top Therapy Areas */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4">Active Therapy Areas (90d)</h2>
          <div className="space-y-3">
            {pulse.top_therapy_areas.map((ta, i) => (
              <div key={ta.name}>
                <div className="flex items-center justify-between text-sm mb-1">
                  <span className="text-slate-300">{ta.name}</span>
                  <span className="text-slate-500">{ta.count}</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${(ta.count / (pulse.top_therapy_areas[0]?.count || 1)) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify build**

```bash
cd frontend && npm run build
```

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: executive dashboard with KPIs, trend chart, notable deals"
```

---

## Task 6: Advanced Search Page

**Files:**
- Modify: `frontend/src/pages/SearchPage.tsx` — full search UI with filters

**Step 1: Build the search page**

Replace `frontend/src/pages/SearchPage.tsx`:
```typescript
import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Filter, Download, Star, ChevronDown, ChevronUp, X } from 'lucide-react';
import api, { SearchFilters, SearchResponse, FilterOptions, DealSummary } from '../lib/api';

function FilterSelect({ label, options, value, onChange, multi = false }: {
  label: string;
  options: string[];
  value: string | string[];
  onChange: (v: any) => void;
  multi?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = multi ? (value as string[]) : (value ? [value as string] : []);

  const toggle = (opt: string) => {
    if (multi) {
      const cur = value as string[];
      onChange(cur.includes(opt) ? cur.filter(v => v !== opt) : [...cur, opt]);
    } else {
      onChange(opt === value ? '' : opt);
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs transition-colors ${
          selected.length > 0
            ? 'border-blue-500/50 bg-blue-500/10 text-blue-400'
            : 'border-slate-700 bg-slate-800 text-slate-400 hover:border-slate-600'
        }`}
      >
        {label}{selected.length > 0 && ` (${selected.length})`}
        <ChevronDown className="w-3 h-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute z-20 mt-1 w-64 max-h-60 overflow-y-auto bg-slate-800 border border-slate-700 rounded-lg shadow-xl">
            {options.map(opt => (
              <button
                key={opt}
                onClick={() => toggle(opt)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-700 ${
                  selected.includes(opt) ? 'text-blue-400 bg-blue-500/10' : 'text-slate-300'
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function SearchPage() {
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [disclosedOnly, setDisclosedOnly] = useState(false);

  useEffect(() => {
    api.get('/search/filters').then(res => setFilterOptions(res.data)).catch(console.error);
  }, []);

  const search = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await api.post(`/search/deals?page=${p}&page_size=25`, {
        ...filters,
        disclosed_only: disclosedOnly,
      });
      setResults(res.data);
      setPage(p);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [filters, disclosedOnly]);

  useEffect(() => {
    search(1);
  }, []);

  const clearFilters = () => {
    setFilters({});
    setDisclosedOnly(false);
  };

  const hasFilters = Object.values(filters).some(v =>
    Array.isArray(v) ? v.length > 0 : v !== undefined && v !== '' && v !== null
  ) || disclosedOnly;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Deal Search</h1>
          <p className="text-sm text-slate-500 mt-1">
            {results ? `${results.total.toLocaleString()} deals` : 'Search across 145K+ pharmaceutical deals'}
          </p>
        </div>
        <button
          onClick={() => search(1)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium transition-colors"
        >
          Search
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <Filter className="w-4 h-4 text-slate-500" />
        {filterOptions && (
          <>
            <FilterSelect
              label="Therapy Area"
              options={filterOptions.therapy_areas}
              value={filters.therapy_area || ''}
              onChange={(v: string) => setFilters(f => ({ ...f, therapy_area: v || undefined }))}
            />
            <FilterSelect
              label="Agreement Type"
              options={filterOptions.deal_types}
              value={filters.deal_type || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, deal_type: v.length ? v : undefined }))}
              multi
            />
            <FilterSelect
              label="Phase"
              options={filterOptions.phases}
              value={filters.phase || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, phase: v.length ? v : undefined }))}
              multi
            />
            <FilterSelect
              label="Status"
              options={filterOptions.statuses}
              value={filters.status || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, status: v.length ? v : undefined }))}
              multi
            />
          </>
        )}

        {/* Disclosed only toggle */}
        <button
          onClick={() => setDisclosedOnly(!disclosedOnly)}
          className={`px-3 py-1.5 rounded-lg border text-xs transition-colors ${
            disclosedOnly
              ? 'border-green-500/50 bg-green-500/10 text-green-400'
              : 'border-slate-700 bg-slate-800 text-slate-400 hover:border-slate-600'
          }`}
        >
          Disclosed Only
        </button>

        {hasFilters && (
          <button onClick={clearFilters} className="px-2 py-1.5 text-xs text-slate-500 hover:text-slate-300">
            <X className="w-3 h-3 inline mr-1" /> Clear
          </button>
        )}
      </div>

      {/* Company search input */}
      <div className="flex gap-2 mb-6">
        <input
          type="text"
          placeholder="Filter by company name..."
          value={filters.company || ''}
          onChange={(e) => setFilters(f => ({ ...f, company: e.target.value || undefined }))}
          onKeyDown={(e) => e.key === 'Enter' && search(1)}
          className="flex-1 max-w-sm px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Results table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 bg-slate-900/50">
                <th className="px-4 py-3 font-medium">Deal</th>
                <th className="px-4 py-3 font-medium">Principal</th>
                <th className="px-4 py-3 font-medium">Partner</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Value</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-4 py-3"><div className="h-4 bg-slate-800 rounded animate-pulse" /></td>
                  </tr>
                ))
              ) : results?.results.map(deal => (
                <tr key={deal.id} className="border-t border-slate-800/50 hover:bg-slate-800/30 cursor-pointer">
                  <td className="px-4 py-3">
                    <span className="text-slate-200 hover:text-blue-400 font-medium">
                      {deal.title}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {deal.principal_company ? (
                      <span className="hover:text-blue-400 cursor-pointer">{deal.principal_company}</span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {deal.partner_company ? (
                      <span className="hover:text-blue-400 cursor-pointer">{deal.partner_company}</span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{deal.deal_type || '—'}</td>
                  <td className="px-4 py-3 text-slate-300">{formatValue(deal.total_value)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      deal.status === 'Active' ? 'bg-green-500/10 text-green-400' :
                      deal.status === 'Completed' ? 'bg-blue-500/10 text-blue-400' :
                      'bg-slate-700 text-slate-400'
                    }`}>{deal.status || '—'}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{deal.date_start || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {results && results.total > 25 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800">
            <span className="text-xs text-slate-500">
              Page {page} of {Math.ceil(results.total / 25)}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => search(page - 1)}
                disabled={page <= 1}
                className="px-3 py-1 text-xs bg-slate-800 rounded hover:bg-slate-700 disabled:opacity-50"
              >
                Previous
              </button>
              <button
                onClick={() => search(page + 1)}
                disabled={page >= Math.ceil(results.total / 25)}
                className="px-3 py-1 text-xs bg-slate-800 rounded hover:bg-slate-700 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: advanced search page with multi-criteria filters"
```

---

## Task 7: Company Profile Page

**Files:**
- Modify: `frontend/src/pages/CompanyProfilePage.tsx`

**Step 1: Build company profile page**

Replace `frontend/src/pages/CompanyProfilePage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Building2, TrendingUp, Users, Pill, FileText, ArrowLeft } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import api from '../lib/api';

const COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1'];

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function CompanyProfilePage() {
  const { companyId } = useParams();
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    api.get(`/company/${companyId}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false));
  }, [companyId]);

  if (loading) return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!profile) return null;

  const { company, deal_summary, deal_timeline, top_partners, therapeutic_focus, recent_deals, drugs, sec_filings } = profile;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Back link */}
      <Link to="/search" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to search
      </Link>

      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-blue-600/20 flex items-center justify-center">
          <Building2 className="w-6 h-6 text-blue-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{company.name}</h1>
          <div className="flex gap-3 mt-1 text-sm text-slate-500">
            {company.company_type && <span>{company.company_type}</span>}
            {company.ticker && <span>({company.ticker})</span>}
          </div>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        {[
          { label: 'Total Deals', value: deal_summary.total_deals?.toString() || '0' },
          { label: 'As Principal', value: deal_summary.as_principal?.toString() || '0' },
          { label: 'As Partner', value: deal_summary.as_partner?.toString() || '0' },
          { label: 'Avg Deal Value', value: formatValue(deal_summary.avg_deal_value) },
          { label: 'Total Value', value: formatValue(deal_summary.total_deal_value) },
        ].map(kpi => (
          <div key={kpi.label} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
            <div className="text-xs text-slate-500">{kpi.label}</div>
            <div className="text-lg font-bold text-slate-200 mt-1">{kpi.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Deal timeline */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" /> Deal Activity Over Time
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={deal_timeline}>
              <XAxis dataKey="year" stroke="#475569" fontSize={12} />
              <YAxis stroke="#475569" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Therapeutic focus */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4">Therapeutic Focus</h2>
          {therapeutic_focus?.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={therapeutic_focus.slice(0, 8)}
                  dataKey="count"
                  nameKey="indication"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={({ indication, percent }) => `${indication?.slice(0, 15)} (${(percent * 100).toFixed(0)}%)`}
                  labelLine={false}
                  fontSize={10}
                >
                  {therapeutic_focus.slice(0, 8).map((_: any, i: number) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-slate-500 text-sm">No indication data available</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top partners */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Users className="w-4 h-4" /> Top Partners
          </h2>
          <div className="space-y-2">
            {top_partners?.slice(0, 10).map((p: any) => (
              <div key={p.name} className="flex items-center justify-between text-sm">
                <span className="text-slate-300 truncate">{p.name}</span>
                <span className="text-slate-500 text-xs">{p.deal_count} deals</span>
              </div>
            ))}
          </div>
        </div>

        {/* Drugs / Assets */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Pill className="w-4 h-4" /> Drug Portfolio
          </h2>
          <div className="space-y-2">
            {drugs?.slice(0, 10).map((d: any) => (
              <Link key={d.id} to={`/drug/${d.id}`} className="flex items-center justify-between text-sm hover:bg-slate-800 rounded px-2 py-1 -mx-2">
                <span className="text-slate-300 truncate">{d.name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">{d.phase}</span>
              </Link>
            ))}
          </div>
        </div>

        {/* SEC Filings */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <FileText className="w-4 h-4" /> SEC Filings
          </h2>
          {sec_filings?.length > 0 ? (
            <div className="space-y-2">
              {sec_filings.slice(0, 10).map((f: any) => (
                <div key={f.id} className="flex items-center justify-between text-sm">
                  <span className="text-slate-300">{f.doc_type}</span>
                  <span className="text-slate-500 text-xs">{f.filing_date}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No SEC filings linked</p>
          )}
        </div>
      </div>

      {/* Recent deals */}
      <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-medium text-slate-400 mb-4">Recent Deals</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="pb-2">Title</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {recent_deals?.map((d: any) => (
              <tr key={d.id} className="border-t border-slate-800/50">
                <td className="py-2 text-slate-200">{d.title}</td>
                <td className="py-2 text-slate-400 text-xs">{d.deal_type || d.agreement_type || '—'}</td>
                <td className="py-2 text-slate-300">{formatValue(d.total_value)}</td>
                <td className="py-2 text-slate-500 text-xs">{d.date_start || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: company profile page with charts, partners, drugs, filings"
```

---

## Task 8: Drug Profile Page

**Files:**
- Modify: `frontend/src/pages/DrugProfilePage.tsx`

**Step 1: Build drug profile page**

Replace `frontend/src/pages/DrugProfilePage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Pill, ArrowLeft, Building2, Globe, DollarSign } from 'lucide-react';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function DrugProfilePage() {
  const { drugId } = useParams();
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!drugId) return;
    api.get(`/drug/${drugId}/profile`)
      .then(res => setProfile(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [drugId]);

  if (loading) return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  if (!profile) return <div className="p-6 text-red-400">Drug not found</div>;

  const { drug, deal_history, territory_rights, financial_summary, related_companies } = profile;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <Link to="/search" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back
      </Link>

      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-purple-600/20 flex items-center justify-center">
          <Pill className="w-6 h-6 text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{drug.name}</h1>
          <div className="flex gap-3 mt-1">
            {drug.phase && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">{drug.phase}</span>
            )}
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total Deals</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{financial_summary?.deal_count || 0}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total Deal Value</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{formatValue(financial_summary?.total_value)}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Related Companies</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{related_companies?.length || 0}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Related companies */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Building2 className="w-4 h-4" /> Related Companies
          </h2>
          <div className="space-y-2">
            {related_companies?.map((c: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span className="text-slate-300 truncate">{c.name}</span>
                <span className="text-xs text-slate-500">{c.role}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Territory rights */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Globe className="w-4 h-4" /> Territory Rights
          </h2>
          {territory_rights?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-800">
                    <th className="pb-2">Territory</th>
                    <th className="pb-2">Rights Holder</th>
                    <th className="pb-2">Deal</th>
                  </tr>
                </thead>
                <tbody>
                  {territory_rights.map((t: any, i: number) => (
                    <tr key={i} className="border-t border-slate-800/50">
                      <td className="py-2 text-slate-300">{t.territory}</td>
                      <td className="py-2 text-slate-400">{t.holder}</td>
                      <td className="py-2 text-slate-500 text-xs">#{t.deal_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No territory data available</p>
          )}
        </div>
      </div>

      {/* Deal history */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
          <DollarSign className="w-4 h-4" /> Deal History
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="pb-2">Title</th>
              <th className="pb-2">Principal</th>
              <th className="pb-2">Partner</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {deal_history?.map((d: any) => (
              <tr key={d.id} className="border-t border-slate-800/50">
                <td className="py-2 text-slate-200">{d.title}</td>
                <td className="py-2 text-slate-400">{d.principal_company || '—'}</td>
                <td className="py-2 text-slate-400">{d.partner_company || '—'}</td>
                <td className="py-2 text-slate-300">{formatValue(d.total_value)}</td>
                <td className="py-2 text-slate-500 text-xs">{d.date_start || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: drug profile page with deal history, territory rights, related companies"
```

---

## Task 9A: Enhanced Chat (v2 Synthesis) — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_chat_v2.py` — unit tests for synthesis logic
- Create: `unified_api/tests/integration/test_chat_v2_endpoints.py` — API endpoint tests

**Step 1: Write synthesis unit tests**

Create `unified_api/tests/unit/test_chat_v2.py`:
```python
"""
TDD: Chat v2 synthesis tests — write these FIRST, then implement.
"""
import pytest


class TestFollowUpSuggestions:
    """Test contextual follow-up generation."""

    def test_company_query_gets_company_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What deals has Pfizer done?")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3
        assert all(isinstance(s, str) for s in suggestions)

    def test_oncology_query_gets_oncology_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Show me oncology deal trends")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3

    def test_modality_query_gets_modality_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("ADC deals in solid tumors")
        assert len(suggestions) > 0

    def test_valuation_query_gets_financial_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What are typical upfront values?")
        assert len(suggestions) > 0

    def test_generic_query_gets_default_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("hello world")
        assert len(suggestions) == 3  # always returns 3 defaults

    def test_followups_are_unique(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Pfizer oncology deals")
        assert len(suggestions) == len(set(suggestions))
```

**Step 2: Write chat v2 endpoint tests**

Create `unified_api/tests/integration/test_chat_v2_endpoints.py`:
```python
"""
TDD: Chat v2 endpoint tests — write these FIRST, then implement.
These require OpenAI API key to be set (skip if not available).
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


# Skip all tests if no OpenAI key
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping LLM-dependent tests"
)


class TestChatV2Endpoint:
    """Test POST /api/chat/v2"""

    def test_chat_v2_returns_200(self, client):
        resp = client.post("/api/chat/v2", json={"message": "How many deals are in the database?"})
        assert resp.status_code == 200

    def test_chat_v2_response_structure(self, client):
        data = client.post("/api/chat/v2", json={"message": "Show me the 5 largest deals"}).json()
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 10  # non-trivial answer
        assert "intent" in data
        assert "confidence" in data
        assert "follow_ups" in data
        assert "actions" in data

    def test_chat_v2_confidence_has_required_fields(self, client):
        data = client.post("/api/chat/v2", json={"message": "Count of oncology deals"}).json()
        conf = data["confidence"]
        assert "data_completeness" in conf
        assert "sample_size" in conf

    def test_chat_v2_follow_ups_are_strings(self, client):
        data = client.post("/api/chat/v2", json={"message": "Pfizer deal history"}).json()
        assert isinstance(data["follow_ups"], list)
        for f in data["follow_ups"]:
            assert isinstance(f, str)

    def test_chat_v2_actions_have_label_and_type(self, client):
        data = client.post("/api/chat/v2", json={"message": "Top acquirers"}).json()
        assert isinstance(data["actions"], list)
        for a in data["actions"]:
            assert "label" in a
            assert "type" in a

    def test_chat_v2_accepts_history(self, client):
        resp = client.post("/api/chat/v2", json={
            "message": "And what about 2023?",
            "history": [
                {"role": "user", "content": "How many deals in 2024?"},
                {"role": "assistant", "content": "There were approximately 5,000 deals in 2024."},
            ],
        })
        assert resp.status_code == 200

    def test_chat_v2_returns_sql_query_for_deal_search(self, client):
        data = client.post("/api/chat/v2", json={"message": "Show me 5 recent oncology deals"}).json()
        # For SQL-routed queries, sql_query should be present
        if data["intent"] in ["deal_search", "company_lookup", "valuation", "market_trends"]:
            assert data.get("sql_query") is not None
```

**Step 3: Run tests — verify they FAIL**

```bash
python -m pytest unified_api/tests/unit/test_chat_v2.py -v
python -m pytest unified_api/tests/integration/test_chat_v2_endpoints.py -v
```

Expected: Unit tests FAIL (ImportError — `_suggest_follow_ups` doesn't exist). Integration tests FAIL (404 — endpoint doesn't exist).

**Step 4: Commit failing tests**

```bash
git add unified_api/tests/unit/test_chat_v2.py unified_api/tests/integration/test_chat_v2_endpoints.py
git commit -m "test: chat v2 tests (TDD red phase — all failing)"
```

---

## Task 9B: Enhanced Chat (v2 Synthesis) — IMPLEMENTATION

Now implement the minimum code to make all Task 9A tests pass.

## Task 9: Enhanced Chat (v2 Synthesis) Backend

**Files:**
- Modify: `unified_api/routers/chat.py` — add `/api/chat/v2` endpoint
- Modify: `unified_api/services/llm.py` — add synthesis prompt

**Step 1: Add synthesis prompt to llm.py**

Add to `unified_api/services/llm.py` after the existing prompts:
```python
SYNTHESIS_PROMPT = """You are an expert pharmaceutical business development analyst providing intelligence to a biotech CEO.

Given the user's question and the data retrieved, provide a SYNTHESIZED response that includes:

1. **Direct Answer** - Lead with a clear, concise answer in plain language
2. **Supporting Data** - Key numbers, trends, or comparisons that back the answer
3. **Data Quality Note** - Sample size, disclosure rate, or any caveats
4. **Follow-up Suggestions** - 2-3 related questions the user might want to ask next

FORMAT RULES:
- Use markdown formatting (bold, tables, bullet points)
- Lead with the insight, not the methodology
- If data is limited (< 5 results or < 50% disclosed), say so explicitly
- Be specific with numbers — don't round unnecessarily
- When showing financial data, always note if values are in millions USD

User question: {question}

Query mode used: {mode}

Data retrieved ({count} records):
{results}

Provide your synthesized response:
"""
```

Add a method to `LLMService`:
```python
async def synthesize_response(self, question: str, mode: str, data: list) -> dict:
    """Generate a synthesized intelligence response with confidence indicators."""
    limited = data[:30]
    results_json = json.dumps(limited, indent=2, default=str)

    try:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": SYNTHESIS_PROMPT.format(
                    question=question,
                    mode=mode,
                    count=len(data),
                    results=results_json,
                )}
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Synthesis failed", error=str(e))
        answer = f"Found {len(data)} results but failed to synthesize: {str(e)[:200]}"

    # Calculate confidence metrics
    disclosed = sum(1 for d in data if isinstance(d, dict) and d.get('total_value') is not None
                    or isinstance(d, dict) and d.get('total_projected_current_amount') is not None)

    return {
        "answer": answer,
        "confidence": {
            "data_completeness": f"{len(data)} records retrieved",
            "sample_size": len(data),
            "disclosure_rate": round(disclosed / len(data) * 100, 1) if data else None,
        },
        "follow_ups": _suggest_follow_ups(question),
    }


def _suggest_follow_ups(question: str) -> list:
    """Generate contextual follow-up question suggestions."""
    q_lower = question.lower()
    suggestions = []

    if any(w in q_lower for w in ['company', 'pfizer', 'merck', 'novartis', 'roche', 'abbvie']):
        suggestions.append("What are their most recent deals?")
        suggestions.append("Who are their top partners?")
        suggestions.append("Show their deal activity trend over 5 years")

    if any(w in q_lower for w in ['oncology', 'cancer', 'tumor']):
        suggestions.append("What are typical deal values in this space?")
        suggestions.append("Who are the most active acquirers in oncology?")

    if any(w in q_lower for w in ['adc', 'car-t', 'bispecific', 'antibody']):
        suggestions.append("Show me valuation benchmarks for this modality")
        suggestions.append("Which companies are most active in this space?")

    if any(w in q_lower for w in ['value', 'price', 'cost', 'upfront', 'milestone']):
        suggestions.append("Show me comparable deals with disclosed financials")
        suggestions.append("What's the trend in deal values over time?")

    if not suggestions:
        suggestions = [
            "Show me the largest deals this year",
            "What therapy areas are most active?",
            "Who are the top acquirers by deal volume?",
        ]

    return suggestions[:3]
```

**Step 2: Add `/api/chat/v2` endpoint to chat.py**

Add to `unified_api/routers/chat.py`:
```python
class ChatV2Response(BaseModel):
    """Enhanced chat response with synthesis."""
    answer: str
    intent: str
    confidence: dict
    data: Optional[List[dict]] = None
    sql_query: Optional[str] = None
    follow_ups: List[str] = []
    actions: List[dict] = []


@router.post("/chat/v2", response_model=ChatV2Response)
async def chat_v2(request: ChatRequest):
    """
    Enhanced conversational intelligence endpoint.

    Returns synthesized answers with:
    - Narrative response (not raw data)
    - Confidence indicators (sample size, disclosure rate)
    - Follow-up suggestions
    - Action links (save search, export, view dashboard)
    """
    from unified_api.services.llm import get_llm_service

    llm_service = get_llm_service()

    # Classify intent
    intent = await llm_service.classify_intent(request.message)

    # Route to appropriate handler and get raw data
    if intent in ["contract_search"]:
        raw_response = await _handle_rag_query(request.message)
        mode = "rag"
        data = [r.model_dump() for r in (raw_response.search_results or [])]
        sql_query = None
    elif intent in ["relationship", "company_compare"]:
        raw_response = await _handle_graph_query(request.message, llm_service)
        mode = "graph"
        data = raw_response.data or []
        sql_query = None
    else:
        raw_response = await _handle_sql_query(request.message, llm_service)
        mode = "sql"
        data = raw_response.data or []
        sql_query = raw_response.sql_query

    # Synthesize response
    synthesis = await llm_service.synthesize_response(request.message, mode, data)

    # Build action suggestions
    actions = [
        {"label": "Export to Excel", "type": "export", "params": {"format": "excel"}},
    ]
    if data:
        actions.append({"label": "Save Search", "type": "save_search", "params": {"query": request.message}})
    if intent == "deal_search":
        actions.append({"label": "View in Search", "type": "navigate", "params": {"path": "/search"}})
    if intent == "market_trends":
        actions.append({"label": "View Analytics", "type": "navigate", "params": {"path": "/analytics"}})

    return ChatV2Response(
        answer=synthesis["answer"],
        intent=intent,
        confidence=synthesis["confidence"],
        data=data[:10],
        sql_query=sql_query,
        follow_ups=synthesis["follow_ups"],
        actions=actions,
    )
```

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: chat v2 endpoint with synthesized answers, confidence indicators, follow-ups"
```

---

## Task 10: Enhanced Chat UI

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx` — full chat interface using v2 endpoint

**Step 1: Build chat page**

Replace `frontend/src/pages/ChatPage.tsx`:
```typescript
import { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Send, Sparkles, Database, ChevronRight, Loader2, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import api from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  intent?: string;
  confidence?: any;
  followUps?: string[];
  actions?: Array<{ label: string; type: string; params: any }>;
  sqlQuery?: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Handle initial query from URL
  useEffect(() => {
    const q = searchParams.get('q');
    if (q && messages.length === 0) {
      handleSend(q);
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || loading) return;
    setInput('');

    const userMsg: Message = { role: 'user', content: msg };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await api.post('/chat/v2', {
        message: msg,
        history: messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
      });

      const assistantMsg: Message = {
        role: 'assistant',
        content: res.data.answer,
        intent: res.data.intent,
        confidence: res.data.confidence,
        followUps: res.data.follow_ups,
        actions: res.data.actions,
        sqlQuery: res.data.sql_query,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleAction = (action: { label: string; type: string; params: any }) => {
    if (action.type === 'navigate') {
      navigate(action.params.path);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="text-center py-20">
            <Sparkles className="w-12 h-12 text-blue-500/50 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-slate-300 mb-2">Ask anything about pharma deals</h2>
            <p className="text-sm text-slate-500 mb-6 max-w-md mx-auto">
              Get synthesized answers with supporting data from 145K+ deals, 314K+ SEC filings, and 26K contracts.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
              {[
                'What are the largest ADC deals in oncology?',
                'Compare Pfizer and Merck deal activity',
                'Typical Phase 2 oncology deal values?',
                'Who are the most active acquirers this year?',
              ].map(q => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors text-left"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <div key={i} className={`${msg.role === 'user' ? 'flex justify-end' : ''}`}>
              {msg.role === 'user' ? (
                <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">
                  {msg.content}
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Confidence badge */}
                  {msg.confidence && (
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <Database className="w-3 h-3" />
                      <span>{msg.confidence.data_completeness}</span>
                      {msg.confidence.disclosure_rate !== null && (
                        <span>• {msg.confidence.disclosure_rate}% with disclosed values</span>
                      )}
                    </div>
                  )}

                  {/* Answer */}
                  <div className="prose prose-invert prose-sm max-w-none text-slate-300
                    prose-headings:text-slate-200 prose-strong:text-slate-200
                    prose-th:text-slate-400 prose-td:text-slate-300
                    prose-a:text-blue-400">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>

                  {/* SQL query (collapsible) */}
                  {msg.sqlQuery && (
                    <details className="text-xs">
                      <summary className="text-slate-600 cursor-pointer hover:text-slate-400">View query</summary>
                      <pre className="mt-1 p-2 bg-slate-800 rounded text-slate-400 overflow-x-auto">{msg.sqlQuery}</pre>
                    </details>
                  )}

                  {/* Follow-ups */}
                  {msg.followUps && msg.followUps.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-2">
                      {msg.followUps.map(q => (
                        <button
                          key={q}
                          onClick={() => handleSend(q)}
                          className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600"
                        >
                          <ChevronRight className="w-3 h-3" /> {q}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Actions */}
                  {msg.actions && msg.actions.length > 0 && (
                    <div className="flex gap-2 pt-1">
                      {msg.actions.map(a => (
                        <button
                          key={a.label}
                          onClick={() => handleAction(a)}
                          className="px-3 py-1.5 bg-blue-600/10 border border-blue-500/30 rounded-lg text-xs text-blue-400 hover:bg-blue-600/20"
                        >
                          {a.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Analyzing...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-800 p-4">
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          className="max-w-3xl mx-auto flex gap-2"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about deals, companies, valuations, trends..."
            className="flex-1 px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-xl transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: enhanced chat UI with synthesis, confidence badges, follow-ups, actions"
```

---

## Task 11: Integration Tests + Docker Build Verification

**Files:**
- Modify: `unified_api/main.py` — verify all routers registered
- Modify: `frontend/nginx.conf` — verify proxy routes work with React Router
- Verify: Docker Compose builds successfully

**Step 1: Verify main.py has all routers**

Ensure `unified_api/main.py` imports and registers:
```python
from unified_api.routers import (
    health, chat, search, entities, graph, analytics,
    export, xref, edgar, watchlist, contracts, auth, dashboard
)

# ... after app creation:
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(xref.router, prefix="/api")
app.include_router(edgar.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(contracts.router, prefix="/api")
```

**Step 2: Update nginx.conf for SPA routing**

Ensure `frontend/nginx.conf` has the `try_files` fallback for React Router:
```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

**Step 3: Docker build test**

```bash
cd /Users/kayleighbot/Projects/cortellis
docker compose -f docker-compose.unified.yml build api frontend
```

Expected: Both containers build successfully.

**Step 4: Create initial user seed script**

Create `unified_api/scripts/seed_users.py`:
```python
"""Seed initial users for the BD Intelligence Platform."""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text, create_engine
from unified_api.services.auth import hash_password
import os

DB_URL = os.environ.get('CORTELLIS_DB_URL', 'postgresql://cortellis:changeme@localhost:5433/cortellis')

engine = create_engine(DB_URL)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'analyst',
            preferences JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP
        )
    """))

    # Seed JVO account
    conn.execute(text("""
        INSERT INTO users (email, password_hash, name, role)
        VALUES (:email, :hash, :name, :role)
        ON CONFLICT (email) DO NOTHING
    """), {
        "email": "joyler@beigene.com",
        "hash": hash_password("BDIntel2026!"),
        "name": "John Oyler",
        "role": "ceo",
    })

    # Seed Steve account
    conn.execute(text("""
        INSERT INTO users (email, password_hash, name, role)
        VALUES (:email, :hash, :name, :role)
        ON CONFLICT (email) DO NOTHING
    """), {
        "email": "steve@ipwatcher.com",
        "hash": hash_password("BDIntel2026!"),
        "name": "Steve",
        "role": "admin",
    })

    conn.commit()
    print("Users seeded successfully")
```

**Step 5: Create end-to-end Phase 1 test suite**

Create `unified_api/tests/integration/test_phase1_e2e.py`:
```python
"""
End-to-end integration tests for Phase 1.
Verifies that all new features work together.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Register a user and return auth headers."""
    resp = client.post("/api/auth/register", json={
        "email": "e2e_phase1@test.com",
        "password": "TestPass123!",
        "name": "E2E Test User",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPhase1Endpoints:
    """Verify all Phase 1 endpoints exist and return valid responses."""

    def test_health(self, client):
        assert client.get("/api/health").status_code == 200

    def test_auth_flow(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "e2e_phase1@test.com"

    def test_dashboard(self, client):
        resp = client.get("/api/dashboard/executive")
        assert resp.status_code == 200
        data = resp.json()
        assert "market_pulse" in data
        assert "notable_deals" in data

    def test_search_deals(self, client):
        resp = client.post("/api/search/deals", json={})
        assert resp.status_code == 200
        assert "total" in resp.json()
        assert "results" in resp.json()

    def test_search_deals_with_filters(self, client):
        resp = client.post("/api/search/deals?page=1&page_size=5", json={
            "therapy_area": "Oncology",
            "disclosed_only": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["page_size"] == 5

    def test_filter_options(self, client):
        resp = client.get("/api/search/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert "therapy_areas" in data
        assert "deal_types" in data
        assert "phases" in data
        assert "statuses" in data
        assert len(data["therapy_areas"]) > 0

    def test_autocomplete_companies(self, client):
        resp = client.get("/api/search/autocomplete/companies?q=pfi")
        assert resp.status_code == 200
        assert "suggestions" in resp.json()

    def test_chat_v1_still_works(self, client):
        """Ensure original chat endpoint is not broken."""
        resp = client.post("/api/chat", json={"message": "SELECT COUNT(*) FROM deals", "mode": "sql"})
        assert resp.status_code == 200


class TestPhase1DataQuality:
    """Verify data integrity for dashboard and search."""

    @pytest.mark.cortellis
    def test_deals_table_has_data(self, cortellis_session):
        from sqlalchemy import text
        count = cortellis_session.execute(text("SELECT COUNT(*) FROM deals")).scalar()
        assert count > 100000, f"Expected 100K+ deals, got {count}"

    @pytest.mark.cortellis
    def test_therapy_areas_populated(self, cortellis_session):
        from sqlalchemy import text
        count = cortellis_session.execute(text("SELECT COUNT(*) FROM therapy_areas")).scalar()
        assert count > 0

    @pytest.mark.cortellis
    def test_finance_summary_exists(self, cortellis_session):
        from sqlalchemy import text
        count = cortellis_session.execute(text(
            "SELECT COUNT(*) FROM deal_finance_summary WHERE total_projected_current_amount IS NOT NULL"
        )).scalar()
        assert count > 10000, f"Expected 10K+ deals with financial data, got {count}"
```

**Step 6: Run the full Phase 1 test suite**

```bash
cd /Users/kayleighbot/Projects/cortellis

# Unit tests (no DB needed)
python -m pytest unified_api/tests/unit/test_auth.py -v
python -m pytest unified_api/tests/unit/test_chat_v2.py -v

# Integration tests (needs DB)
python -m pytest unified_api/tests/integration/test_auth_endpoints.py -v
python -m pytest unified_api/tests/integration/test_dashboard.py -v
python -m pytest unified_api/tests/integration/test_phase1_e2e.py -v

# All Phase 1 tests at once
python -m pytest unified_api/tests/ -v -k "auth or dashboard or chat_v2 or phase1" --tb=short
```

Expected: ALL PASS.

**Step 7: Final commit and push**

```bash
git add -A
git commit -m "feat: integration verification, e2e tests, nginx SPA routing, user seed script"
git push origin main
```

---

## Test Summary

| Test File | Type | Count | Requires |
|-----------|------|-------|----------|
| `tests/unit/test_auth.py` | Unit | 10 | Nothing |
| `tests/unit/test_chat_v2.py` | Unit | 6 | Nothing |
| `tests/integration/test_auth_endpoints.py` | Integration | 8 | Cortellis DB |
| `tests/integration/test_dashboard.py` | Integration | 9 | Cortellis DB |
| `tests/integration/test_chat_v2_endpoints.py` | Integration | 7 | Cortellis DB + OpenAI key |
| `tests/integration/test_phase1_e2e.py` | E2E | 11 | Cortellis DB |
| **Total** | | **51** | |

---

## Summary

After completing all 11 tasks, the platform will have:

1. **Multi-page app** with sidebar navigation (9 pages + 2 profile pages)
2. **JWT authentication** with login page and auth guards
3. **Executive dashboard** with KPIs, trend chart, notable deals, therapy area breakdown
4. **Advanced search** with multi-criteria filters, pagination, disclosed-only toggle
5. **Company profile** with deal timeline, partners, therapeutic focus, drug portfolio, SEC filings
6. **Drug profile** with deal history, territory rights, related companies
7. **Enhanced chat (v2)** with synthesized answers, confidence indicators, follow-ups, action links
8. **Docker-verified** builds for deployment

The remaining pages (Analytics, Competitors, Graph, Filings, Contracts, My Deals) are placeholder routes ready for Phase 2 implementation.
