# AI-Powered Candidate Recommendation System
## Technical Implementation Plan

---

## 1. System Overview

A pipeline that ingests unstructured job description and candidate data, uses an LLM to extract structured features and dynamic constraints, applies a constraint engine and scoring model, and returns ranked recommendations with explanations.

```
[Unstructured Inputs]
  Job Description (text)
  Candidate: CV + LinkedIn + Interview Notes
        ↓
[Feature Extraction Layer]  ← LLM (Claude API)
  Structured feature JSON + dynamic constraint lists
        ↓
[Constraint Compatibility Engine]
  Semantic matching of employer ↔ candidate constraints
  Hard constraint failures → eliminated
  Soft constraint mismatches → score penalty
        ↓
[Scoring Model]
  Linear regression over weighted features
  Soft preference scores applied as modifiers
        ↓
[Explanation Layer]  ← LLM
  Per-candidate rationale including constraint analysis
        ↓
[Demo UI]
  Add JD → Run → Ranked results + explanations
```

---

## 2. Design Philosophy: Dynamic Constraints

The key design decision is that **constraints are not a fixed schema**. A given job might require security clearance; another might require 5-day onsite attendance; a third might mandate specific certifications. Candidates similarly carry heterogeneous constraints — visa status, compressed hours requirements, notice period, relocation willingness, and so on.

Rather than hardcoding fields, the LLM extracts constraints as a **typed, matchable list** on both sides. The constraint engine then performs compatibility matching between employer and candidate constraint lists — semantically, not by field name.

---

## 3. Data Model Design

### 3.1 Constraint Object (shared structure, used by both JD and Candidate)

```json
{
  "id": "c1",
  "type": "hard | soft",
  "side": "employer | candidate",
  "category": "location | compensation | schedule | legal | skills | culture | other",
  "description": "Natural language description as extracted from source text",
  "canonical_key": "office_days_per_week | remote_only | visa_sponsorship | salary_min | ...",
  "value": "5 | true | false | [fintech, saas] | 90000",
  "operator": "requires | prefers | excludes | min | max | one_of",
  "weight": 0.8,
  "confidence": 0.9
}
```

**`type`:** Hard constraints are binary pass/fail. Soft constraints influence score.

**`canonical_key`:** The LLM is prompted to normalise extracted constraints to a shared vocabulary where possible (e.g. both "must be in office full time" and "5 days a week in London" → `office_days_per_week: 5`). Where no canonical key exists, the raw description is preserved and semantic matching is used at runtime.

**`confidence`:** The LLM's self-reported confidence that it correctly extracted this constraint from the source text. Low-confidence constraints are flagged in the UI for human review rather than silently applied.

---

### 3.2 Job Description Schema

```json
{
  "job_id": "string",
  "raw_text": "original JD text",
  "title": "string",
  "required_skills": ["Python", "SQL"],
  "preferred_skills": ["dbt", "Spark"],
  "min_years_experience": 5,
  "seniority": "senior | mid | junior",
  "management_required": false,
  "industries_preferred": ["fintech", "saas"],
  "industries_acceptable": ["any"],
  "constraints": [
    {
      "id": "c1",
      "type": "hard",
      "side": "employer",
      "category": "location",
      "description": "Must be in office 5 days per week in London",
      "canonical_key": "office_days_per_week",
      "value": 5,
      "operator": "requires",
      "confidence": 0.97
    },
    {
      "id": "c2",
      "type": "hard",
      "side": "employer",
      "category": "legal",
      "description": "No visa sponsorship available",
      "canonical_key": "visa_sponsorship",
      "value": false,
      "operator": "requires",
      "confidence": 0.95
    },
    {
      "id": "c3",
      "type": "soft",
      "side": "employer",
      "category": "culture",
      "description": "Preference for candidates with fintech or regulated industry background",
      "canonical_key": "industry_preference",
      "value": ["fintech", "insurance", "banking"],
      "operator": "prefers",
      "weight": 0.7,
      "confidence": 0.88
    }
  ]
}
```

---

### 3.3 Candidate Schema

```json
{
  "candidate_id": "string",
  "name": "string",
  "raw_sources": {
    "cv": "...",
    "linkedin": "...",
    "interview_notes": "..."
  },
  "years_experience": 7,
  "skills": ["Python", "SQL", "dbt"],
  "industries": ["fintech", "ecommerce"],
  "seniority_level": "senior",
  "management_experience": true,
  "education_level": "BSc | MSc | PhD",
  "career_trajectory": "ascending | lateral | mixed",
  "interview_score": 0.82,
  "culture_fit_score": 0.75,
  "constraints": [
    {
      "id": "c1",
      "type": "hard",
      "side": "candidate",
      "category": "location",
      "description": "Only willing to consider remote or hybrid roles",
      "canonical_key": "office_days_per_week",
      "value": 2,
      "operator": "max",
      "confidence": 0.91
    },
    {
      "id": "c2",
      "type": "hard",
      "side": "candidate",
      "category": "compensation",
      "description": "Minimum salary expectation of £90,000",
      "canonical_key": "salary_min",
      "value": 90000,
      "operator": "min",
      "confidence": 0.99
    },
    {
      "id": "c3",
      "type": "soft",
      "side": "candidate",
      "category": "schedule",
      "description": "Prefers 4-day working week but not a dealbreaker",
      "canonical_key": "four_day_week",
      "value": true,
      "operator": "prefers",
      "weight": 0.5,
      "confidence": 0.80
    }
  ]
}
```

