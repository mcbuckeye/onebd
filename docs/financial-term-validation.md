# Cortellis Financial-Term Validation

**Audit date:** 2026-07-13

## Population baseline

Parser v2 completed all 125,360 deals with Cortellis finance JSON and created
445,904 normalized term rows. The population audit found two material conversion
defects that must be repaired before governed aggregate answers are enabled:

- 1,818 monetary terms use Cortellis unit `B` or `T`. Parser v2 treated those
  values as millions, understating them by 1,000x or 1,000,000x.
- 11,376 known percentage terms exist, but only 9,033 had a captured rate. The
  missing 2,343 are primarily profit-split and equity-stake percentages because
  v2 only populated bounds for royalty and transfer-price terms.

Parser v3 recognizes `B` and `T`, extracts every known numeric percentage, and
preserves one-sided Cortellis accuracy markers (`=<` and `>=`) as upper/lower
bounds instead of misrepresenting them as exact rates.

## Automated release gate

`GET /api/enrichment/financial-terms/validation` reports:

- source-JSON parse coverage and failures;
- full-population unit, negative-value, rate-bound, source-type, and percentage
  capture checks;
- unknown Cortellis payment types requiring taxonomy review;
- a deterministic, term-type-stratified replay sample comparing persisted fields
  with a fresh extraction from each stored source node;
- `governed_release_ready`, which stays false until parser-v3 coverage and every
  automated accuracy invariant pass.

The milestone/upfront/royalty chat guardrails must remain in place until the v3
backfill reaches 100% and the production validation endpoint reports ready.
