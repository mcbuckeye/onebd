# Cortellis API coverage audit

**Observed:** 2026-07-14
**Credential type:** legacy HTTP Digest credential configured for the Cortellis
Deals API

## Conclusion

The local database contains every deal record that an exhaustive audit can
retrieve through the configured Deals credential and now has complete exact
expanded-response, deal-source-citation, and contract-metadata scan coverage.
It is not a copy of the separately licensed Cortellis Drugs, Companies, Sources,
Patents, or Clinical Trials products.

1. `deals-v2/deal/expanded/search` advertises **149,028** deals, but its count
   is not the credential's full retrievable surface. Exhaustively requesting
   every integer ID across the stable advertised bounds 100,063 through
   506,108 returned **172,638 unique deals with zero request errors**. The
   durable reconciliation restored all **23,608** previously missing records.
   The local `deals` table now has **172,643** rows: all 172,638 currently
   retrievable IDs plus five preserved historical records that now return
   successful empty responses.
2. Sampled missing IDs return complete historical expanded records through
   direct retrieval while exact `dealId` searches report zero hits. These are
   hidden or archived records excluded from search, not pagination artifacts.
3. Lossless retention and source-citation backfills are complete for all 172,638
   API-eligible deals. PostgreSQL holds **196,340 immutable expanded-response
   versions**, **172,638 current source responses**, and **268,543 normalized
   current citations**.
4. The contract metadata scanner checked all **172,643 local deals** with zero
   unresolved failures and retained **42,573 contract records**. Full text is
   locally searchable for 25,977 contracts; document availability is governed
   by the source flags and is not expected for every metadata record.
5. The companies, drugs, indications, technologies, actions, therapy areas, and
   patents in the local database are entities embedded in deal responses. They
   are not standalone full copies of Clarivate's broader Companies or Drugs
   products.

## Live inventory

| Local object | Rows | Scope |
|---|---:|---|
| Deals | 172,643 | All 172,638 directly retrievable IDs plus five preserved retired records |
| Companies | 67,177 | Companies referenced by deals |
| Drugs/assets | 33,912 | Drugs referenced by deals; display name and phase fields |
| Indications | 2,654 | Indications referenced by deals |
| Technologies | 705 | Technologies referenced by deals |
| Actions/targets | 7,934 | Actions referenced by deals |
| Therapy areas | 21 | Therapy areas referenced by deals |
| Patents | 2,157 | Limited patent references embedded in deals |
| Timeline events | 232,058 | Deal timeline events and embedded payment JSON |
| Contract metadata | 42,573 | Complete per-deal endpoint scan |
| Exact expanded responses | 196,340 | Immutable response versions covering every eligible deal |
| Deal source citations | 268,543 | Current normalized citations; 172,638 exact source responses retained |

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

## Exhaustive numeric-ID audit

The 2026-07-14 audit first retrieved every one of the 149,035 local IDs in
30-record batches. Cortellis returned 149,030 of them while the search count
remained stable at 149,028. Five local IDs returned HTTP 200 with empty batch,
individual, and exact-search results: 168114, 327122, 465219, 491157, and
492264. The two-record excess over the advertised count proved that even
retrieval of every local ID plus count equality could not characterize the
source set.

The acceptance audit therefore stopped trusting both count and offset
pagination. It requested every integer ID from the stable minimum search ID
100,063 through stable maximum ID 506,108, using 13,535 bounded requests. The
bounds and advertised count were unchanged before and after the run. The API
returned 172,638 unique requested IDs with zero request errors. Comparing that
set with PostgreSQL found 23,608 remote-only IDs and the same five local-only
IDs.

The deployed durable repair repeated the same exhaustive discovery and finished
at 2026-07-14 02:02 UTC. It restored all 23,608 remote-only IDs in committed
30-record batches. Its before/after search snapshots were identical, all
406,046 integer IDs in the inclusive bounds were attempted, all 13,535 API
batches succeeded, and the post-repair exact-set comparison reported zero
missing IDs. PostgreSQL therefore contains the complete directly retrievable
deal membership observed for this credential. The five local-only IDs remain
preserved and explicitly reported rather than deleted.

Spot checks of remote-only IDs, including 110202, 111083, 114499, 126831, and
128220, returned populated historical deal records through direct retrieval
while `dealId:<id>` searches returned zero hits. The expanded retrieval surface
therefore includes hidden or archived deals that the search catalog does not
advertise. A complete credential archive must use bounded numeric-ID discovery
or an equivalent Clarivate-supported export; search pagination cannot supply
it.

## Credentialed Deals API surface

The credential exposes the `deals-v2` WADL and successfully serves the expanded
search/retrieval, contract metadata/document, and per-deal source-citation
operations. The application ingests all four surfaces, with durable backfills
still in progress. Other documented legacy operations returned `400 Operation
not found` or `500 Error processing API service` during the live audit and are
not counted as demonstrated access.

## Broader Cortellis products

Clarivate documents separate [Companies](https://developer.clarivate.com/apis/cortellis-np-companies-api),
[Drugs](https://developer.clarivate.com/apis/cortellis-np-drugs-api), and
[Sources](https://developer.clarivate.com/apis/cortellis-np-sources-api) APIs. Those products
contain substantially broader company profiles, drug-development history,
chemical structures, targets, indications/diseases, trials, sales forecasts,
patents, publications, and source metadata.

The configured legacy credential successfully minted a time-limited auth token
and returned data from Deals operations. The Drugs and Companies WADLs were
reachable, but fresh record and metadata requests against their declared
service base returned `500 Error processing API service` even with that token;
usable access to those products has not been demonstrated. The newer Clarivate
developer-portal APIs use API-key subscriptions, not this legacy
username/password credential. Contract paperwork or Clarivate support is still
the authoritative way to confirm whether the account should have additional
product entitlements.

## Remediation

- The daily incremental worker compares the locally eligible set with the
  durable exhaustive numeric-ID proof. The five verified retired records are
  excluded from that denominator, while the smaller advertised search count is
  retained as a drift observation rather than treated as a false failure.
- The weekly reconciliation now uses bounded numeric-ID enumeration as its
  membership proof, repairs missing records in committed batches, validates
  stable bounds before accepting success, and preserves local-only IDs for
  review rather than deleting them. Successful proof cardinality and bounds
  are stored in a dedicated singleton table, independently of mutable job
  status. A PostgreSQL advisory lock prevents two worker invocations from
  running the expensive audit concurrently.
- Both parallel scans exposed unstable offset pagination: the unsorted pass
  produced 148,754 unique IDs and the `dealId`-sorted pass produced 148,910.
  The reconciler rejects either result because neither equals the advertised
  total.
- Source/local counts and the reconciliation result flow through the common
  health/alert model. The advertised search count remains useful as a drift
  signal, but it is not a completeness denominator.
- The replacement contract scanner completed its versioned per-deal checkpoint
  across all 172,643 local deals. It retries transient failures and accepts only
  a successful empty response as a negative result. A direct credentialed probe
  confirmed that no-contract deals return HTTP 200 with
  `<dealContractsOutput/>`; the old behavior that converted API errors into
  `has_contract = false` is no longer used for completeness decisions.
- Lossless individual expanded responses and source responses are stored with
  endpoint, response hash, first/last fetch timestamps, and parser version.
  The completed scan covers every accessible ID and scheduled runs now maintain
  that position for new or changed records.
- Deal-linked source citations from `deal/sources/{dealId}` are normalized with
  source IDs, types, and API provenance. Their backfill uses the same durable
  per-deal checkpoint as exact-response retention.
