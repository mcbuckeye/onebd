# OneBD Completion — Design Document

**Date:** 2026-04-02
**Author:** Supercoder
**Approved by:** Steve McLaughlin

## Scope

Six independent tasks to close remaining frontend gaps in the BD Intelligence Platform.

### 1. Force-Directed Graph Visualization
- Replace flat list in GraphPage.tsx with react-force-graph-2d
- Nodes sized by deal count, colored by company type
- Click node → navigate to /company/:id
- Hover tooltip: company name + deal count

### 2. Deal Detail Panel
- Click deal row in SearchPage → slide-in panel from right
- Shows full deal detail: companies, drugs, indications, territories, financials, timeline, contracts
- Company names link to /company/:id, drug names to /drug/:id
- Close button + click-outside-to-close

### 3. Search Results Export
- Add "Export CSV" and "Export Excel" buttons to SearchPage header
- Use existing /api/export/search-results/excel and /api/export/deals/csv endpoints
- Pass current filters to export endpoint
- Download file via blob URL

### 4. Persistent Competitor Tracking
- New backend endpoints: GET/POST/DELETE /api/competitors
- Backed by new competitors table (user_id, company_id, created_at)
- CompetitorsPage loads from API instead of local state
- Add/remove persists across sessions

### 5. Notification Bell
- Wire header bell icon to /api/notifications
- Show unread count badge (red dot with number)
- Click → dropdown panel showing recent notifications
- Mark as read on open via PATCH /api/notifications/read-all

### 6. Email Digest Configuration
- New settings section accessible from user menu or admin
- Pick tracked therapy areas, companies, frequency (daily/weekly/off)
- Backend: /api/settings/digest GET/PUT endpoints
- Stores in user_preferences table
