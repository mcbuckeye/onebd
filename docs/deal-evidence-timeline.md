# Deal Evidence Timelines

**Design date:** 2026-07-14

## Precision boundary

A shared drug name is not enough to say that a ClinicalTrials.gov study belongs
to a specific deal. In production, a naive canonical-drug join produces more
than 2.3 million deal/trial pairs and thousands of nominal matches for some
oncology deals. Those are useful as broader asset evidence, but not as
deal-specific provenance.

The first governed link therefore requires an exact `NCT########` identifier in
the lossless current Cortellis expanded-deal response. The extractor retains the
Cortellis raw-response ID and SHA-256, exact character offsets, a readable source
excerpt, parser version, and normalized NCT ID. It does not infer links from
titles, drug names, company names, diseases, or semantic similarity.

## Timeline contents

For a deal, the source-labeled timeline combines:

- explicit Cortellis deal, development, and regulatory milestone events;
- start, primary-completion, and completion dates for exactly cited trials;
- the cited trial's current ClinicalTrials.gov status and last-posted date;
- direct links to the retained ClinicalTrials.gov source record; and
- expandable Cortellis citation evidence for every trial event.

Date precision and source labels remain visible. A planned ClinicalTrials.gov
completion date is not relabeled as an observed result or regulatory outcome.

## Operations

- `POST /api/enrichment/link-deal-clinical-trials` advances a bounded batch and
  requires an authenticated administrator.
- `GET /api/enrichment/status` reports scan coverage, citation counts, registry
  matches, failures, parser version, and link method.
- `GET /api/enrichment/deal-clinical-trials/validation` proves every normalized
  ID against its retained raw-response offsets and SHA, and reports registry
  match coverage and technical release readiness (administrator only).
- `GET /api/deal/{deal_id}/evidence-timeline` returns the standalone timeline.
- `GET /api/deal/{deal_id}` embeds the same events for the deal-detail UI.

The scheduled job is resumable by current Cortellis response ID/SHA and uses a
database advisory lock to prevent overlapping scans. Payload changes replace the
prior extracted citations for that deal and preserve the raw response itself in
the existing append-only Cortellis archive.
