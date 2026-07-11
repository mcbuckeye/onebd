-- Run with psql outside an explicit transaction. CONCURRENTLY keeps filing
-- ingestion and user queries available while the 3.3M-row index is built.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_vector_ivfflat
ON chunks USING ivfflat (vector vector_cosine_ops)
WITH (lists = 1800);

ANALYZE chunks;
