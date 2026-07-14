# Contract Financial-Clause Extraction

**Design date:** 2026-07-13

## Why this lane exists

Production contains 25,977 contract documents, including 20,453 with at least
100 characters of content. Only 320 contracts currently have the older
LLM-generated `extracted_clauses` JSON, even though 8,243 PageIndex trees are
cached. Running thousands of new LLM calls before establishing precision and
cost controls would be expensive and difficult to audit.

The first at-scale lane is therefore deterministic and has no external API
cost. It identifies only explicit royalty percentages and milestone/upfront
currency amounts. Redacted values are not invented. Every candidate stores:

- contract and deal IDs;
- normalized rate or monetary bounds;
- all matched raw numeric values and their offsets;
- the exact cleaned-contract excerpt, character/line bounds, and SHA-256 hash;
- parser version, confidence, extraction timestamp, and review status.

The original contract content remains authoritative. Candidate rows are not a
substitute for reading the cited clause.

## Resumability and operations

`contract_financial_clause_extractions` records the contract hash, parser
version, status, count, and error. A transaction-scoped advisory lock prevents
overlapping replacement batches; savepoints isolate an individual malformed
contract. The scheduled batch handles 1,000 contracts at a time, while the
bounded rebuild task can populate the eligible corpus without PageIndex or
OpenAI calls.

Operational endpoints:

- `POST /api/enrichment/parse-contract-financial-clauses`
- `GET /api/enrichment/status`
- `GET /api/enrichment/contract-financial-clauses/validation`
- `GET /api/enrichment/contract-financial-clauses/review-sample`
- `PATCH /api/enrichment/contract-financial-clauses/{id}/review`

The parsing, validation, review-queue, and review-decision endpoints require an
authenticated administrator. Review decisions derive the reviewer identity from
the signed JWT rather than accepting a caller-supplied name, and each decision is
also written to the application audit log. Administrators can work the queue in
the **Clause Review** tab of the Admin panel.

## Release gates

The validator checks full eligible-contract coverage, failed extractions,
numeric bounds, source offsets/hashes, and a deterministic clause-type-stratified
replay against current contract content. Passing those checks sets
`technical_release_ready`.

`governed_release_ready` additionally requires at least 100 candidates to be
accepted/rejected and at least 95% precision. Each decision now stores a hash of
the exact clause type, source excerpt hash, normalized bounds, currency, and
tiered flag that was reviewed. A decision remains valid after a parser upgrade
only when the current row has that same assertion fingerprint; changed
assertions automatically return to the unreviewed queue. The validation report
separately identifies current-parser decisions, safely carried-forward exact
decisions, and any invalid review hashes. Until the gate passes, candidates may
support review and retrieval, but they must not drive aggregate royalty,
milestone, or upfront claims.
