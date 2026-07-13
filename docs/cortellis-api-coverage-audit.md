# Cortellis API coverage audit

**Observed:** 2026-07-13  
**Credential type:** legacy HTTP Digest credential configured for the Cortellis
Deals API

## Conclusion

The local database is **not** a complete, field-for-field copy of everything
exposed by the configured credential.

1. `deals-v2/deal/expanded/search` advertises **149,006** deals. Two repair
   passes raised the local `deals` table from **146,931** to **149,013**, but
   neither offset scan returned all advertised unique IDs. The latest sorted
   pass returned **148,910 unique IDs**, restored five more records, and
   correctly remained `partial`.
2. The local schema is a normalized projection of expanded deal records, not a
   raw archive. A sampled expanded record exposed `ProductNumber` and root
   attributes that the current transformer does not persist. Other complex
   fields such as finance detail and cross-references are retained as JSON, but
   the complete source response is not stored.
3. The credential returns deal-linked source citations from
   `deals-v2/deal/sources/{dealId}`. The local ingestion path does not call or
   store that endpoint.
4. Contract coverage is not complete. The durable scanner has checked only
   **3,000 of 149,013 deals (2.01%)** and currently holds 41,786 contract
   records. Eighteen advertised PDFs do not have a recorded local path.
5. The companies, drugs, indications, technologies, actions, therapy areas, and
   patents in the local database are entities embedded in deal responses. They
   are not standalone full copies of Clarivate's broader Companies or Drugs
   products.

## Live inventory

| Local object | Rows | Scope |
|---|---:|---|
| Deals | 149,013 | Expanded Deals API projection; exact source set not proven |
| Companies | 53,656 | Companies referenced by deals |
| Drugs/assets | 33,888 | Drugs referenced by deals; display name and phase fields |
| Indications | 2,596 | Indications referenced by deals |
| Technologies | 672 | Technologies referenced by deals |
| Actions/targets | 7,932 | Actions referenced by deals |
| Therapy areas | 20 | Therapy areas referenced by deals |
| Patents | 2,156 | Limited patent references embedded in deals |
| Timeline events | 206,199 | Deal timeline events and embedded payment JSON |
| Contract metadata | 41,786 | Contract endpoint results obtained to date |
| Deal source citations | 0 | Accessible endpoint is not ingested |

## First reconciliation result

The first repair run restored **2,077** deal IDs and raised the local count to
**149,008**, but deliberately finished `partial`. Fetching all advertised page
positions without a sort produced only **148,754 unique IDs**; the API's default
ordering repeated 252 IDs across pages. Consequently, the run's 254 apparent
local-only IDs are not a trustworthy extra-record set and the two-row net excess
does not prove there are only two true extras. A rerun using monotonic `dealId`
sorting is required to establish the exact zero-missing/extra set.

## Sorted reconciliation result

The `dealId`-sorted acceptance run still exposed unreliable offset pagination.
It fetched all 149,006 advertised positions but produced only **148,910 unique
IDs**. It found five source IDs absent locally and restored all five, raising the
local total to 149,013, but the run remained `partial` by design. Its 103
apparent local-only records were not a valid deletion set: a direct bulk
retrieval of the first 20 returned all 20 successfully from the API. This proves
that the search scan omitted accessible records despite its sort parameter.

Catalog proof now needs either validated/retried page-boundary scanning or a
full retrieval-based membership audit. Row-count equality or a union of
incomplete scans is not sufficient evidence.

## Credentialed Deals API surface

The credential exposes the `deals-v2` WADL and successfully serves the expanded
search/retrieval, contract metadata/document, and per-deal source-citation
operations. The application currently ingests expanded deal records and
contract data, but not `deal/sources/{dealId}`. Other documented legacy
operations returned `400 Operation not found` or `500 Error processing API
service` during the live audit and are not counted as demonstrated access.

## Broader Cortellis products

Clarivate documents separate [Companies](https://developer.clarivate.com/apis/cortellis-np-companies-api),
[Drugs](https://developer.clarivate.com/apis/cortellis-np-drugs-api), and
[Sources](https://developer.clarivate.com/apis/cortellis-np-sources-api) APIs. Those products
contain substantially broader company profiles, drug-development history,
chemical structures, targets, indications/diseases, trials, sales forecasts,
patents, publications, and source metadata.

The configured legacy credential successfully authenticated and returned data
from the Deals expanded search/retrieval operations. Fresh authenticated probes
of the legacy drugs and company operations reached the services but returned
`500 Error processing API service`; therefore usable access to those products
has not been demonstrated. The newer Clarivate developer-portal APIs use API-key
subscriptions, not this legacy username/password credential. Contract paperwork
or Clarivate support is still the authoritative way to confirm whether the
account should have additional product entitlements.

## Remediation

- The daily incremental worker now compares the advertised source count with
  the local count and marks the source partial on a mismatch.
- A weekly full-ID reconciliation scans the authoritative Deals catalog,
  restores only missing deal IDs, retrieves their contracts, and preserves
  local-only IDs for review rather than deleting them.
- Both parallel scans exposed unstable offset pagination: the unsorted pass
  produced 148,754 unique IDs and the `dealId`-sorted pass produced 148,910.
  The reconciler rejects either result because neither equals the advertised
  total.
- Source/local counts and the reconciliation result flow through the common
  health/alert model.
- A complete contract scan still needs to be resumed from durable database
  state before contract completeness can be claimed. The replacement scanner
  stores a versioned per-deal checkpoint in PostgreSQL, advances in bounded
  scheduled batches, retries transient failures, exposes coverage and terminal
  failures, and accepts only a successful empty response as a negative result.
  A direct credentialed probe confirmed that no-contract deals return HTTP 200
  with `<dealContractsOutput/>`. The legacy client incorrectly converted every
  contract API error into `has_contract = false`.
- Add lossless raw expanded-response retention with a response hash, fetch
  timestamp, and parser version if archive fidelity is required.
- Ingest deal-linked source citations from `deal/sources/{dealId}` with source
  IDs and types, preserving their API provenance.
