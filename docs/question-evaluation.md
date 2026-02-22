# BD Intelligence Platform — Question & Analysis Evaluation

## Methodology
Each question is rated on how well the platform can answer it today:
- ✅ **Strong** — Direct answer with data, confidence indicators, sources
- 🟡 **Partial** — Can answer but with gaps (missing data, no synthesis, manual steps)
- ❌ **Cannot** — Not supported or would produce unreliable results
- 🔧 **Needs Work** — Infrastructure exists but implementation incomplete

---

## Category 1: Quick Factual Lookups
*JVO in a meeting, needs an answer in 10 seconds*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 1 | "How many deals did Pfizer do in 2024?" | ✅ | Chat v2 → SQL → synthesized answer with count + context | — |
| 2 | "What was the biggest pharma deal ever?" | ✅ | SQL → deals ordered by total_projected_current_amount DESC | Only shows disclosed deals (27%) |
| 3 | "Who are the top 5 most active acquirers this year?" | ✅ | SQL + `/analytics/top-acquirers` endpoint | — |
| 4 | "How many ADC deals have been done?" | ✅ | SQL → join deal_technologies WHERE name ILIKE '%ADC%' | — |
| 5 | "What's BeiGene's total deal count?" | ✅ | SQL → deal_companies join | — |
| 6 | "When was the last oncology M&A deal over $1B?" | ✅ | SQL with therapy_area + agreement_type + value filter | — |
| 7 | "Is there a deal between Pfizer and Seagen?" | ✅ | Graph → `/graph/deals-between` or SQL | — |
| 8 | "What phase is drug X in?" | ✅ | SQL → drugs table phase_highest_now | — |
| 9 | "How many deals closed last week?" | 🟡 | SQL with date filter works, but "last week" → needs NL date parsing | LLM handles relative dates variably |
| 10 | "What's the average deal size in oncology?" | ✅ | SQL → AVG with therapy_area filter + disclosure caveat | Auto-notes 27% disclosure rate |

**Score: 9/10 Strong, 1/10 Partial**

---

## Category 2: Analytical / Benchmarking
*VP BD preparing for a negotiation*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 11 | "What are typical upfront payments for Phase 2 ADC assets?" | ✅ | Chat v2 synthesis + `/analytics/valuations/by-phase` | Sample size may be small |
| 12 | "Show me the valuation range for oncology M&A deals 2020-2025" | ✅ | Analytics dashboards + chat | — |
| 13 | "How have deal values trended over the past 5 years?" | ✅ | `/analytics/market-trends` + chat synthesis | — |
| 14 | "What's the median milestone payment for Phase 3 license deals?" | 🟡 | Finance parser can extract milestones, but not yet aggregated into analytics endpoint | Need milestone-specific analytics endpoint |
| 15 | "Compare Pfizer vs Merck vs Novartis deal activity" | 🟡 | `/analytics/company-comparison` exists but frontend shows only 3 hardcoded IDs | Need dynamic company selection in comparison |
| 16 | "What royalty rates are typical for oncology bispecifics?" | 🔧 | Contract clause extractor exists but not run at scale; no royalty rate analytics | Need to run extraction pipeline + build royalty analytics |
| 17 | "Show me all deals with disclosed upfront over $100M" | ✅ | SQL → finance_summary filter + search page | — |
| 18 | "What percentage of deals in 2024 were M&A vs licensing?" | ✅ | `/analytics/agreement-type-distribution` | — |
| 19 | "Year-over-year deal volume growth by therapy area?" | ✅ | `/analytics/yoy-growth` with therapy filter | — |
| 20 | "What's the largest deal in each major therapy area?" | ✅ | SQL → GROUP BY therapy_area with MAX value | — |

**Score: 7/10 Strong, 2/10 Partial, 1/10 Needs Work**

---

## Category 3: Strategic / Recommendation
*JVO thinking about an acquisition*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 21 | "We want to acquire a bispecific antibody company in lung cancer. What should we pay?" | 🟡 | Chat v2 synthesis attempts strategic answer; comp builder can find comparable deals | Synthesis quality depends on LLM; no structured "acquisition framework" template |
| 22 | "Who are the most likely acquisition targets in ADC oncology?" | 🔧 | Could combine: small companies + Phase 2+ assets + no M&A deal yet, but no dedicated "target screening" feature | Need target identification algorithm |
| 23 | "Build me a comp set for a Phase 2 NSCLC bispecific license deal" | ✅ | Comp builder: indication=NSCLC + phase=Phase 2 + modality=bispecific + deal_type=License | — |
| 24 | "What's the competitive landscape for CAR-T in hematology?" | 🟡 | Briefing system + analytics can show deals/players, but no structured "landscape map" | Need therapy area landscape report template |
| 25 | "Should we build, buy, or partner for solid tumor ADC assets?" | ❌ | Too strategic for current system — would need to synthesize market access, pipeline gaps, valuation vs internal R&D cost | This is a McKinsey engagement, not a database query |
| 26 | "Which companies are divesting oncology assets?" | 🟡 | SQL can find terminated/divested deals, but "divesting" intent is nuanced | Need deal type classification for divestitures specifically |
| 27 | "What acquisition premium should we expect for a Phase 3 company?" | 🟡 | Can show M&A deal values by phase, but "premium" implies public company valuation comparison (not in our data) | Would need stock price data pre-acquisition |
| 28 | "Generate a DD package on Company X" | ✅ | DD generator: 10 sections, risk flags, financial summary | — |
| 29 | "Who are the warm introduction paths between us and Company Y?" | 🟡 | Graph path-finder (`/graph/path`) finds connection chains | Shows deal connections, not personal relationships |
| 30 | "What deals are we missing? Recommend targets I haven't seen." | 🟡 | Recommendation engine exists but uses recency+value, not personalized collaborative filtering | Need search history-based personalization |