---

## 4. Feature Extraction Layer (LLM)

### 4.1 Pipeline

```
parse_job_description(raw_text)       → JDSchema (features + constraints)
parse_candidate(cv, linkedin, notes)  → CandidateSchema (features + constraints)
```

These are separate LLM calls to keep prompts focused and outputs reliable.

### 4.2 Prompting Strategy

- System prompt defines the full output schema as JSON with field descriptions
- Instruct the model to extract constraints exhaustively — if something *could* be a constraint (hard or soft), extract it
- Prompt the model to normalise to canonical keys where a reasonable mapping exists, and flag uncertainty via `confidence`
- Include few-shot examples covering: explicit constraints ("must be UK citizen"), implicit constraints ("fast-paced startup environment" → culture/pace soft constraint), and missing data ("salary not mentioned" → no salary constraint extracted, do not infer)
- Separate extraction call per candidate source (CV, LinkedIn, notes), then a merge call to reconcile and deduplicate

### 4.3 Confidence Handling

| Confidence | Behaviour |
|---|---|
| ≥ 0.85 | Applied automatically |
| 0.60 – 0.84 | Applied but flagged in UI for human review |
| < 0.60 | Excluded from engine; surfaced as "uncertain extraction" in UI |

---

## 5. Constraint Compatibility Engine

This runs **before** scoring and is the most novel part of the system.

### 5.1 Matching Approach

Employer and candidate constraints are matched against each other using a combination of:

1. **Canonical key matching** — if both sides share the same `canonical_key`, apply operator logic directly
2. **Semantic matching** — if no canonical key match exists, use embedding similarity (or a second LLM call) to determine whether two constraints are addressing the same dimension
3. **No match** — if an employer constraint has no candidate-side counterpart, it is treated as unconstrained on the candidate side (i.e. no penalty or failure)

### 5.2 Compatibility Rules

```python
def check_compatibility(employer_constraint, candidate_constraint):
    # Hard × Hard: both sides have hard constraints — must be compatible
    # Hard × Soft: employer hard constraint takes precedence
    # Soft × Soft: compute partial compatibility score (0.0 – 1.0)
    # Hard × None: employer hard constraint is unmatched — treat as met (candidate
    #              has not expressed a conflicting preference)
```

**Example compatibility checks by operator pair:**

| Employer | Candidate | Outcome |
|---|---|---|
| `office_days_per_week requires 5` | `office_days_per_week max 2` | Hard fail — eliminated |
| `office_days_per_week requires 3` | `office_days_per_week max 3` | Compatible — pass |
| `salary_max 100000` | `salary_min 90000` | Compatible — pass |
| `salary_max 85000` | `salary_min 90000` | Hard fail — eliminated |
| `industry_preference prefers fintech` | candidate has fintech background | Soft match — score boost |
| `four_day_week not offered` | `four_day_week prefers` | Soft mismatch — score penalty |
| `security_clearance required` | no clearance constraint extracted | Unknown — flagged for human review |

### 5.3 Output

```json
{
  "candidate_id": "...",
  "eliminated": false,
  "elimination_reasons": [],
  "constraint_matches": [
    {
      "employer_constraint_id": "c1",
      "candidate_constraint_id": "c1",
      "match_type": "canonical_key",
      "compatible": false,
      "score": 0.0,
      "explanation": "Candidate requires max 2 office days; role requires 5"
    },
    {
      "employer_constraint_id": "c3",
      "candidate_constraint_id": null,
      "match_type": "no_candidate_constraint",
      "compatible": true,
      "score": 1.0,
      "explanation": "Candidate has not expressed a conflicting preference"
    }
  ],
  "unmatched_candidate_constraints": ["c3"],
  "flagged_for_review": ["security_clearance"]
}
```

---

## 6. Scoring Model

### 6.1 Feature Vector

For each (JD, Candidate) pair that passes the constraint engine:

```python
features = {
    # Skills
    "required_skills_overlap":    jaccard(candidate.skills, job.required_skills),
    "preferred_skills_overlap":   jaccard(candidate.skills, job.preferred_skills),

    # Industry fit
    "industry_preferred_match":   1.0 if overlap(candidate.industries, job.industries_preferred) else 0.0,

    # Experience
    "experience_delta":           clip(candidate.years_experience - job.min_years_experience, 0, 5) / 5,
    "seniority_match":            1.0 if candidate.seniority == job.seniority else 0.5,

    # Soft signals
    "career_trajectory_score":    {"ascending": 1.0, "lateral": 0.6, "mixed": 0.4}[candidate.career_trajectory],
    "interview_score":            candidate.interview_score,
    "culture_fit_score":          candidate.culture_fit_score,

    # Management fit
    "management_match":           1.0 if job.management_required == candidate.management_experience else 0.3,

    # Constraint soft match aggregate
    "soft_constraint_score":      mean([m.score for m in constraint_matches if m.match_type != "hard_fail"]),
}
```

