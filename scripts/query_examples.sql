-- Example SQL Queries for Cortellis Deals Database

-- =============================================================================
-- BASIC QUERIES
-- =============================================================================

-- Count total deals
SELECT COUNT(*) as total_deals FROM deals;

-- Get deals by status
SELECT status, COUNT(*) as count
FROM deals
GROUP BY status
ORDER BY count DESC;

-- Recent deals (last 30 days)
SELECT id, title, status, date_start
FROM deals
WHERE date_start >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY date_start DESC
LIMIT 50;

-- =============================================================================
-- COMPANY QUERIES
-- =============================================================================

-- Find deals by company name (as either principal or partner)
SELECT d.id, d.title, d.status, c.name as company, dc.role
FROM deals d
JOIN deal_companies dc ON d.id = dc.deal_id
JOIN companies c ON dc.company_id = c.id
WHERE c.name ILIKE '%Pfizer%'
ORDER BY d.date_start DESC
LIMIT 50;

-- Top 20 most active companies (by number of deals)
SELECT c.name, c.company_type, COUNT(DISTINCT d.id) as deal_count
FROM companies c
JOIN deal_companies dc ON c.id = dc.company_id
JOIN deals d ON dc.deal_id = d.id
GROUP BY c.id, c.name, c.company_type
ORDER BY deal_count DESC
LIMIT 20;

-- Companies that appear as both Principal and Partner
SELECT c.name,
       SUM(CASE WHEN dc.role = 'Principal' THEN 1 ELSE 0 END) as principal_count,
       SUM(CASE WHEN dc.role = 'Partner' THEN 1 ELSE 0 END) as partner_count
FROM companies c
JOIN deal_companies dc ON c.id = dc.company_id
GROUP BY c.id, c.name
HAVING SUM(CASE WHEN dc.role = 'Principal' THEN 1 ELSE 0 END) > 0
   AND SUM(CASE WHEN dc.role = 'Partner' THEN 1 ELSE 0 END) > 0
ORDER BY principal_count + partner_count DESC
LIMIT 20;

-- =============================================================================
-- THERAPY AREA & INDICATION QUERIES
-- =============================================================================

-- Deals by therapy area
SELECT ta.name as therapy_area, COUNT(*) as deal_count
FROM deals d
JOIN therapy_areas ta ON d.therapy_area_id = ta.id
GROUP BY ta.name
ORDER BY deal_count DESC;

-- Top indications by deal count
SELECT i.name as indication, COUNT(DISTINCT di.deal_id) as deal_count
FROM indications i
JOIN deal_indications di ON i.id = di.indication_id
GROUP BY i.name
ORDER BY deal_count DESC
LIMIT 20;

-- Cancer deals in the last year
SELECT d.id, d.title, d.status, d.date_start,
       dfs.total_projected_current_amount as deal_value_millions
FROM deals d
JOIN therapy_areas ta ON d.therapy_area_id = ta.id
LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
WHERE ta.name ILIKE '%cancer%'
  AND d.date_start >= CURRENT_DATE - INTERVAL '1 year'
ORDER BY dfs.total_projected_current_amount DESC NULLS LAST
LIMIT 50;

-- =============================================================================
-- FINANCIAL QUERIES
-- =============================================================================

-- Largest deals by total projected current value
SELECT d.id, d.title, d.status, d.date_start,
       dfs.total_projected_current_amount as value_millions,
       dfs.total_projected_current_disclosure_status
FROM deals d
JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
WHERE dfs.total_projected_current_amount IS NOT NULL
  AND dfs.total_projected_current_disclosure_status = 'Known'
ORDER BY dfs.total_projected_current_amount DESC
LIMIT 50;

-- Average deal value by therapy area
SELECT ta.name as therapy_area,
       COUNT(*) as deal_count,
       ROUND(AVG(dfs.total_projected_current_amount)::numeric, 2) as avg_value_millions,
       ROUND(SUM(dfs.total_projected_current_amount)::numeric, 2) as total_value_millions
FROM deals d
JOIN therapy_areas ta ON d.therapy_area_id = ta.id
JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
WHERE dfs.total_projected_current_amount IS NOT NULL
  AND dfs.total_projected_current_disclosure_status = 'Known'
GROUP BY ta.name
ORDER BY total_value_millions DESC;

