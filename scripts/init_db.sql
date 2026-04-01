-- Initialization script for Cortellis Deals Database
-- This file is executed automatically when PostgreSQL container starts

-- Create extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For text similarity searches
CREATE EXTENSION IF NOT EXISTS vector;   -- For vector embeddings (pgvector)

-- Note: Tables are created by SQLAlchemy models
-- This file is for any additional initialization needed

-- Create indexes for full-text search (optional, for better query performance)
-- These will be created after the tables exist

-- Function to create indexes safely (if tables exist)
DO $$
BEGIN
    -- Check if deals table exists before creating index
    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'deals') THEN
        -- Full text search index on deal title and summary
        CREATE INDEX IF NOT EXISTS idx_deals_title_trgm ON deals USING gin (title gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_deals_summary_trgm ON deals USING gin (summary gin_trgm_ops);
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'companies') THEN
        CREATE INDEX IF NOT EXISTS idx_companies_name_trgm ON companies USING gin (name gin_trgm_ops);
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'indications') THEN
        CREATE INDEX IF NOT EXISTS idx_indications_name_trgm ON indications USING gin (name gin_trgm_ops);
    END IF;
END $$;

-- ============================================================
-- Contract Tree Index Cache (PageIndex integration)
-- Stores generated tree structures to avoid re-indexing contracts
-- each tree costs ~$0.50 and takes 30-150 seconds to generate
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_tree_index (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    deal_id INTEGER NOT NULL,
    tree_json JSONB NOT NULL,
    line_count INTEGER,
    model VARCHAR(100) NOT NULL,
    indexed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(contract_id)
);

CREATE INDEX IF NOT EXISTS idx_contract_tree_deal_id ON contract_tree_index(deal_id);
CREATE INDEX IF NOT EXISTS idx_contract_tree_contract_id ON contract_tree_index(contract_id);
