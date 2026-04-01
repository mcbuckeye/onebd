"""
Clinical Protocol Analyzer.

Dedicated analysis mode for clinical study protocols with optimized
prompts for different question types (endpoints, eligibility, dosing,
statistics, safety). Uses PageIndex for tree-based retrieval.
"""
import structlog

logger = structlog.get_logger(__name__)

# Optimized extraction prompts for each protocol question type
PROTOCOL_PROMPTS = {
    "endpoints": """Extract ALL efficacy endpoints from this clinical protocol:

1. PRIMARY ENDPOINT(S): exact measure, timeframe, assessment method
2. SECONDARY ENDPOINTS: list each with measure and timeframe
3. EXPLORATORY ENDPOINTS: if present
4. JUSTIFICATION: why this primary endpoint was chosen

Be precise — cite section numbers and page numbers.""",

    "eligibility": """Extract the COMPLETE inclusion and exclusion criteria:

1. INCLUSION CRITERIA: list every criterion with specific thresholds (age, diagnosis, prior therapy, lab values)
2. EXCLUSION CRITERIA: list every criterion
3. SCREENING PROCEDURES: what tests/assessments are required
4. SPECIAL POPULATIONS: women of childbearing potential, hepatic/renal impairment rules

Number each criterion. Be exhaustive — a clinical ops professional needs every detail.""",

    "dosing": """Extract the complete dosing regimen:

1. DOSE AMOUNT: exact mg/kg, volume, concentration
2. ROUTE: IV, SC, oral, etc.
3. FREQUENCY: how often (QD, BID, Q2W, etc.)
4. SCHEDULE: visit schedule, cycle length, treatment duration
5. DOSE MODIFICATIONS: reduction rules, hold criteria, re-escalation
6. CONCOMITANT MEDICATIONS: required, allowed, prohibited

Include all treatment arms if randomized.""",

    "statistics": """Extract the statistical design:

1. SAMPLE SIZE: number of patients, per arm
2. POWER CALCULATION: power level, effect size, assumed parameters
3. RANDOMIZATION: ratio, stratification factors, method
4. PRIMARY ANALYSIS: statistical test, analysis population (ITT, PP, mITT)
5. MULTIPLICITY: adjustment method for multiple comparisons
6. MISSING DATA: handling method (LOCF, MMRM, multiple imputation)
7. INTERIM ANALYSIS: planned yes/no, timing, stopping rules

Cite section numbers.""",

    "safety": """Extract safety monitoring and stopping rules:

1. SAFETY ASSESSMENTS: AE recording, labs, vitals, ECG, imaging schedule
2. SAE REPORTING: timeline, to whom
3. STOPPING RULES: individual patient and study-level
4. DSMB/DMC: composition, meeting schedule, charter
5. DOSE-LIMITING TOXICITY: definition if applicable
6. SPECIAL SAFETY MONITORING: suicidality, hepatotoxicity, cardiac, pregnancy

Be specific about timing and thresholds.""",

    "general": """Analyze this clinical study protocol and provide:

1. STUDY TITLE and phase
2. SPONSOR and key investigators
3. STUDY DESIGN: randomized, blinded, controlled, parallel/crossover
4. STUDY POPULATION: disease, line of therapy, key criteria
5. INTERVENTIONS: treatment arms, doses, schedule
6. PRIMARY ENDPOINT and sample size
7. KEY DATES: if available

Provide a concise executive summary suitable for a BD professional.""",
}

# Keywords for classifying protocol questions
_QUESTION_PATTERNS = {
    "endpoints": ["endpoint", "primary outcome", "secondary outcome", "efficacy measure", "primary objective"],
    "eligibility": ["inclusion", "exclusion", "eligib", "criteria", "enrollment", "patient selection"],
    "dosing": ["dose", "dosing", "regimen", "administration", "route", "schedule", "treatment arm"],
    "statistics": ["sample size", "power", "statistical", "randomiz", "analysis plan", "multiplicity"],
    "safety": ["safety", "monitoring", "stopping rule", "adverse event", "dsmb", "dmc", "toxicity"],
}


def classify_protocol_question(question: str) -> str:
    """
    Classify a protocol question to select the optimized prompt.

    Returns one of: endpoints, eligibility, dosing, statistics, safety, general
    """
    q_lower = question.lower()

    scores = {}
    for category, keywords in _QUESTION_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in q_lower)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)

    return "general"
