"""LLM-powered feature extraction for job descriptions and candidate sources."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid

from dotenv import load_dotenv

from .models import (
    LLM_MODEL,
    Candidate,
    Constraint,
    ConstraintOperator,
    ConstraintSide,
    ConstraintType,
    JobDescription,
)

load_dotenv()

_anthropic_client = None
_client_lock = threading.Lock()


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        with _client_lock:
            if _anthropic_client is None:
                import anthropic
                _anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _anthropic_client

# ---------------------------------------------------------------------------
# Canonical key guidance — domain-agnostic instruction for consistent key
# assignment across any professional matching domain.
# ---------------------------------------------------------------------------
CONSTRAINT_KEY_GUIDANCE = """
Canonical key assignment:
Assign a short, descriptive snake_case canonical_key to each constraint.
- The key should capture the constraint dimension (what is being constrained):
  compensation, location, working arrangement, qualifications, scheduling, values, etc.
- Be consistent: choose the label that another LLM, given the same constraint,
  would independently produce. This consistency enables matching across documents.
- Good examples: salary_minimum, weekly_office_days, work_authorization,
  notice_period_weeks, publication_count_min, on_call_frequency, travel_percent
- Use null only for purely qualitative constraints where no clear dimension key applies.
Do not limit yourself to any predefined list — choose the most natural key for the domain.

Value format:
When a constraint can be expressed numerically (as a count, amount, rate, or duration),
always use a numeric value rather than a qualitative phrase. For example:
- "fully remote" → value: 0 (not "fully_remote")
- "five days per week" → value: 5 (not "five days")
- "at least two years" → value: 2 (not "two years")
Reserve strings for values that are genuinely categorical (e.g. currency codes, named
tiers, jurisdiction names).
"""

# ---------------------------------------------------------------------------
# Few-shot examples — cover explicit, implicit, and missing-data cases
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CONSTRAINT EXTRACTION:

Example 1 — Explicit hard employer constraint:
Source text: "This role is 5 days per week in our London office. No exceptions."
Constraint:
  type: hard, side: employer, category: location,
  canonical_key: office_days_per_week, value: 5, operator: requires,
  confidence: 0.97, description: "Must be in office 5 days per week"

Example 2 — Explicit hard employer constraint (visa):
Source text: "Applicants must have the right to work in the UK. We do not offer visa sponsorship."
Constraint:
  type: hard, side: employer, category: visa,
  canonical_key: visa_sponsorship, value: false, operator: requires,
  confidence: 0.97, description: "No visa sponsorship offered; right to work required"

Example 3 — Explicit hard candidate constraint (salary):
Source text: "I'm looking for a role paying at least £90,000."
Constraint:
  type: hard, side: candidate, category: compensation,
  canonical_key: salary_min, value: 90000, operator: min, currency: "GBP",
  confidence: 0.95, description: "Minimum salary expectation £90,000"

Example 4 — Explicit hard candidate constraint (remote):
Source text: "I work fully remote — that's non-negotiable for me."
Constraint:
  type: hard, side: candidate, category: location,
  canonical_key: office_days_per_week, value: 0, operator: max,
  confidence: 0.97, description: "Requires fully remote; max 0 days in office"

Example 5 — Soft candidate constraint (4-day week preference):
Source text: "I'd love a four-day week if possible — it's important to me but not a dealbreaker."
Constraint:
  type: soft, side: candidate, category: work_arrangement,
  canonical_key: four_day_week, value: true, operator: prefers,
  confidence: 0.90, description: "Prefers four-day working week"

Example 6 — Implicit soft employer constraint (culture):
Source text: "We're a fast-paced startup and value people who thrive under pressure."
Constraint:
  type: soft, side: employer, category: culture,
  canonical_key: null, value: "high-pace startup", operator: prefers,
  confidence: 0.72, description: "Preference for candidates comfortable in fast-paced startup culture"

Example 7 — Novel candidate constraint (no canonical key):
Source text: "I only work with B-corp certified companies. It's a core value for me."
Constraint:
  type: hard, side: candidate, category: ethics,
  canonical_key: bcorp_required, value: true, operator: requires,
  confidence: 0.95, description: "Only works with B-corp certified employers"

Example 8 — Ambiguous constraint (low confidence):
Source text: "I'm probably looking for something around £70,000 to maybe £80,000 depending on benefits."
Constraint:
  type: soft, side: candidate, category: compensation,
  canonical_key: salary_min, value: 70000, operator: min,
  confidence: 0.62, description: "Approximate salary expectation £70–80k (ambiguous)"

Example 9 — Missing data (do NOT infer):
Source text: "Looking for a new challenge in fintech."
→ Do NOT extract a salary constraint. Do NOT infer any constraint that is not stated.
"""


