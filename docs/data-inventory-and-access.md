# OneBD data inventory and colleague access

**Production snapshot:** 2026-07-14
**Audience:** internal colleagues evaluating available data and programmatic access

## Executive answer

OneBD has a complete local archive of the deal records retrievable through the
configured legacy **Cortellis Deals API** credential. That credential returned
172,638 unique deals in an exhaustive ID audit, and none are missing locally.
The database also preserves five retired local records that the API no longer
returns.

This does **not** mean the credential provides the complete Cortellis Drugs,
Companies, Sources, Patents, or Clinical Trials products. The companies, drugs,
indications, targets/actions, technologies, territories, patents, and timelines
described below are objects embedded in or linked from Deals responses. Clarivate
markets separate, paid APIs for the much broader standalone product records.

OneBD supplements Deals with SEC EDGAR, ClinicalTrials.gov, PubChem, ChEMBL,
Open Targets, UniProt, Europe PMC, GLEIF, and Wikidata. Those integrations are
source-attributed and should not be described to colleagues as Cortellis data.

## Cortellis Deals data available locally

| Data object | Production rows | What is retained |
|---|---:|---|
| Deals | 172,643 | 172,638 API-retrievable deals plus 5 preserved retired records |
| Deals with phase at signing | 63,772 | Highest deal-asset phase at the deal start |
| Deals with current phase | 64,312 | Highest current phase within each deal response |
| Exact expanded-response versions | 196,340 | Lossless XML/JSON response history and hashes |
| Deal source responses | 172,638 | Complete source-citation response coverage for retrievable deals |
| Normalized source citations | 268,543 | Current source ID and source type links |
| Companies | 67,177 | Companies referenced by deals; name, type, HQ when supplied |
| Drugs/assets | 33,912 | Deal-referenced assets, display name and highest phase fields |
| Indications | 2,654 | Deal-referenced indications |
| Actions/mechanisms | 7,934 | Deal-referenced target/action concepts |
| Technologies | 705 | Deal-referenced technology concepts |
| Therapy areas | 21 | Deal classification concepts |
| Territories | 262 | Included/excluded deal territories |
| Patents | 2,157 | Limited deal-embedded patent references |
| Company links | 343,088 | Principal/partner relationships |
| Drug links | 79,301 | Deal-to-asset relationships |
| Indication links | 243,413 | Deal-to-indication relationships, including principal flag |
| Action links | 236,458 | Deal-to-action relationships, including primary/secondary type |
| Technology links | 400,709 | Deal-to-technology relationships, including principal flag |
| Timeline events | 232,058 | Stage/status events and embedded payment/drug structures |
| Finance summaries | 172,643 | Paid/projected amounts, currency, unit, disclosure status, raw detail |
| Normalized financial terms | 445,904 | Parser-v4 upfront, milestone, royalty and related source-derived terms |
| M&A summaries | 11,277 | M&A-specific product, ownership, investor and financial fields |
| Contract metadata | 42,573 | Complete per-deal metadata scan, PDF/text flags, dates and redaction |
| Searchable contract texts | 25,978 | Downloaded and indexed full text |
| Contract chunks | 897,130 | Full-text/RAG chunks for contract retrieval |

### Deal fields

The normalized deal record includes title, summary, deal type, status,
agreement/asset/transaction category, optional and M&A flags, start/end/event/
update/add dates, highest phase at signing and currently, therapy area, cross
references, companies and roles, drugs, indications, technologies, mechanisms,
territories, patents, high-level finance, detailed source payment structures,
timeline events, M&A fields, contract metadata, and source citations.

Lossless expanded-response history is retained specifically so fields that have
not yet been promoted into normalized columns are not discarded. The governed
colleague API initially returns normalized records; raw payload export can be
added as a separately scoped endpoint if the owner wants it.

### Completeness evidence

The Deals search endpoint advertised 149,028 records but omitted accessible
hidden/archived records and repeated/omitted IDs under offset pagination. The
accepted audit therefore tested every integer ID from 100,063 through 506,108 in
13,535 API batches. It returned 172,638 unique deals with zero request errors.
The database has zero remote IDs missing. Complete contract-metadata and exact
response/source scans cover every eligible deal.

