## ADDED Requirements

### Requirement: Compute a feature vector for each non-eliminated candidate
The system SHALL compute a feature vector of 10 named float values (each in 0.0–1.0) for every candidate that passes the constraint engine, using the candidate's structured data and the job's structured data.

Features:
- `required_skills_overlap`: Jaccard similarity between candidate skills and job required skills
- `preferred_skills_overlap`: Jaccard similarity between candidate skills and job preferred skills
- `industry_preferred_match`: 1.0 if candidate industries overlap with job preferred industries, else 0.0
- `experience_delta`: clip((candidate.years_experience - job.min_years_experience), 0, 5) / 5
- `seniority_match`: 1.0 if levels match, else 0.5
- `career_trajectory_score`: ascending=1.0, lateral=0.6, mixed=0.4
- `interview_score`: raw interview score from candidate schema (0.0–1.0)
- `culture_fit_score`: raw culture fit score from candidate schema (0.0–1.0)
- `management_match`: 1.0 if job.management_required == candidate.management_experience, else 0.3
- `soft_constraint_score`: mean of soft constraint match scores from the constraint engine

#### Scenario: Candidate with perfect skill overlap
- **WHEN** the candidate's skills exactly match all required and preferred skills
- **THEN** `required_skills_overlap: 1.0` and `preferred_skills_overlap: 1.0`

#### Scenario: Candidate with more experience than required
- **WHEN** the candidate has 10 years experience and the role requires 5
- **THEN** `experience_delta: 1.0` (capped at the 5-year surplus ceiling)

#### Scenario: Candidate with insufficient experience
- **WHEN** the candidate has 3 years experience and the role requires 5
- **THEN** `experience_delta: 0.0` (clamped at zero, not negative)

---

### Requirement: Score candidates via weighted linear sum
The system SHALL compute `score = Σ(feature_i × weight_i)` using the 10 features and their configured weights. The resulting score SHALL be in the range 0.0–1.0.

Default weights:
- `required_skills_overlap`: 0.28
- `preferred_skills_overlap`: 0.10
- `industry_preferred_match`: 0.12
- `experience_delta`: 0.10
- `seniority_match`: 0.08
- `career_trajectory_score`: 0.07
- `interview_score`: 0.10
- `culture_fit_score`: 0.05
- `management_match`: 0.04
- `soft_constraint_score`: 0.06

#### Scenario: All features at maximum
- **WHEN** all 10 feature values are 1.0 and default weights are used
- **THEN** the score equals 1.0 (weights sum to 1.0)

#### Scenario: Candidate with zero required skill overlap
- **WHEN** `required_skills_overlap: 0.0`
- **THEN** the score is reduced by 0.28 relative to a perfect-match candidate

---

### Requirement: Rank non-eliminated candidates by score descending
The system SHALL return candidates sorted by score descending. Eliminated candidates SHALL appear in a separate list with their elimination reasons and SHALL NOT appear in the ranked list.

#### Scenario: Mixed pool of candidates
- **WHEN** a job has 20 candidates, 5 of whom are eliminated
- **THEN** the response contains a ranked list of 15 candidates sorted by score and a separate list of 5 eliminated candidates with reasons

---

### Requirement: Support live weight reconfiguration without re-running LLM calls
The system SHALL accept a custom weight vector and recompute scores using cached feature vectors. LLM extraction and constraint matching SHALL NOT be re-invoked when weights change.

#### Scenario: Weight slider adjusted in UI
- **WHEN** the recruiter adjusts the `required_skills_overlap` weight slider
- **THEN** all candidate scores are recomputed instantly from cached feature vectors and the ranked list updates