# ---------------------------------------------------------------------------
# Regex pre-extraction helpers
# ---------------------------------------------------------------------------
# Matches: £105,000 / £105k / £85K / $90,000 / €80k etc.
_MONEY_RE = re.compile(r'([£$€])\s*([\d,]+)\s*([kK])?', re.IGNORECASE)



def _find_salary_hints(text: str, label: str) -> list[str]:
    """Return human-readable salary hints detected by regex in text."""
    hints = []
    seen = set()
    for match in _MONEY_RE.finditer(text):
        currency, digits, kilo = match.groups()
        try:
            amount = int(digits.replace(',', ''))
            if kilo:
                amount *= 1000
            # Filter to plausible salary range (20k–1M)
            if 20_000 <= amount <= 1_000_000 and amount not in seen:
                seen.add(amount)
                hints.append(f"{currency}{amount:,} (found in {label})")
        except ValueError:
            pass
    return hints



# ---------------------------------------------------------------------------
# JD extraction tool schema
# ---------------------------------------------------------------------------
JD_TOOL_SCHEMA = {
    "name": "extract_job_description",
    "description": "Extract structured fields from a raw job description text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Job title"},
            "company": {"type": "string", "description": "Company name"},
            "required_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Must-have technical skills",
            },
            "preferred_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Nice-to-have technical skills",
            },
            "min_years_experience": {
                "type": "integer",
                "description": "Minimum years of relevant experience",
            },
            "seniority": {
                "type": "string",
                "enum": ["junior", "mid", "senior", "lead", "principal", "staff"],
            },
            "management_required": {
                "type": "boolean",
                "description": "Whether the role requires managing people",
            },
            "industries_preferred": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industries the employer prefers candidates to have worked in",
            },
            "industries_acceptable": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industries considered acceptable background",
            },
            "constraints": {
                "type": "array",
                "description": "Employer-side constraints extracted from the job description",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["hard", "soft"]},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "canonical_key": {"type": ["string", "null"]},
                        "value": {},
                        "operator": {
                            "type": "string",
                            "enum": ["requires", "max", "min", "prefers", "excludes", "one_of"],
                        },
                        "weight": {"type": "number"},
                        "confidence": {"type": "number"},
                        "currency": {
                            "type": ["string", "null"],
                            "description": "ISO 4217 code for salary constraints (GBP, USD, EUR). Null for non-salary constraints.",
                        },
                    },
                    "required": ["type", "category", "description", "operator", "confidence"],
                },
            },
        },
        "required": [
            "title",
            "company",
            "required_skills",
            "preferred_skills",
            "min_years_experience",
            "seniority",
            "management_required",
            "constraints",
        ],
    },
}


CANDIDATE_SOURCE_TOOL_SCHEMA = {
    "name": "extract_candidate_source",
    "description": "Extract structured fields from a single candidate source document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "years_experience": {
                "type": "number",
                "description": "Years of relevant professional experience",
            },
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Technical and domain skills mentioned",
            },
            "industries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industries the candidate has worked in",
            },
            "seniority_level": {
                "type": "string",
                "enum": ["junior", "mid", "senior", "lead", "principal", "staff"],
            },
            "management_experience": {
                "type": "boolean",
                "description": "Whether the candidate has people management experience",
            },
            "education_level": {
                "type": "string",
                "enum": ["high_school", "bachelor", "master", "phd", "other"],
            },
            "career_trajectory": {
                "type": "string",
                "enum": ["ascending", "lateral", "mixed"],
                "description": "ascending=consistent growth, lateral=similar roles, mixed=varied",
            },
            "interview_score": {
                "type": "number",
                "description": "0.0–1.0 score for communication, clarity, and enthusiasm shown",
            },
            "culture_fit_score": {
                "type": "number",
                "description": "0.0–1.0 inferred culture fit from stated values and preferences",
            },
            "constraints": {
                "type": "array",
                "description": "Candidate-side constraints extracted from this source",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["hard", "soft"]},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "canonical_key": {"type": ["string", "null"]},
                        "value": {},
                        "operator": {
                            "type": "string",
                            "enum": ["requires", "max", "min", "prefers", "excludes", "one_of"],
                        },
                        "weight": {"type": "number"},
                        "confidence": {"type": "number"},
                        "currency": {
                            "type": ["string", "null"],
                            "description": "ISO 4217 code for salary constraints (GBP, USD, EUR). Null for non-salary constraints.",
                        },
                    },
                    "required": ["type", "category", "description", "operator", "confidence"],
                },
            },
        },
        "required": [
            "years_experience",
            "skills",
            "industries",
            "seniority_level",
            "management_experience",
            "constraints",
        ],
    },
}