### 6.2 Weights

For the initial demo, weights are manually calibrated. These can later be learned from recruiter feedback using standard linear regression (accepted/rejected hires as labels).

```python
weights = {
    "required_skills_overlap":    0.28,
    "preferred_skills_overlap":   0.10,
    "industry_preferred_match":   0.12,
    "experience_delta":           0.10,
    "seniority_match":            0.08,
    "career_trajectory_score":    0.07,
    "interview_score":            0.10,
    "culture_fit_score":          0.05,
    "management_match":           0.04,
    "soft_constraint_score":      0.06,
}

score = sum(features[k] * weights[k] for k in weights)  # → 0.0 to 1.0
```

> **Path to learned weights:** Once real hiring outcomes are available (hired = 1, rejected = 0), treat each scored (JD, Candidate) pair as a training row and fit a proper linear regression model. The manually calibrated weights serve as a warm-start prior.

---

## 7. Explanation Layer

Post-scoring, the top N candidates are passed back to the LLM with their feature breakdown and constraint match results to generate human-readable rationale.

**Example output:**

> **Alex Chen — Score: 0.87**
>
> Strong match on required technical skills (Python, SQL, dbt — 100% overlap). Seven years of experience comfortably exceeds the five-year minimum. Background in fintech aligns directly with the employer's industry preference. Interview score of 0.82 is above threshold.
>
> **Constraint analysis:** No hard constraint conflicts. One soft mismatch: Alex prefers a four-day working week, which this role does not offer — minor negative signal. Salary expectation (£92k) is within the stated range.
>
> **Flag for review:** Security clearance requirement could not be confirmed from available candidate documents.

---

## 8. Dummy Data

Generate three jobs and 20 candidates designed to exercise the full system:

**Jobs:**
- Fintech data engineer — 5-day onsite London, no visa sponsorship, no management required
- Remote SaaS product manager — fully remote, visa sponsorship available, strong preference for B2B SaaS background
- Hybrid ML engineer — 2 days onsite, compressed hours available, security clearance preferred

**Candidates (mix across):**
- Strong match on all dimensions (2–3 per job)
- Strong skills match, hard constraint conflict — eliminated (e.g. remote-only candidate for onsite role)
- Weak skills match, good soft signals — ranked low
- Good overall fit, one low-confidence constraint flagged for review
- Salary expectation above job max — eliminated
- Unusual constraints not seen before — exercises semantic matching (e.g. "only works with B-corps", "requires sponsorship renewal within 12 months")

---

## 9. Demo UI

A single-page app (Streamlit or React) with:

1. **Job input panel** — paste raw JD text or select a preloaded scenario
2. **Run pipeline button** — triggers extraction → constraint engine → scoring → explanation
3. **Results panel:**
   - Eliminated candidates with reasons clearly shown
   - Ranked candidates with score bar, feature breakdown, and LLM explanation
   - Constraint match detail expandable per candidate
   - Flags for constraints requiring human review
4. **Weight tuner** — live sliders to adjust feature weights and re-rank without re-running LLM calls

---

## 10. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Feature + constraint extraction | Claude API (Sonnet) | Best structured output; self-reported confidence natively |
| Semantic constraint matching | Embeddings (OpenAI or local) or second LLM call | Handles novel constraints with no canonical key |
| Scoring | Python / NumPy | Simple, inspectable, easy to swap to sklearn |
| Dummy data generation | Claude-generated JSON | Fast to iterate and cover edge cases |
| UI | Streamlit | Quickest demo turnaround |
| Backend | FastAPI | Clean separation, easy to extend |
| Storage | SQLite or in-memory dict | No infra overhead for demo |

---

## 11. Build Order

1. **Define schemas** — finalise JD, candidate, and constraint object models
2. **Generate dummy data** — 3 JDs, 20 candidates with deliberate constraint variety
3. **Build extraction prompts** — parse raw text → structured JSON with constraint lists
4. **Build constraint compatibility engine** — canonical key matching, then semantic fallback
5. **Build scoring** — feature vector + weighted sum including soft constraint aggregate
6. **Build explanation prompts** — per-candidate rationale with constraint detail
7. **Wire up UI** — Streamlit or React frontend with weight tuner
8. **Demo polish** — preload scenarios, surface review flags, add elimination detail panel

---

## 12. Key Design Decisions & Open Questions

| Decision | Current approach | Alternative |
|---|---|---|
| Constraint extraction granularity | Extract all possible constraints, prune low-confidence ones | Extract only explicit constraints — lower recall but more precise |
| Semantic constraint matching | Embedding similarity | Second LLM call — more reliable but slower and costlier |
| Missing candidate constraint | Treat as compatible (no expressed conflict) | Treat as unknown, flag for review — more conservative |
| Learned weights | Manual for demo; linear regression once labelled data exists | Start with a recruiter preference survey to seed weights |
| Multi-job matching | Single job → candidate ranking | Extend to candidate → best-fit job recommendations |