-- Deal value distribution by year
SELECT EXTRACT(YEAR FROM d.date_start) as year,
       COUNT(*) as deal_count,
       ROUND(AVG(dfs.total_projected_current_amount)::numeric, 2) as avg_value,
       ROUND(MAX(dfs.total_projected_current_amount)::numeric, 2) as max_value,
       ROUND(SUM(dfs.total_projected_current_amount)::numeric, 2) as total_value
FROM deals d
JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
WHERE d.date_start IS NOT NULL
  AND dfs.total_projected_current_amount IS NOT NULL
GROUP BY EXTRACT(YEAR FROM d.date_start)
ORDER BY year DESC;

-- =============================================================================
-- M&A QUERIES
-- =============================================================================

-- Recent M&A deals
SELECT d.id, d.title, d.status, d.date_start,
       mas.ownership, mas.attitude,
       mas.cash_at_acquisition, mas.price_per_share
FROM deals d
JOIN deal_ma_summary mas ON d.id = mas.deal_id
WHERE d.is_merger_acquisition = true
ORDER BY d.date_start DESC
LIMIT 50;

-- M&A deals by attitude (Friendly/Hostile)
SELECT mas.attitude, COUNT(*) as count
FROM deal_ma_summary mas
WHERE mas.attitude IS NOT NULL
GROUP BY mas.attitude
ORDER BY count DESC;

-- =============================================================================
-- DRUG & TECHNOLOGY QUERIES
-- =============================================================================

-- Deals by drug development phase
SELECT dd.drug_id, dr.name_display as drug_name,
       dr.phase_highest_start, dr.phase_highest_now,
       COUNT(DISTINCT dd.deal_id) as deal_count
FROM deal_drugs dd
JOIN drugs dr ON dd.drug_id = dr.id
GROUP BY dd.drug_id, dr.name_display, dr.phase_highest_start, dr.phase_highest_now
ORDER BY deal_count DESC
LIMIT 20;

-- Technology types used in deals
SELECT t.name as technology, COUNT(DISTINCT dt.deal_id) as deal_count
FROM technologies t
JOIN deal_technologies dt ON t.id = dt.technology_id
GROUP BY t.name
ORDER BY deal_count DESC
LIMIT 20;

-- =============================================================================
-- TIMELINE & EVENT QUERIES
-- =============================================================================

-- Deal events by type
SELECT event_type, COUNT(*) as count
FROM deal_timeline_events
GROUP BY event_type
ORDER BY count DESC;

-- Recent deal events
SELECT dte.id, d.id as deal_id, d.title, dte.event_type, dte.event_date, dte.stage
FROM deal_timeline_events dte
JOIN deals d ON dte.deal_id = d.id
WHERE dte.event_date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY dte.event_date DESC
LIMIT 50;

-- =============================================================================
-- CONTRACT QUERIES
-- =============================================================================

-- Deals with downloadable contracts
SELECT d.id, d.title, dc.id as contract_id, dc.contract_types,
       dc.has_pdf, dc.has_text, dc.date_contract
FROM deals d
JOIN deal_contracts dc ON d.id = dc.deal_id
WHERE dc.has_pdf = true OR dc.has_text = true
ORDER BY dc.date_contract DESC
LIMIT 50;

-- =============================================================================
-- COMPLEX ANALYSIS QUERIES
-- =============================================================================

-- Cross-border deals (deals with multiple territories)
SELECT d.id, d.title,
       COUNT(DISTINCT CASE WHEN dt.territory_type = 'Included' THEN dt.territory_id END) as included_count,
       COUNT(DISTINCT CASE WHEN dt.territory_type = 'Excluded' THEN dt.territory_id END) as excluded_count
FROM deals d
JOIN deal_territories dt ON d.id = dt.deal_id
GROUP BY d.id, d.title
HAVING COUNT(DISTINCT dt.territory_id) > 3
ORDER BY included_count DESC
LIMIT 50;

-- Company partnerships (who works with whom most often)
SELECT
    LEAST(c1.name, c2.name) as company_1,
    GREATEST(c1.name, c2.name) as company_2,
    COUNT(*) as partnership_count
FROM deal_companies dc1
JOIN deal_companies dc2 ON dc1.deal_id = dc2.deal_id AND dc1.company_id < dc2.company_id
JOIN companies c1 ON dc1.company_id = c1.id
JOIN companies c2 ON dc2.company_id = c2.id
GROUP BY LEAST(c1.name, c2.name), GREATEST(c1.name, c2.name)
ORDER BY partnership_count DESC
LIMIT 20;
