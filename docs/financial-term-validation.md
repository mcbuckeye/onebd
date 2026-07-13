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

The first complete v3 production run exposed one internally inconsistent vendor
record: an upfront payment's reported unit was `%` with a value of 200, while
its converted value and narrative both identified a $200 million payment.
Parser v4 normalizes only an impossible percentage above 100 when the same node
contains a monetary USD conversion. The untouched Cortellis node remains in
`source_payload` for audit and replay.

## Automated release gate

`GET /api/enrichment/financial-terms/validation` reports:

- source-JSON parse coverage and failures;
- full-population unit, negative-value, rate-bound, source-type, and percentage
  capture checks;
- unknown Cortellis payment types requiring taxonomy review;
- a deterministic, term-type-stratified replay sample comparing persisted fields
  with a fresh extraction from each stored source node;
- `governed_release_ready`, which stays false until current-parser coverage and every
  automated accuracy invariant pass.

## Production result

Parser v4 completed in production on 2026-07-13:

- 125,360 of 125,360 source payloads parsed (100%);
- 445,904 normalized terms and zero failed deals;
- 11,375 of 11,375 known percentage terms captured;
- zero unrecognized units, negative amounts, invalid rates, source-type
  mismatches, or unknown payment types;
- 475 deterministic term-type-stratified replays with zero field mismatches;
- `governed_release_ready: true`.

This clears the data-quality prerequisite. Chat aggregate queries still need
explicit governed SQL patterns and evaluation truths before their refusal
guardrails are removed.