**Score: 2/10 Strong, 5/10 Partial, 2/10 Needs Work, 1/10 Cannot**

---

## Category 4: Competitive Intelligence
*JVO tracking competitors weekly*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 31 | "What has Pfizer done in the last 90 days?" | ✅ | Company profile + chat + competitor tracking page | — |
| 32 | "Who is most actively acquiring oncology assets?" | ✅ | `/analytics/top-acquirers` with therapy filter | — |
| 33 | "Compare our deal pace to Merck's" | 🟡 | Company comparison exists but requires knowing company IDs; "our" = BeiGene needs to be configured | Need "my company" config setting |
| 34 | "Alert me when any competitor does an ADC deal" | 🟡 | Alert system exists in DB + Celery task, but saved search UI is basic | Need better alert configuration UI |
| 35 | "What's Roche's oncology strategy based on their deal pattern?" | 🟡 | Company profile shows deals/focus/partners, but no "strategy inference" | Could add LLM-synthesized strategy summary on company profile |
| 36 | "Which companies just entered the bispecific space?" | 🔧 | Technically queryable (first deal with bispecific tech in last 12m) but no dedicated "new entrant" feature | Need new entrant detection algorithm |
| 37 | "Show me Pfizer's partnership network" | ✅ | Graph network page + `/graph/partnership-network/{id}` | — |
| 38 | "How does AbbVie's deal structure differ from Gilead's?" | 🟡 | Can show deal type distributions for each, but no automated comparison narrative | Need head-to-head company comparison with synthesis |
| 39 | "Are any competitors building an ADC portfolio faster than us?" | ❌ | Would need to define "us", track ADC deal velocity over time per company, and compare | Need company-specific trend comparison |
| 40 | "Weekly competitive briefing for oncology" | 🟡 | Briefing system generates on-demand reports; email digest sends daily | No weekly scheduled briefing with competitor focus |

**Score: 3/10 Strong, 5/10 Partial, 1/10 Needs Work, 1/10 Cannot**

---

## Category 5: Due Diligence & Deal Execution
*BD team evaluating a specific target*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 41 | "Full DD on Company X" | ✅ | DD generator: overview, deals, drugs, partners, financials, risk flags | — |
| 42 | "What territories are available for Drug Y?" | ✅ | Territory rights page: committed vs terminated by territory | — |
| 43 | "Show me all contracts mentioning royalty rates for this drug" | 🟡 | Contract search (semantic + fulltext) can find mentions, but not structured extraction at scale | Clause extractor exists but needs scale run |
| 44 | "What are the risk flags for this acquisition target?" | ✅ | DD generator auto-detects: termination rate, partnership concentration, limited track record | — |
| 45 | "Export a comp set with deal values to Excel" | 🔧 | Comp builder has save, but no Excel export endpoint wired | `/export` router exists but not connected to comp sets |
| 46 | "What SEC filings relate to this deal?" | 🟡 | EDGAR search exists, company_xref links some companies, but only 692/52K matched | Entity resolution coverage too low |
| 47 | "Show me the milestone payment structure for comparable deals" | 🔧 | Finance parser extracts milestones, but no milestone-specific comparison view | Need milestone comparison feature on comp builder |
| 48 | "What's the IP landscape for KRAS inhibitors?" | ❌ | No patent data in the system | Would need patent database integration |
| 49 | "Timeline of all deals for this target company" | ✅ | Company profile deal timeline chart + DD package | — |
| 50 | "Who else has licensed this company's technology?" | ✅ | Graph → company partners + deal history | — |

**Score: 5/10 Strong, 2/10 Partial, 2/10 Needs Work, 1/10 Cannot**

---

