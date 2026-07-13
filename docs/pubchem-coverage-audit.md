# PubChem Identifier Coverage Audit

**Audit date:** 2026-07-13

## Production baseline

The Cortellis mirror contains 33,653 drug/asset rows and 33,648 drugs with at
least one source alias. The initial PubChem lane had processed 4,423 drugs:

- 1,632 matched PubChem CIDs and InChIKeys;
- 1,604 connectivity SMILES values;
- 2,791 first-query not-found results;
- 29,230 drugs not yet represented by a terminal result.

Of the 1,632 matches, 1,250 PubChem titles are normalized-exact with the query
and 1,282 share a meaningful title token. Title divergence is not automatically
an error: development codes, brands, salts, and INNs often resolve through a
PubChem synonym to a systematic or preferred title. The validation endpoint
therefore exposes a deterministic divergent-title review sample instead of
silently rejecting those mappings.

## Defect and remediation

The first implementation stored one state row per drug. After the preferred
alias returned 404, the drug was marked `not_found` permanently even when a
different display name or development code remained available.

`drug_public_enrichment_queries` now stores attempts independently for each
normalized alias. Existing state is migrated into that table, a miss advances
to the next untried alias, and transient 429/503 failures retry independently
with bounded exponential backoff. The per-drug state remains as an operational
summary (`pending`, `matched`, `not_found`, or `failed`).

The worker advances 500 aliases every 15 minutes with a 0.22-second inter-request
delay. That is below PubChem's documented maximum of five requests per second,
and 429/503 responses still slow down and retry. PubChem documents both the
[PUG REST usage policy](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) and
[dynamic request throttling](https://pubchem.ncbi.nlm.nih.gov/docs/dynamic-request-throttling).

## Validation

`GET /api/enrichment/pubchem/validation` reports:

- eligible, matched, exhausted, failed, and in-progress drug coverage;
- alias-query attempt outcomes and terminal coverage;
- CID, InChIKey, and connectivity-SMILES coverage;
- matched-state/CID consistency, evidence/CID/source-link fidelity, InChIKey
  shape, and per-query/per-drug state consistency;
- shared CIDs across Cortellis asset rows as an informational count (a public
  compound may legitimately correspond to multiple formulations/assets);
- deterministic title-exact, title-token-overlap, and divergent-title samples.

`identifier_integrity_ready` covers stored-record correctness. It does not mean
the corpus is complete; `coverage_complete` remains false until every eligible
drug is matched or exhausts all aliases with no terminal failures.
