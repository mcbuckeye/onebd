# Cortellis API coverage audit

**Observed:** 2026-07-13  
**Credential type:** legacy HTTP Digest credential configured for the Cortellis
Deals API

## Conclusion

The local database is not currently a complete, field-for-field copy of
everything exposed by the configured credential.

1. `deals-v2/deal/expanded/search` advertised **149,006** deals while the local
   `deals` table contained **146,931**, a cardinality gap of **2,075**.
2. The local schema is a normalized projection of expanded deal records, not a
   raw archive. A sampled expanded record exposed `ProductNumber` and root
   attributes that the current transformer does not persist. Other complex
   fields such as finance detail and cross-references are retained as JSON, but
   the complete source response is not stored.
3. Contract coverage is not proven. The database contains 41,626 contract
   records, but only 16,194 deals have a non-null `has_contract` state and the
   old file-based scan checkpoint is absent from the deployed data directory.
4. The companies, drugs, indications, technologies, actions, therapy areas, and
   patents in the local database are entities embedded in deal responses. They
   are not standalone full copies of Clarivate's broader Companies or Drugs
   products.

## Live inventory

| Local object | Rows | Scope |
|---|---:|---|
| Deals | 146,931 | Expanded Deals API projection |
| Companies | 52,889 | Companies referenced by deals |
| Drugs/assets | 33,653 | Drugs referenced by deals; display name and phase fields |
| Indications | 2,583 | Indications referenced by deals |
| Technologies | 662 | Technologies referenced by deals |
| Actions/targets | 7,876 | Actions referenced by deals |
| Therapy areas | 19 | Therapy areas referenced by deals |
| Patents | 2,156 | Limited patent references embedded in deals |
| Timeline events | 203,889 | Deal timeline events and embedded payment JSON |
| Contract metadata | 41,626 | Contract endpoint results obtained to date |

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
- Source/local counts and the reconciliation result flow through the common
  health/alert model.
- A complete contract scan still needs to be resumed from durable database
  state before contract completeness can be claimed.
- Full raw expanded-record retention should be added if field-for-field archive
  fidelity is a requirement.
