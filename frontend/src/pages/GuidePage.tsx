import { BookOpen, Search, MessageSquare, BarChart3, Scale, Building2, Pill, Shield, MapPin, FileText, ScrollText, Network, Star, TrendingUp, Lightbulb, CalendarDays } from 'lucide-react';

export default function GuidePage() {
  return (
    <div className="min-h-screen bg-slate-950">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-3">
            <BookOpen className="w-8 h-8 text-blue-500" />
            <h1 className="text-3xl font-bold text-slate-100">User Guide</h1>
          </div>
          <p className="text-slate-400 text-lg">Comprehensive guide to the BD Intelligence Platform</p>
        </div>

        {/* Table of Contents */}
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800 mb-8">
          <h2 className="text-lg font-semibold text-slate-200 mb-4">Quick Navigation</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <a href="#getting-started" className="text-blue-400 hover:text-blue-300">Getting Started</a>
            <a href="#ask-mode" className="text-blue-400 hover:text-blue-300">Ask Mode (Chat)</a>
            <a href="#search" className="text-blue-400 hover:text-blue-300">Search</a>
            <a href="#analytics" className="text-blue-400 hover:text-blue-300">Analytics</a>
            <a href="#catalyst-calendar" className="text-blue-400 hover:text-blue-300">Catalyst Calendar</a>
            <a href="#comp-builder" className="text-blue-400 hover:text-blue-300">Comp Builder</a>
            <a href="#company-profiles" className="text-blue-400 hover:text-blue-300">Company Profiles</a>
            <a href="#drug-profiles" className="text-blue-400 hover:text-blue-300">Drug Profiles</a>
            <a href="#due-diligence" className="text-blue-400 hover:text-blue-300">Due Diligence</a>
            <a href="#territory-rights" className="text-blue-400 hover:text-blue-300">Deal Territory Scope</a>
            <a href="#briefings" className="text-blue-400 hover:text-blue-300">Briefings</a>
            <a href="#partnership-network" className="text-blue-400 hover:text-blue-300">Partnership Network</a>
            <a href="#competitor-tracking" className="text-blue-400 hover:text-blue-300">Competitor Tracking</a>
            <a href="#my-deals" className="text-blue-400 hover:text-blue-300">My Deals</a>
            <a href="#contracts-filings" className="text-blue-400 hover:text-blue-300">Contracts & Filings</a>
            <a href="#data-notes" className="text-blue-400 hover:text-blue-300">Data Notes</a>
          </div>
        </div>

        {/* Getting Started */}
        <Section id="getting-started" icon={BookOpen} title="Getting Started">
          <p className="text-slate-300 mb-4">Welcome to the BD Intelligence Platform. This section covers the basics to get you oriented.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Login</h3>
          <p className="text-slate-400 mb-4">Access the platform at the login page. Enter your credentials to access the dashboard.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Dashboard Overview</h3>
          <p className="text-slate-400 mb-4">The dashboard is your starting point, showing recent activity, saved searches, and quick access to key features.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Navigation</h3>
          <p className="text-slate-400 mb-2">Use the left sidebar to access all platform features:</p>
          <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4">
            <li>Dashboard — overview and recent activity</li>
            <li>Search — find deals by multiple criteria</li>
            <li>Analytics — market trends and insights</li>
            <li>Catalysts — trial completion calendar and exports</li>
            <li>Competitors — track competitor activity</li>
            <li>Network — explore partnership relationships</li>
            <li>Filings — search EDGAR filings</li>
            <li>Contracts — search contract language</li>
            <li>My Deals — watchlist and saved searches</li>
            <li>Teams — shared evidence, notes, and discussion</li>
            <li>Comps — build comparable deal sets</li>
            <li>Due Diligence — generate DD packages</li>
            <li>Ask — natural language queries</li>
          </ul>
          
          <ProTip>Use the global search bar at the top to ask questions from any page.</ProTip>
        </Section>

        {/* Ask Mode */}
        <Section id="ask-mode" icon={MessageSquare} title="Ask Mode (Chat)">
          <p className="text-slate-300 mb-4">Ask questions in natural language and get intelligent answers from the platform's knowledge base.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">How to Ask Questions</h3>
          <p className="text-slate-400 mb-4">Type your question in plain English. The system understands context and can handle both simple lookups and complex strategic queries.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Query Complexity Spectrum</h3>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <p className="text-slate-300 font-medium mb-2">Simple queries:</p>
            <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4 mb-4">
              <li>"Show me recent deals in oncology"</li>
              <li>"What's the average upfront for Phase 2 assets?"</li>
            </ul>
            <p className="text-slate-300 font-medium mb-2">Strategic queries:</p>
            <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4">
              <li>"What valuation trends are emerging in antibody-drug conjugates?"</li>
              <li>"How do Japanese pharma licensing strategies differ from US companies?"</li>
            </ul>
          </div>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Follow-up Suggestions</h3>
          <p className="text-slate-400 mb-4">After each answer, the system may suggest related questions to explore the topic further.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Confidence Indicators</h3>
          <p className="text-slate-400 mb-4">Answers include confidence scores based on data availability and query complexity. Higher confidence means the answer is well-supported by disclosed deal data.</p>
          
          <ProTip>Start broad, then narrow down. Ask "Show me CAR-T deals" first, then "Which had upfronts over $100M?"</ProTip>
        </Section>

        {/* Search */}
        <Section id="search" icon={Search} title="Search">
          <p className="text-slate-300 mb-4">Advanced multi-criteria search across the currently synchronized Cortellis deal corpus.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Multi-Criteria Filters</h3>
          <p className="text-slate-400 mb-2">Filter deals by:</p>
          <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4 mb-4">
            <li>Therapeutic area (oncology, CNS, etc.)</li>
            <li>Deal type (licensing, acquisition, collaboration)</li>
            <li>Development stage (preclinical, Phase 1-3, marketed)</li>
            <li>Territory (worldwide, US, EU, Asia, etc.)</li>
            <li>Deal date range</li>
            <li>Financial thresholds (upfront, milestones, total value)</li>
          </ul>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Disclosed-Only Toggle</h3>
          <p className="text-slate-400 mb-4">Enable this to restrict results to deals with a disclosed value. Always use the displayed eligible and disclosed N when interpreting valuation statistics.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Company Search</h3>
          <p className="text-slate-400 mb-4">Search by licensor, licensee, or both. Autocomplete helps you find companies quickly.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Pagination & Exporting</h3>
          <p className="text-slate-400 mb-4">Results are paginated for performance. Export results to CSV or Excel for further analysis.</p>
          
          <ProTip>Save complex searches to "My Deals" for quick access later. Keyboard shortcut: Cmd/Ctrl + S</ProTip>
        </Section>

        {/* Analytics */}
        <Section id="analytics" icon={BarChart3} title="Analytics">
          <p className="text-slate-300 mb-4">Visualize market trends, valuations, and competitive dynamics across multiple dimensions.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Market Trends Tab</h3>
          <p className="text-slate-400 mb-4">Track deal volume and value over time by therapeutic area, deal type, or territory. Identify emerging hotspots and cooling sectors.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Valuations Tab</h3>
          <p className="text-slate-400 mb-4">Analyze upfront payments, milestones, and total deal values. Charts show median, quartiles, and outliers.</p>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <p className="text-slate-300 font-medium mb-2">Understanding N and Disclosure Rate:</p>
            <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4">
              <li><span className="font-medium text-slate-300">N =</span> number of deals in the dataset for that filter</li>
              <li><span className="font-medium text-slate-300">Disclosure rate:</span> percentage of those N deals with disclosed financials</li>
              <li>Disclosure varies by cohort and changes as synchronization and normalization progress; use the live N shown in the result.</li>
            </ul>
          </div>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Geographic Tab</h3>
          <p className="text-slate-400 mb-4">View deal activity by region. See where licensors and licensees are based, and which territories are most valuable.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Competitive Tab</h3>
          <p className="text-slate-400 mb-4">Compare activity across companies. See who's most active in licensing-in vs. licensing-out, and in which areas.</p>
          
          <ProTip>Hover over charts for exact values. Click legend items to toggle series on/off.</ProTip>
        </Section>

        {/* Catalyst Calendar */}
        <Section id="catalyst-calendar" icon={CalendarDays} title="Catalyst Calendar">
          <p className="text-slate-300 mb-4">Track upcoming clinical-trial primary-completion dates reported by ClinicalTrials.gov.</p>

          <h3 className="text-lg font-semibold text-slate-200 mb-2">Filtering and Evidence</h3>
          <p className="text-slate-400 mb-4">Filter by date, phase, status, title, sponsor, drug, condition, or NCT number. Company, drug, and indication badges appear only where OneBD has an exact normalized link; source date precision and estimated versus actual labels remain visible.</p>

          <h3 className="text-lg font-semibold text-slate-200 mb-2">Exports and Scheduled Reports</h3>
          <p className="text-slate-400 mb-4">Export the current filters to CSV for analysis or iCalendar for Outlook, Google Calendar, and Apple Calendar. In Settings, enable a daily or weekly intelligence digest and choose a 14–180 day catalyst look-ahead window.</p>

          <ProTip>Treat a primary-completion date as a monitoring signal, not a guaranteed readout date. Open the ClinicalTrials.gov source before making a decision.</ProTip>
        </Section>

        {/* Comp Builder */}
        <Section id="comp-builder" icon={Scale} title="Comp Builder">
          <p className="text-slate-300 mb-4">Build custom comparable deal sets for valuation benchmarking. Follow these steps:</p>
          
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <h3 className="text-slate-300 font-semibold mb-3">Step 1: Define Criteria</h3>
            <p className="text-slate-400 mb-2">Set your target deal characteristics:</p>
            <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4">
              <li>Therapeutic area and mechanism of action</li>
              <li>Development stage (±1 stage for flexibility)</li>
              <li>Territory scope</li>
              <li>Deal type</li>
            </ul>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <h3 className="text-slate-300 font-semibold mb-3">Step 2: Find Comps</h3>
            <p className="text-slate-400">The system suggests deals matching your criteria, ranked by similarity. Review the top 20-30 candidates.</p>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <h3 className="text-slate-300 font-semibold mb-3">Step 3: Select Comps</h3>
            <p className="text-slate-400">Check the deals you want to include. Aim for 5-15 high-quality comps with disclosed terms.</p>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <h3 className="text-slate-300 font-semibold mb-3">Step 4: Compare & Analyze</h3>
            <p className="text-slate-400">View side-by-side comparison tables and summary statistics. Export to Excel for modeling.</p>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <h3 className="text-slate-300 font-semibold mb-3">Step 5: Save</h3>
            <p className="text-slate-400">Save your comp set to "My Deals" for future reference and updates as new deals are added.</p>
          </div>
          
          <ProTip>Narrow criteria = fewer comps but higher relevance. Broaden if you need more data points.</ProTip>
        </Section>

        {/* Company Profiles */}
        <Section id="company-profiles" icon={Building2} title="Company Profiles">
          <p className="text-slate-300 mb-4">Detailed company pages show deal history, strategic focus, and partnership patterns.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">What's Shown</h3>
          <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4 mb-4">
            <li>Company overview and key stats</li>
            <li>All deals (as licensor and licensee)</li>
            <li>Therapeutic area focus</li>
            <li>Deal type distribution</li>
            <li>Financial summary (total disclosed value, average upfront)</li>
            <li>Partnership network graph</li>
          </ul>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Navigating from Search</h3>
          <p className="text-slate-400 mb-4">Click any company name in search results or deal cards to open the profile. Use the back button to return to search results.</p>
          
          <ProTip>Add companies to "Competitors" for monitoring. You'll get alerts when they announce new deals.</ProTip>
        </Section>

        {/* Drug Profiles */}
        <Section id="drug-profiles" icon={Pill} title="Drug Profiles">
          <p className="text-slate-300 mb-4">Drug/asset pages summarize linked deal history and the latest territory-scope evidence found in deal records.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Deal History</h3>
          <p className="text-slate-400 mb-4">See the bounded linked deal history returned for this asset. Disclosed total values are not equivalent to realized payments.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Deal Territory Scope</h3>
          <p className="text-slate-400 mb-4">View territory and scope labels attached to sourced deals. These records do not establish current ownership, retained rights, termination, or availability without reviewing the underlying agreement and later events.</p>
          
          <ProTip>Look for assets with multiple deals at different stages to understand value inflection points.</ProTip>
        </Section>

        {/* Due Diligence */}
        <Section id="due-diligence" icon={Shield} title="Due Diligence">
          <p className="text-slate-300 mb-4">Generate a sourced due-diligence starting package for target companies or assets. It is not a substitute for legal, regulatory, financial, or scientific diligence.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">How to Generate a DD Package</h3>
          <ol className="list-decimal list-inside text-slate-400 space-y-2 ml-4 mb-4">
            <li>Navigate to DD page</li>
            <li>Enter company or asset name</li>
            <li>Select scope: financial, regulatory, competitive, or all</li>
            <li>Click "Generate Package"</li>
            <li>Review and export to PDF or Word</li>
          </ol>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Understanding Risk Flags</h3>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-3 h-3 bg-red-500 rounded-full"></div>
              <span className="text-slate-300 font-medium">Red flags:</span>
              <span className="text-slate-400">Critical issues requiring immediate attention (e.g., terminated prior deals, litigation)</span>
            </div>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
              <span className="text-slate-300 font-medium">Yellow flags:</span>
              <span className="text-slate-400">Moderate concerns for further investigation (e.g., delayed milestones, regulatory warnings)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-green-500 rounded-full"></div>
              <span className="text-slate-300 font-medium">Green indicators:</span>
              <span className="text-slate-400">Positive signals (e.g., successful milestone achievements, strong IP position)</span>
            </div>
          </div>
          
          <ProTip>Regenerate a package after data updates and verify every material conclusion against its linked evidence.</ProTip>
        </Section>

        {/* Territory Rights */}
        <Section id="territory-rights" icon={MapPin} title="Deal Territory Scope">
          <p className="text-slate-300 mb-4">Search territory and scope labels attached to deal records for an asset.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Searching by Drug</h3>
          <p className="text-slate-400 mb-4">Enter a drug/asset name to see linked deal-scope evidence, participants, dates, and statuses.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Interpreting the Evidence</h3>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <ul className="space-y-2">
              <li className="text-slate-400"><span className="font-medium text-blue-400">Territory:</span> Geographic label recorded for the cited deal.</li>
              <li className="text-slate-400"><span className="font-medium text-purple-400">Scope:</span> Direction or scope label supplied by the source record when available.</li>
              <li className="text-slate-400"><span className="font-medium text-amber-400">Status:</span> Status of that deal record, not a legal conclusion about present rights.</li>
            </ul>
          </div>
          
          <ProTip>Do not infer availability from a missing record. Confirm current rights through contracts, amendments, and direct diligence.</ProTip>
        </Section>

        {/* Briefings */}
        <Section id="briefings" icon={FileText} title="Briefings">
          <p className="text-slate-300 mb-4">Generate executive briefings on therapeutic areas, companies, or market trends.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">On-Demand Briefings</h3>
          <p className="text-slate-400 mb-4">Request a briefing topic. The current briefing is a deterministic summary of matching deal records and states its method and match count.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Topic Suggestions</h3>
          <p className="text-slate-400 mb-2">Not sure what to brief on? Try these:</p>
          <ul className="list-disc list-inside text-slate-400 space-y-1 ml-4 mb-4">
            <li>"Antibody-drug conjugate licensing trends 2023-2025"</li>
            <li>"Japanese pharma outbound deals in oncology"</li>
            <li>"GLP-1 agonist competitive landscape"</li>
            <li>"Preclinical asset valuations in rare disease"</li>
          </ul>
          
          <ProTip>Copy a generated briefing into your governed work product; saved briefing persistence is not currently enabled.</ProTip>
        </Section>

        {/* Partnership Network */}
        <Section id="partnership-network" icon={Network} title="Partnership Network">
          <p className="text-slate-300 mb-4">Visualize relationships between companies based on deal history.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Company Search</h3>
          <p className="text-slate-400 mb-4">Enter a company to see its partnership network. Node size represents deal count, edge thickness represents total value.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Industry Overview</h3>
          <p className="text-slate-400 mb-4">View a bounded graph of normalized partnership relationships. Large graph views intentionally limit nodes and edges for performance.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Understanding Connections</h3>
          <p className="text-slate-400 mb-4">Direct connections = deals between two companies. Indirect = shared partners. Hover on edges to see deal details.</p>
          
          <ProTip>Look for "hub" companies with many connections — they're often prolific licensors or serial acquirers.</ProTip>
        </Section>

        {/* Competitor Tracking */}
        <Section id="competitor-tracking" icon={TrendingUp} title="Competitor Tracking">
          <p className="text-slate-300 mb-4">Monitor competitor deal activity and strategic moves.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Adding Companies</h3>
          <p className="text-slate-400 mb-4">Use the company autocomplete on the Competitors page to select the exact company record you want to track.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Monitoring Activity</h3>
          <p className="text-slate-400 mb-4">The Competitors page shows exact-ID recent deal activity and evidence-limited first-observed indication entrants for tracked companies. Entrant monitoring establishes a historical baseline before creating deduplicated in-app alerts, which can be marked read, dismissed, paused, or resumed.</p>
          
          <ProTip>Treat “first observed” as a monitoring signal to review the cited deals, not as proof that the company has never worked in the space before.</ProTip>
        </Section>

        {/* My Deals */}
        <Section id="my-deals" icon={Star} title="My Deals">
          <p className="text-slate-300 mb-4">Your personal workspace for saved searches, watchlists, and search history.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Watchlist</h3>
          <p className="text-slate-400 mb-4">Star individual deals from search results to add to your watchlist. Great for tracking specific transactions you're analyzing.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Saved Searches</h3>
          <p className="text-slate-400 mb-4">Save complex filter combinations for quick re-running against the data available at execution time.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Search History</h3>
          <p className="text-slate-400 mb-4">Last 30 days of search activity. Click any to re-run or refine.</p>

          <h3 className="text-lg font-semibold text-slate-200 mb-2">Team Workspaces</h3>
          <p className="text-slate-400 mb-4">Use Teams to share typed OneBD records or source links, explain why they matter, and keep colleague comments attached to the evidence. Owners control editor and viewer membership.</p>
          
          <ProTip>Name saved searches descriptively: "Q1 2025 Oncology Phase 2 Licensing" {'>'} "Search 1"</ProTip>
        </Section>

        {/* Contracts & Filings */}
        <Section id="contracts-filings" icon={ScrollText} title="Contracts & Filings">
          <p className="text-slate-300 mb-4">Search the currently indexed EDGAR filings and Cortellis contract excerpts for specific language and clauses.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Semantic vs Full-Text Search</h3>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <p className="text-slate-300 font-medium mb-2">Semantic search:</p>
            <p className="text-slate-400 mb-3">Understands meaning. Example: "indemnification for IP infringement" also finds "hold harmless for patent claims"</p>
            <p className="text-slate-300 font-medium mb-2">Full-text search:</p>
            <p className="text-slate-400">Exact phrase matching. Faster for known terms like "change of control"</p>
          </div>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Searching Indexed Excerpts</h3>
          <p className="text-slate-400 mb-4">Each filing is split into semantic chunks. Search results show relevant chunks with context. Click to view full document.</p>
          
          <ProTip>Use hybrid for a ranked blend, semantic for concepts, and full-text for known terms. Results are bounded excerpts, not proof that every relevant clause was found.</ProTip>
        </Section>

        {/* Data Notes */}
        <Section id="data-notes" icon={Lightbulb} title="Data Notes">
          <p className="text-slate-300 mb-4">Important context about the platform's data sources and limitations.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Financial Disclosure Is Incomplete</h3>
          <p className="text-slate-400 mb-4">Many pharmaceutical deals do not disclose financial terms. The live disclosed N and eligible N are the relevant denominators for each filter; do not generalize a platform-wide percentage to a specific cohort.</p>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">Data Sources</h3>
          <div className="bg-slate-800 rounded-lg p-4 mb-4">
            <ul className="space-y-2 text-slate-400">
              <li><span className="font-medium text-slate-300">Cortellis:</span> Licensed deal records and the companies, assets, indications, technologies, territories, and available contract material linked to them under the configured credential.</li>
              <li><span className="font-medium text-slate-300">SEC EDGAR:</span> Public filings and indexed filing text for matched issuers.</li>
              <li><span className="font-medium text-slate-300">Public enrichment:</span> ClinicalTrials.gov and selected public biology and identity sources where exact links are available.</li>
              <li><span className="font-medium text-slate-300">Coverage:</span> Missing records and unresolved links are possible; zero results do not prove absence.</li>
            </ul>
          </div>
          
          <h3 className="text-lg font-semibold text-slate-200 mb-2">What "N=" Means</h3>
          <p className="text-slate-400 mb-4">
            <span className="font-medium text-slate-300">N =</span> the number of deals matching your filter criteria. Example: "Median upfront $25M (N=47, 34% disclosed)" means 47 deals matched, 34% had disclosed upfronts, and the median of those disclosed values is $25M. Always consider N and disclosure rate when interpreting statistics.
          </p>
          
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
            <p className="text-blue-300 font-medium mb-2">Data Freshness</p>
            <p className="text-slate-400">Open the dashboard health details for each source's last successful run, last data-changing run, source-data timestamp, lag, failures, and retry state. A successful no-op run does not mean the underlying data changed.</p>
          </div>
        </Section>

        {/* Footer */}
        <div className="mt-12 pt-6 border-t border-slate-800 text-center">
          <p className="text-slate-500 text-sm">For access or data questions, contact your OneBD administrator.</p>
        </div>
      </div>
    </div>
  );
}

// Helper component for sections
function Section({ id, icon: Icon, title, children }: { id: string; icon: any; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mb-12 scroll-mt-6">
      <div className="flex items-center gap-3 mb-4">
        <Icon className="w-6 h-6 text-blue-500" />
        <h2 className="text-2xl font-bold text-slate-100">{title}</h2>
      </div>
      <div className="pl-9">
        {children}
      </div>
    </section>
  );
}

// Helper component for pro tips
function ProTip({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 mt-4">
      <div className="flex items-start gap-2">
        <Lightbulb className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-blue-300 font-medium text-sm mb-1">Pro Tip</p>
          <p className="text-slate-300 text-sm">{children}</p>
        </div>
      </div>
    </div>
  );
}
