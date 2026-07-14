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

The result is intentionally a snapshot. Durable tracked-company entrant alerts,
delivery preferences, and notification deduplication remain a separate follow-up
before the broader roadmap item is complete.