# Single-pass full candidate extraction schema (replaces 3+1 call approach)
CANDIDATE_FULL_TOOL_SCHEMA = {
    "name": "extract_candidate_full",
    "description": "Extract all structured candidate fields from combined source documents into a single canonical record.",
    "input_schema": {
        "type": "object",
        "properties": {
            "years_experience": {"type": "number"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "industries": {"type": "array", "items": {"type": "string"}},
            "seniority_level": {
                "type": "string",
                "enum": ["junior", "mid", "senior", "lead", "principal", "staff"],
            },
            "management_experience": {"type": "boolean"},
            "education_level": {
                "type": "string",
                "enum": ["high_school", "bachelor", "master", "phd", "other"],
            },
            "career_trajectory": {
                "type": "string",
                "enum": ["ascending", "lateral", "mixed"],
            },
            "interview_score": {"type": "number"},
            "culture_fit_score": {"type": "number"},
            "constraints": {
                "type": "array",
                "description": "All candidate-side constraints, deduplicated across all sources",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["hard", "soft"]},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "canonical_key": {"type": ["string", "null"]},
                        "value": {},
                        "operator": {
                            "type": "string",
                            "enum": ["requires", "max", "min", "prefers", "excludes", "one_of"],
                        },
                        "weight": {"type": "number"},
                        "confidence": {"type": "number"},
                        "currency": {
                            "type": ["string", "null"],
                            "description": "ISO 4217 code for salary constraints (GBP, USD, EUR). Null for non-salary constraints.",
                        },
                    },
                    "required": ["type", "category", "description", "operator", "confidence"],
                },
            },
        },
        "required": [
            "years_experience",
            "skills",
            "industries",
            "seniority_level",
            "management_experience",
            "constraints",
        ],
    },
}


