# EDGAR production query-plan verification

Verified on `onebd.pchomelab.com` on 2026-07-11 against approximately 3.35
million embedded chunks. Plans used `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)`.

| Query | Plan | Execution | Important buffers |
|---|---|---:|---:|
| `agreement`, form `8-K`, 500 candidates | Parallel document filter + `ix_chunks_document_id` | 136 ms | 10,839 hits |
| `agreement`, unfiltered, 500 candidates | Bounded sequential scan (common term) | 508 ms | 2,999 hits / 782 reads |
| `bispecific antibody`, 500 candidates | Bitmap scan on `idx_chunks_text_search` | 26 ms | 13 hits / 295 reads |
| cosine nearest 20, 40 IVFFlat probes | `idx_chunks_vector_ivfflat` index scan | 534 ms | 36 hits / 188,207 reads |

The planner appropriately prefers the document-id path for the selective 8-K
filter, the GIN index for a rarer compound term, and IVFFlat for cosine ordering.
The common-term query stays bounded below one second because only 500 candidates
are materialized before ranking.

`chunks_text_search_idx` and `idx_chunks_text_search` were identical 994 MB GIN
expression indexes. `pg_stat_user_indexes` showed 0 scans for the former and 16
for the latter. The unused duplicate was removed with `DROP INDEX CONCURRENTLY`;
`idx_chunks_text_search` remains valid and selected by the rare-term plan.

Re-run the HTTP latency smoke budget with:

```bash
python -m unified_api.scripts.benchmark_edgar_search \
  --base-url https://onebd.pchomelab.com
```