## What the configured Cortellis credential does not demonstrate

Clarivate's current developer portal describes separate paid product APIs:

- The [Cortellis Drugs API](https://developer.clarivate.com/apis/cortellis-np-drugs-api)
  includes standalone current and historical development status, companies,
  chemical structures, mechanisms, targeted indications, sales/forecasts, SWOT,
  regulatory, clinical, patent and source intelligence. Our credential has not
  demonstrated access to that product.
- The [Cortellis Companies API](https://developer.clarivate.com/apis/cortellis-np-companies-api)
  includes broad profiles, ownership, organization type, financials, contacts,
  subsidiaries, drug sales/forecasts, trials, patents and publications. Our
  67,177 companies are deal-referenced entities, not this standalone dataset.
- The [Cortellis Sources API](https://developer.clarivate.com/apis/cortellis-np-sources-api)
  includes bibliographic title, author, origin and publication details. OneBD's
  normalized Deals surface currently retains deal-linked source IDs and types,
  not a complete standalone Sources archive.

The legacy username/password could reach those products' WADLs during audit,
but record requests did not return usable data. The developer-portal products
require API-key subscriptions. Clarivate account paperwork/support remains the
authoritative entitlement record.

## Other data available in OneBD

| Source | Production inventory | Useful data |
|---|---:|---|
| SEC EDGAR | 330,818 documents; 330,295 texts; 3,580,771 chunks | Filings, exhibits/contracts, source URLs, extracted deals, parties, assets, indications and terms |
| ClinicalTrials.gov | 593,857 current trials | Sponsors, phase, status/history, design, endpoints, enrollment, dates, results, interventions, conditions, collaborators and locations |
| PubChem | 5,055 exact structure matches | CID, InChIKey, connectivity SMILES and source-verified public titles |
| ChEMBL 37 | 3,853 structure-confirmed drugs | ChEMBL ID, molecule fields, 3,851 typed INN aliases and 6,698 development codes |
| Open Targets 26.06 | 3,118 drug profiles; 972 targets; 2,829 diseases | Drug descriptions, mechanisms, target/disease links and development stages |
| UniProt | 973 target records | Reviewed accessions, proteins, genes, function, disease/location and sequence metadata |
| Europe PMC | 20,432 publication records; 45,479 target links | Structured publication metadata and exact target/accession citations |
| GLEIF | 475 verified LEIs | Legal entity identity and verified direct/ultimate parent evidence |
| Wikidata | 129 reviewable domains | Official websites matched only through exact verified LEIs |
| Neo4j | Derived graph | Cross-database company/deal relationships for graph queries |

The public drug enrichment is deliberately conservative: PubChem requires exact
source-name resolution; ChEMBL requires an exact InChIKey; Open Targets follows
the confirmed ChEMBL ID; and UniProt follows exact Swiss-Prot accessions. Missing
coverage is reported as missing, not filled with fuzzy inferred biology.

## License and source-use notes

These labels are documentation, **not automatic enforcement**. The system owner
chooses technical access policy independently.

- Cortellis is commercial licensed content; permitted users and redistribution
  depend on the organization's Clarivate agreement.
- [SEC EDGAR](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
  is freely accessible public filing data; SEC fair-access rules apply to source
  acquisition.
- [ClinicalTrials.gov](https://clinicaltrials.gov/about-site/terms-conditions)
  data are free of charge but require source attribution, currency, processing
  date, and modification disclosure on publication/distribution.
- [PubChem](https://pubchem.ncbi.nlm.nih.gov/docs/downloads) is free to use, but
  contributor-specific rights can apply; provenance should be retained.
- [ChEMBL](https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/general-questions)
  is CC BY-SA 3.0.
- [Open Targets](https://platform-docs.opentargets.org/licence) Platform data are
  CC0 1.0, with upstream third-party rights still relevant.
- [UniProt](https://www.uniprot.org/help/license) applies CC BY 4.0 to
  copyrightable database content.
- [Europe PMC](https://europepmc.org/Help) metadata are accessible, but full-text
  reuse depends on each article's license.
- [GLEIF](https://www.gleif.org/en/meta/lei-data-terms-of-use) LEI data are CC0.
- [Wikidata](https://www.wikidata.org/wiki/Wikidata:Copyright) structured data
  are CC0.

## Governed read-only API

The versioned API is rooted at:

```text
https://onebd.pchomelab.com/api/v1
```

It provides live catalog, deals, deal detail, normalized financial terms,
companies, drugs, clinical trials, biology targets/diseases, EDGAR filing
metadata, and source-health endpoints.
Every list uses a bounded cursor (`after_id` or `after_nct_id`) and a maximum of
100 records per request. It does not accept arbitrary SQL.

An administrator issues a key through `POST /api/admin/api-credentials`. The
plaintext is returned once; only its SHA-256 hash is stored. Keys have scopes,
optional expiry, use counters, last-use path/time, and immediate revocation.

Example:

```bash
curl -H "Authorization: Bearer $OWNER_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"BD team","scopes":["data:read"]}' \
  https://onebd.pchomelab.com/api/admin/api-credentials

curl -H "X-API-Key: $ONEBD_API_KEY" \
  'https://onebd.pchomelab.com/api/v1/deals?query=oncology&limit=25'

curl -H "X-API-Key: $ONEBD_API_KEY" \
  'https://onebd.pchomelab.com/api/v1/financial-terms?term_type=upfront_payment&min_amount_usd_millions=100&limit=25'
```

### Owner-controlled enforcement

`GET/PUT /api/admin/data-access-policy` controls the runtime policy:

- `key_required` (default): a valid scoped API key is required.
- `authenticated`: either a scoped API key or a signed-in OneBD user is allowed.
- `open`: the versioned read-only data API is public.
- `enforce_scopes`: can be turned on or off.
- `allow_self_registration`: controls whether new analyst accounts can register;
  it defaults to off, while administrators can always create users.
- `protect_existing_api`: optionally extends the selected global access mode to
  the existing application API; it defaults to off to avoid disrupting the UI.
- `disabled_datasets`: can disable individual API dataset groups without
  changing the advisory license catalog.

The versioned colleague API and MCP adapter always follow this policy.
Application login and administrative policy routes remain reachable so the
owner cannot lock out the control plane. Health checks remain public. Existing
application data routes follow the same global mode when
`protect_existing_api` is enabled.

Administrators can manage the same controls in **Admin -> API Access**. The
console issues scoped keys, shows plaintext once, reports use/expiry/revocation,
and can revoke a key immediately. It also exposes every policy and dataset
switch above, with warnings before opening anonymous access or applying
key-only protection to legacy application routes. Key issuance, revocation, and
policy changes are recorded in the audit log without storing key plaintext.
Signed-in API access rechecks the live user record on every request, so disabling
an account takes effect immediately instead of waiting for its JWT to expire.

## MCP access

The MCP server is a thin stdio adapter over the governed HTTP API; it does not
receive database credentials and cannot bypass API policy.

```json
{
  "mcpServers": {
    "onebd": {
      "command": "python",
      "args": ["-m", "unified_api.mcp_server"],
      "env": {
        "ONEBD_API_URL": "https://onebd.pchomelab.com/api/v1",
        "ONEBD_API_KEY": "onebd_..."
      }
    }
  }
}
```

Available MCP tools cover the catalog, deals, normalized deal financial terms,
companies, drugs, trials, targets, diseases, EDGAR documents, and source status.
The same key scopes, revocation, dataset toggles, and owner access mode apply.

## Recommended colleague briefing language

> OneBD contains a complete local archive of all 172,638 deal records directly
> retrievable through our Cortellis Deals API credential, plus five preserved
> retired records. Deal-linked companies and assets are available, but they are
> not complete copies of the separately licensed Cortellis Companies or Drugs
> products. OneBD adds source-attributed trial, biology, literature, entity, and
> SEC filing data from public providers. Colleagues can use a governed read-only
> API or MCP key; access enforcement is controlled by the OneBD owner and is
> separate from the documented license metadata.