MERGE_TOOL_SCHEMA = {
    "name": "merge_candidate_sources",
    "description": "Merge multiple single-source candidate extractions into a single canonical Candidate record, deduplicating constraints and resolving conflicts.",
    "input_schema": CANDIDATE_FULL_TOOL_SCHEMA["input_schema"],
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
JD_SYSTEM_PROMPT = f"""You are an expert at extracting structured requirements and constraints from professional job postings.

Extract all constraints from the job description accurately.
Mark constraints as "hard" only when the source text is explicit:
  words like "must", "required", "mandatory", "no exceptions", "will not".
Use "soft" for preferences, desirables, and implicit signals.

DO NOT infer constraints that are not stated in the text.
Confidence reflects how explicitly the constraint is stated (0.97 = verbatim; 0.60 = implicit).

{CONSTRAINT_KEY_GUIDANCE}

{FEW_SHOT_EXAMPLES}"""

CANDIDATE_SYSTEM_PROMPT = f"""You are an expert at extracting structured requirements and constraints from professional candidate documents.

Extract all candidate-side constraints accurately.
Mark constraints as "hard" only when the candidate is clearly inflexible:
  "non-negotiable", "only", "will not", "must".
Use "soft" for preferences and stated ideals.

DO NOT infer constraints that are not present in this specific source document.
If compensation figures are vague or unclear, set confidence below 0.75.
Confidence reflects how explicitly the constraint is stated (0.97 = verbatim; 0.60 = vague/implied).

interview_score and culture_fit_score: only score these when the source is an interview transcript.
  For CV or LinkedIn sources, set both to null (omit from output or set 0.5 as neutral).

{CONSTRAINT_KEY_GUIDANCE}

{FEW_SHOT_EXAMPLES}"""

MERGE_SYSTEM_PROMPT = f"""You are merging multiple extractions of the same candidate from different source documents into a single canonical record.

Rules:
1. Deduplicate constraints with the same canonical_key — keep the version with the highest confidence, or merge if values are complementary.
2. If two sources give conflicting values for the same constraint, prefer the interview transcript, then CV, then LinkedIn.
3. Skills, industries: union of all sources, deduplicated and normalised.
4. years_experience: take the most specific value (usually from CV).
5. interview_score and culture_fit_score: take from interview_transcript extraction only.
6. Constraints stated ONLY in the interview transcript are valid and should be preserved — they represent real preferences even if not in the CV.

{CONSTRAINT_KEY_GUIDANCE}"""

CANDIDATE_FULL_SYSTEM_PROMPT = f"""You are an expert at extracting structured requirements and constraints from professional candidate documents.

You will receive all available source documents for one candidate combined with clear section headers.

Rules:
1. Extract ALL constraints from ALL sections — pay special attention to interview transcripts which often contain compensation requirements and location preferences.
2. Deduplicate: if the same constraint appears in multiple sections, keep the highest-confidence version.
3. If sections conflict (e.g. different compensation figures), prefer interview transcript > CV > LinkedIn.
4. Skills and industries: union of all sections, deduplicated.
5. years_experience: most specific value, usually from CV.
6. interview_score and culture_fit_score: infer from the INTERVIEW TRANSCRIPT section only.
7. CRITICAL: The prompt will include a HINTS section listing figures found by automated text scan. Every figure listed there MUST appear in your constraints output — do not omit them.

{CONSTRAINT_KEY_GUIDANCE}

{FEW_SHOT_EXAMPLES}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_constraint(raw: dict, side: ConstraintSide) -> Constraint:
    return Constraint(
        id=str(uuid.uuid4())[:8],
        type=ConstraintType(raw.get("type", "soft")),
        side=side,
        category=raw.get("category", "general"),
        description=raw.get("description", ""),
        canonical_key=raw.get("canonical_key"),
        value=raw.get("value"),
        operator=ConstraintOperator(raw.get("operator", "prefers")),
        weight=float(raw.get("weight") or 1.0),
        confidence=float(raw.get("confidence") or 0.8),
        currency=raw.get("currency") or None,
    )


def _call_tool(messages: list[dict], tool_schema: dict, system: str) -> dict:
    """Call Claude with a single forced tool and return the tool input dict."""
    print(f"    [LLM] {tool_schema['name']}...", flush=True)
    response = _get_client().messages.create(
        model=LLM_MODEL,
        max_tokens=4096,
        system=system,
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("No tool use block in response")


def _build_hint_block(
    cv_text: str,
    linkedin_text: str,
    transcript_text: str,
) -> str:
    """Regex-scan all sources and return a hint block to prepend to the LLM prompt.

    Only monetary figures are detected — compensation constraints are universal
    and high-stakes across all professional domains. The LLM is responsible for
    extracting other constraint types directly from the text.
    """
    salary_hints: list[str] = []

    for label, text in [
        ("CV", cv_text),
        ("LinkedIn", linkedin_text),
        ("interview transcript", transcript_text),
    ]:
        if text:
            salary_hints.extend(_find_salary_hints(text, label))

    if not salary_hints:
        return ""

    lines = ["COMPENSATION FIGURES DETECTED BY TEXT SCAN — each MUST appear as a compensation constraint with an appropriate canonical_key:"]
    lines.extend(f"  • {h}" for h in salary_hints)
    return "\n\nHINTS (from automated text scan — do NOT omit these from constraints):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_job_description(raw_text: str, job_id: str = "", title: str = "", company: str = "") -> JobDescription:
    """Parse raw JD text into a structured JobDescription using Claude tool use."""
    messages = [
        {
            "role": "user",
            "content": f"Parse this job description into structured JSON:\n\n{raw_text}",
        }
    ]
    result = _call_tool(messages, JD_TOOL_SCHEMA, JD_SYSTEM_PROMPT)

    constraints = [
        _make_constraint(c, ConstraintSide.employer)
        for c in result.get("constraints", [])
    ]

    return JobDescription(
        id=job_id or str(uuid.uuid4())[:8],
        title=result.get("title", title),
        company=result.get("company", company),
        raw_text=raw_text,
        required_skills=result.get("required_skills", []),
        preferred_skills=result.get("preferred_skills", []),
        min_years_experience=result.get("min_years_experience", 0),
        seniority=result.get("seniority", "mid"),
        management_required=result.get("management_required", False),
        industries_preferred=result.get("industries_preferred", []),
        industries_acceptable=result.get("industries_acceptable", []),
        constraints=constraints,
    )


def parse_candidate_source(source_text: str, source_type: str) -> dict:
    """Extract structured fields from a single candidate source document.

    Args:
        source_text: Raw text of the source.
        source_type: One of "cv", "linkedin", "interview_transcript".

    Returns:
        Raw dict from the LLM (not yet a Candidate model).
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"Parse this candidate {source_type.upper()} document into structured JSON:\n\n"
                f"{source_text}"
            ),
        }
    ]
    return _call_tool(messages, CANDIDATE_SOURCE_TOOL_SCHEMA, CANDIDATE_SYSTEM_PROMPT)


