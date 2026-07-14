# Company Strategy Intelligence

**Design date:** 2026-07-14

## Evidence boundary

This workflow summarizes observed Cortellis deal patterns. It does not claim to
know management intent, internal research programs, unannounced transactions,
or a company's complete competitive set. Each narrative statement is generated
deterministically from dated deal counts and retains representative deal IDs.

The company profile calls:

```text
GET /api/company/{company_id}/strategy-intelligence
    ?years=5
    &peer_limit=10
    &entrant_days=365
```

The endpoint is read-only. Parameters are bounded to 1–20 years, 1–25 peers,
and a 30–1,825 day entrant window.

## Returned intelligence

- **Observed strategy summary:** deal pace, principal/partner roles, disclosed
  value coverage, momentum versus the preceding 12 months, and top indications,
  technologies, agreement types, assets, and counterparties.
- **Deal-portfolio overlap map:** candidate companies ranked by equally weighted
  Jaccard overlap across the subject company's normalized recent indications,
  technologies, and assets. A peer may also be a partner; direct shared-deal
  counts and representative overlap deal IDs are shown explicitly.
- **First-observed indication entrants:** companies whose earliest dated
  Cortellis deal in one of the subject's top three recent indications falls in
  the selected entrant window. This is not the company's founding date or proof
  of first-ever activity in that market.

## Production validation

The implementation was executed read-only against the production Cortellis
database before deployment. For canonical Roche Holding Ltd (company `19446`),
the five-year query completed in 2.576 seconds and returned 117 dated deals,
ten normalized indication and technology focus rows, five requested overlap
peers, and 20 first-observed entrants in the one-year window.

## Durable entrant alerts

Tracked companies use a separate durable layer rather than treating every
profile view as an alert:

- `company_entrant_detections` stores one global detection per subject company,
  entrant company, and indication, with the current first-observed date, linked
  deal count, and evidence deal IDs.
- `company_entrant_alerts` stores at most one alert per user and detection. Read
  and dismissed timestamps preserve review history.
- Existing and newly tracked companies receive a baseline scan first. Current
  historical detections are retained but do not generate a notification flood.
  Only detections first seen after that baseline create user alerts.
- The Celery worker runs daily at 08:15 UTC under a PostgreSQL advisory lock.
  Pause/resume controls reset a fresh baseline when monitoring is re-enabled.
- The Competitors page lists the in-app alerts with exact company links,
  indication, observed-deal count, and evidence deal IDs. It also retrieves five
  recent deals per tracked company in one exact-ID bulk query.

The production rollback-only migration test covered both existing tracked
companies in 0.452 seconds, retained 200 baseline detections, created zero
historical alerts, and rolled the transaction back without changing production.