## Category 6: Market Landscape & Reporting
*BD team preparing board materials*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 51 | "Oncology deal landscape 2024 — summary for the board" | 🟡 | Briefing system + analytics charts, but no "board-ready" formatted export | Need PowerPoint/PDF report generator |
| 52 | "Top 20 largest pharma deals of all time" | ✅ | SQL + `/analytics/top-deals` | — |
| 53 | "Deal activity heatmap by therapy area" | ✅ | `/analytics/therapy-area-heatmap` | — |
| 54 | "Show me deal volume by geography" | ✅ | `/analytics/geographic-distribution` | — |
| 55 | "What's the M&A vs licensing split in oncology over time?" | 🟡 | Analytics has agreement type distribution and market trends, but no combined time-series by type | Need stacked time-series chart by deal type |
| 56 | "Generate a market map of NSCLC deal activity" | ❌ | No market map visualization (companies × indications matrix with deal dots) | Need dedicated market map feature |
| 57 | "PDF export of this analysis for the board" | 🔧 | jsPDF installed in frontend but no export wired to any page | Need export buttons on analytics, DD, comp pages |
| 58 | "How does our therapeutic focus compare to the industry?" | 🟡 | Analytics shows industry therapy area distribution; would need BeiGene-specific overlay | Need "my company" benchmark comparison |
| 59 | "Quarterly deal report for Q2 2025" | 🟡 | Briefing system can generate, but not structured as a quarterly report | Need quarterly report template |
| 60 | "Which indications have the most deal activity growth?" | ✅ | SQL → indication deal count YoY comparison | — |

**Score: 4/10 Strong, 4/10 Partial, 1/10 Needs Work, 1/10 Cannot**

---

## Category 7: SEC Filing Intelligence
*Analyst cross-referencing public filings*

| # | Question | Rating | How It's Answered | Gap |
|---|----------|--------|-------------------|-----|
| 61 | "Find 8-K filings mentioning ADC partnerships" | ✅ | EDGAR search (semantic + fulltext) across 3.3M chunks | — |
| 62 | "Show me Pfizer's 10-K risk factors" | 🟡 | Can search filings by company (if CIK-matched) + section, but no structured section extraction | Need filing section parser |
| 63 | "Cross-reference this Cortellis deal with SEC filings" | 🟡 | Celery task for deal-filing linking exists but is a TODO stub | Need to implement matching logic |
| 64 | "Material contracts from recent 8-K filings" | 🔧 | EDGAR data exists, contract extraction exists, but not connected | Need 8-K material contract extraction pipeline |
| 65 | "S-1 filing analysis for pre-IPO biotech" | 🟡 | Can search S-1 filings, but no structured IPO analysis | Need S-1 specific extraction (pipeline, financials, risks) |

**Score: 1/5 Strong, 3/5 Partial, 1/5 Needs Work**

---

## Overall Scorecard

| Category | Strong ✅ | Partial 🟡 | Needs Work 🔧 | Cannot ❌ | Total |
|----------|-----------|------------|---------------|----------|-------|
| Quick Factual | 9 | 1 | 0 | 0 | 10 |
| Analytical | 7 | 2 | 1 | 0 | 10 |
| Strategic | 2 | 5 | 2 | 1 | 10 |
| Competitive Intel | 3 | 5 | 1 | 1 | 10 |
| Due Diligence | 5 | 2 | 2 | 1 | 10 |
| Market Landscape | 4 | 4 | 1 | 1 | 10 |
| SEC Filings | 1 | 3 | 1 | 0 | 5 |
| **TOTAL** | **31** | **22** | **8** | **4** | **65** |

**Overall: 31/65 Strong (48%), 53/65 at least Partial (82%)**

---

## Top Priority Gaps to Close

### High Impact, Low Effort (quick wins)
1. **Dynamic company comparison UI** — analytics endpoint exists, just needs company search on frontend (#15, #33, #38)
2. **"My company" configuration** — set BeiGene as default for competitive benchmarking (#33, #39, #58)
3. **Export buttons** — jsPDF installed, wire to analytics/DD/comp pages (#45, #57)
4. **Better alert configuration UI** — backend exists, frontend is minimal (#34, #40)

### High Impact, Medium Effort
5. **Strategy synthesis on company profiles** — LLM summary of deal pattern = "Pfizer's oncology strategy" (#35, #38)
6. **Milestone-specific analytics** — finance parser extracts them, need aggregation endpoint + comp builder integration (#14, #47)
7. **Quarterly/board report template** — combine existing analytics into structured PDF (#51, #59)
8. **New entrant detection** — SQL: companies with first deal in [technology] within 12 months (#36)

### High Impact, High Effort
9. **Target screening algorithm** — combine financial health, pipeline phase, partnership gaps, strategic fit scoring (#22)
10. **Market map visualization** — companies × indications matrix (#56)
11. **Scale contract clause extraction** — run GPT-4o extractor across 26K contracts for structured term database (#16, #43)
12. **Deal-filing cross-reference** — implement the Celery matching logic (#63)

### Not Feasible Without New Data
13. Patent data integration (#48)
14. Stock price / acquisition premium data (#27)
15. Personal relationship / warm introduction mapping (#29)