def merge_candidate_sources(
    candidate_id: str,
    name: str,
    cv_text: str,
    linkedin_text: str,
    transcript_text: str,
    cv_extract: dict | None = None,
    linkedin_extract: dict | None = None,
    transcript_extract: dict | None = None,
) -> Candidate:
    """Extract from each source then merge into a single Candidate (legacy 3+1 approach).

    Prefer parse_candidate() which does single-pass extraction with regex validation.
    """
    if cv_extract is None and cv_text:
        cv_extract = parse_candidate_source(cv_text, "cv")
    if linkedin_extract is None and linkedin_text:
        linkedin_extract = parse_candidate_source(linkedin_text, "linkedin")
    if transcript_extract is None and transcript_text:
        transcript_extract = parse_candidate_source(transcript_text, "interview_transcript")

    sources_json = json.dumps(
        {
            "cv": cv_extract or {},
            "linkedin": linkedin_extract or {},
            "interview_transcript": transcript_extract or {},
        },
        indent=2,
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Merge these three extractions for candidate '{name}' into a single canonical record:\n\n"
                f"{sources_json}"
            ),
        }
    ]
    result = _call_tool(messages, MERGE_TOOL_SCHEMA, MERGE_SYSTEM_PROMPT)

    constraints = [
        _make_constraint(c, ConstraintSide.candidate)
        for c in result.get("constraints", [])
    ]

    return Candidate(
        id=candidate_id,
        name=name,
        raw_cv=cv_text,
        raw_linkedin=linkedin_text,
        raw_interview_transcript=transcript_text,
        years_experience=float(result.get("years_experience", 0)),
        skills=result.get("skills", []),
        industries=result.get("industries", []),
        seniority_level=result.get("seniority_level", "mid"),
        management_experience=result.get("management_experience", False),
        education_level=result.get("education_level", "bachelor"),
        career_trajectory=result.get("career_trajectory", "ascending"),
        interview_score=float(result.get("interview_score") or 0.5),
        culture_fit_score=float(result.get("culture_fit_score") or 0.5),
        constraints=constraints,
    )


def parse_candidate(raw: dict) -> Candidate:
    """Single-pass candidate extraction with regex pre-validation.

    Concatenates all source documents, pre-scans for salary/office figures with
    regex, and passes them as explicit hints to the LLM — so critical numeric
    constraints are never silently dropped by a merge step.
    """
    candidate_id = raw["id"]
    name = raw["name"]
    cv_text = raw.get("cv", "")
    linkedin_text = raw.get("linkedin", "")
    transcript_text = raw.get("interview_transcript", "")

    # Build regex-derived hint block (salary, office days)
    hint_block = _build_hint_block(cv_text, linkedin_text, transcript_text)

    # Concatenate all sources with clear section markers
    sections: list[str] = []
    if cv_text:
        sections.append(f"=== CV ===\n{cv_text}")
    if linkedin_text:
        sections.append(f"=== LINKEDIN ===\n{linkedin_text}")
    if transcript_text:
        sections.append(f"=== INTERVIEW TRANSCRIPT ===\n{transcript_text}")

    combined_text = "\n\n".join(sections)

    messages = [
        {
            "role": "user",
            "content": (
                f"Extract structured candidate data for '{name}' from all source documents below."
                f"{hint_block}\n\n"
                f"{combined_text}"
            ),
        }
    ]

    result = _call_tool(messages, CANDIDATE_FULL_TOOL_SCHEMA, CANDIDATE_FULL_SYSTEM_PROMPT)

    constraints = [
        _make_constraint(c, ConstraintSide.candidate)
        for c in result.get("constraints", [])
    ]

    return Candidate(
        id=candidate_id,
        name=name,
        raw_cv=cv_text,
        raw_linkedin=linkedin_text,
        raw_interview_transcript=transcript_text,
        years_experience=float(result.get("years_experience", 0)),
        skills=result.get("skills", []),
        industries=result.get("industries", []),
        seniority_level=result.get("seniority_level", "mid"),
        management_experience=result.get("management_experience", False),
        education_level=result.get("education_level", "bachelor"),
        career_trajectory=result.get("career_trajectory", "ascending"),
        interview_score=float(result.get("interview_score") or 0.5),
        culture_fit_score=float(result.get("culture_fit_score") or 0.5),
        constraints=constraints,
    )
