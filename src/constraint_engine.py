"""Constraint compatibility engine.

Matches employer constraints against candidate constraints via:
1. Canonical key lookup (deterministic, fast)
2. Embedding-based semantic similarity fallback (OpenAI text-embedding-3-small)
3. No-match fallback (treat as compatible when employer has no candidate counterpart)
"""
from __future__ import annotations

import os
import uuid
from typing import Sequence

import numpy as np

from .models import (
    Candidate,
    CompatibilityResult,
    Constraint,
    ConstraintMatch,
    ConstraintOperator,
    ConstraintType,
    JobDescription,
    MatchType,
)

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _openai_client

EMBEDDING_MODEL = "text-embedding-3-small"
SEMANTIC_THRESHOLD = 0.75  # cosine similarity required for a semantic match
AMBIGUOUS_BAND_LOW = 0.55  # below this: no semantic match

# Clearance-type canonical keys that should be flagged for review when
# an employer requires them but the candidate has no counterpart constraint.
CLEARANCE_KEYS = {"security_clearance"}
SALARY_CANONICAL_KEYS = {"salary_min", "salary_max"}


# ---------------------------------------------------------------------------
# Operator pair logic
# ---------------------------------------------------------------------------
def _evaluate_operator_pair(
    employer: Constraint,
    candidate: Constraint,
) -> tuple[bool, float]:
    """Return (compatible, score) for a matched employer/candidate pair.

    Score 1.0 = perfect match, 0.0 = hard incompatibility.
    """
    emp_op = employer.operator
    can_op = candidate.operator
    emp_val = employer.value
    can_val = candidate.value

    # Both require the same thing — compatible
    if emp_op == ConstraintOperator.requires and can_op == ConstraintOperator.requires:
        compatible = _values_equal(emp_val, can_val)
        return compatible, 1.0 if compatible else 0.0

    # Employer requires X, candidate has max Y
    if emp_op == ConstraintOperator.requires and can_op == ConstraintOperator.max:
        try:
            compatible = float(emp_val) <= float(can_val)
        except (TypeError, ValueError):
            compatible = _values_equal(emp_val, can_val)
        return compatible, 1.0 if compatible else 0.0

    # Employer sets max X, candidate wants min Y
    if emp_op == ConstraintOperator.max and can_op == ConstraintOperator.min:
        try:
            compatible = float(can_val) <= float(emp_val)
        except (TypeError, ValueError):
            compatible = True  # can't compare non-numerics, treat as compatible
        return compatible, 1.0 if compatible else 0.0

    # Employer sets max X, candidate requires Y
    if emp_op == ConstraintOperator.max and can_op == ConstraintOperator.requires:
        try:
            compatible = float(can_val) <= float(emp_val)
        except (TypeError, ValueError):
            compatible = True
        return compatible, 1.0 if compatible else 0.0

    # Employer min X, candidate max Y
    if emp_op == ConstraintOperator.min and can_op == ConstraintOperator.max:
        try:
            compatible = float(can_val) >= float(emp_val)
        except (TypeError, ValueError):
            compatible = True
        return compatible, 1.0 if compatible else 0.0

    # Employer requires X, candidate has min Y — compatible if X >= Y
    if emp_op == ConstraintOperator.requires and can_op == ConstraintOperator.min:
        try:
            compatible = float(emp_val) >= float(can_val)
        except (TypeError, ValueError):
            compatible = _values_equal(emp_val, can_val)
        return compatible, 1.0 if compatible else 0.0

    # Employer min X, candidate requires Y — compatible if Y >= X
    if emp_op == ConstraintOperator.min and can_op == ConstraintOperator.requires:
        try:
            compatible = float(can_val) >= float(emp_val)
        except (TypeError, ValueError):
            compatible = _values_equal(emp_val, can_val)
        return compatible, 1.0 if compatible else 0.0

    # Both want a minimum — no conflict (they both want "at least")
    if emp_op == ConstraintOperator.min and can_op == ConstraintOperator.min:
        return True, 1.0

    # Both set a maximum — no conflict (tighter bound naturally applies)
    if emp_op == ConstraintOperator.max and can_op == ConstraintOperator.max:
        return True, 1.0

    # Employer prefers — soft penalty if candidate has conflicting hard constraint
    if emp_op == ConstraintOperator.prefers:
        if can_op == ConstraintOperator.excludes:
            return True, 0.0  # soft mismatch — not eliminated
        if can_op in (ConstraintOperator.requires, ConstraintOperator.max, ConstraintOperator.min):
            try:
                compatible = float(emp_val) <= float(can_val) if can_op == ConstraintOperator.min else float(emp_val) >= float(can_val)
                return True, 1.0 if compatible else 0.4
            except (TypeError, ValueError):
                pass
        return True, 1.0 if _values_equal(emp_val, can_val) else 0.6

    # Candidate prefers — soft penalty if employer requires something else
    if can_op == ConstraintOperator.prefers:
        if emp_op in (ConstraintOperator.requires, ConstraintOperator.excludes):
            match = _values_equal(emp_val, can_val)
            return True, 1.0 if match else 0.6
        return True, 0.9  # mild mismatch

    # Employer excludes — fail if candidate requires this value
    if emp_op == ConstraintOperator.excludes:
        if can_op == ConstraintOperator.requires:
            return False, 0.0
        return True, 0.7

    # Candidate excludes — fail only if employer requires the excluded value
    if can_op == ConstraintOperator.excludes:
        if emp_op == ConstraintOperator.requires:
            # Compatible if the employer's required value matches what candidate excludes
            # e.g. candidate excludes visa=True + employer requires visa=False → compatible
            try:
                if str(emp_val).lower() != str(can_val).lower():
                    return True, 1.0  # employer requires something different from what's excluded
            except Exception:
                pass
            return False, 0.0
        return True, 0.7

    # Employer one_of — check if candidate value is in the list
    if emp_op == ConstraintOperator.one_of:
        if isinstance(emp_val, list) and can_val in emp_val:
            return True, 1.0
        if isinstance(emp_val, list):
            return False, 0.0
        return True, 0.7

    # Fallback: treat as compatible with moderate score
    return True, 0.8


def _values_equal(a: object, b: object) -> bool:
    """Case-insensitive equality for strings; strict equality otherwise."""
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    try:
        return float(a) == float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return a == b


# ---------------------------------------------------------------------------
# Canonical key matching
# ---------------------------------------------------------------------------
def canonical_key_match(
    employer_c: Constraint,
    candidate_c: Constraint,
) -> ConstraintMatch | None:
    """Attempt a canonical key match.

    Returns a ConstraintMatch if both constraints share a canonical_key,
    or None if they don't share a key.
    """
    if not employer_c.canonical_key or not candidate_c.canonical_key:
        return None

    # Cross-key salary pairs: employer salary_max vs candidate salary_min
    SALARY_CROSS_PAIRS = {("salary_max", "salary_min"), ("salary_min", "salary_max")}
    key_pair = (employer_c.canonical_key, candidate_c.canonical_key)
    if key_pair not in SALARY_CROSS_PAIRS and employer_c.canonical_key != candidate_c.canonical_key:
        return None

    compatible, score = _evaluate_operator_pair(employer_c, candidate_c)

    # Flag salary constraints where currencies differ — numeric comparison is meaningless
    # across currencies (e.g. £85k vs $85k are not equivalent). Require human review.
    currency_mismatch = (
        employer_c.canonical_key in SALARY_CANONICAL_KEYS
        and employer_c.currency is not None
        and candidate_c.currency is not None
        and employer_c.currency.upper() != candidate_c.currency.upper()
    )

    emp_val_str = f"{employer_c.value}{' ' + employer_c.currency if employer_c.currency else ''}"
    can_val_str = f"{candidate_c.value}{' ' + candidate_c.currency if candidate_c.currency else ''}"
    reason = (
        f"Canonical key match on '{employer_c.canonical_key}': "
        f"employer {employer_c.operator.value} {emp_val_str} vs "
        f"candidate {candidate_c.operator.value} {can_val_str}"
    )
    if currency_mismatch:
        reason += " [⚠ currency mismatch — manual FX conversion required]"

    return ConstraintMatch(
        employer_constraint_id=employer_c.id,
        candidate_constraint_id=candidate_c.id,
        match_type=MatchType.canonical_key,
        compatible=compatible,
        score=score,
        reason=reason,
        flagged_for_review=(
            currency_mismatch
            or (candidate_c.confidence < 0.85)
            or (employer_c.confidence < 0.85)
        ),
    )


# ---------------------------------------------------------------------------
# Semantic (embedding) matching
# ---------------------------------------------------------------------------
def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def _batch_embed(texts: list[str]) -> list[np.ndarray]:
    """Embed a list of strings with a single OpenAI API call."""
    if not texts:
        return []
    response = _get_openai_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [np.array(item.embedding, dtype=np.float32) for item in response.data]


def semantic_match(
    employer_constraints: list[Constraint],
    candidate_constraints: list[Constraint],
    unmatched_employer_ids: set[str],
    unmatched_candidate_ids: set[str],
) -> list[ConstraintMatch]:
    """Batch-encode unmatched constraint descriptions and compute cosine similarity.

    Returns ConstraintMatch objects for pairs that exceed SEMANTIC_THRESHOLD.
    """
    emp_unmatched = [c for c in employer_constraints if c.id in unmatched_employer_ids]
    can_unmatched = [c for c in candidate_constraints if c.id in unmatched_candidate_ids]

    if not emp_unmatched or not can_unmatched:
        return []

    emp_texts = [c.description for c in emp_unmatched]
    can_texts = [c.description for c in can_unmatched]

    all_texts = emp_texts + can_texts
    all_embeddings = _batch_embed(all_texts)
    emp_embeddings = all_embeddings[: len(emp_texts)]
    can_embeddings = all_embeddings[len(emp_texts):]

    matches: list[ConstraintMatch] = []
    matched_can_ids: set[str] = set()

    # Greedy: for each employer constraint, find best candidate match
    for i, emp_c in enumerate(emp_unmatched):
        best_score = 0.0
        best_j = -1
        for j, can_c in enumerate(can_unmatched):
            if can_c.id in matched_can_ids:
                continue
            sim = _cosine_similarity(emp_embeddings[i], can_embeddings[j])
            if sim > best_score:
                best_score = sim
                best_j = j

        if best_j >= 0 and best_score >= SEMANTIC_THRESHOLD:
            can_c = can_unmatched[best_j]
            compatible, score = _evaluate_operator_pair(emp_c, can_c)
            matches.append(
                ConstraintMatch(
                    employer_constraint_id=emp_c.id,
                    candidate_constraint_id=can_c.id,
                    match_type=MatchType.semantic,
                    compatible=compatible,
                    score=score,
                    reason=(
                        f"Semantic match (similarity={best_score:.2f}) between "
                        f"'{emp_c.description}' and '{can_c.description}'"
                    ),
                    flagged_for_review=(
                        (can_c.confidence < 0.85)
                        or (emp_c.confidence < 0.85)
                        or (AMBIGUOUS_BAND_LOW < best_score < SEMANTIC_THRESHOLD)
                    ),
                )
            )
            matched_can_ids.add(can_c.id)

    return matches


# ---------------------------------------------------------------------------
# check_compatibility — route through canonical → semantic → no-match
# ---------------------------------------------------------------------------
def check_compatibility(
    employer_c: Constraint,
    candidate_constraints: list[Constraint],
    candidate_embeddings: list[np.ndarray] | None = None,
    candidate_texts: list[str] | None = None,
) -> ConstraintMatch:
    """Check a single employer constraint against the full candidate constraint list.

    Routing:
    1. Canonical key match (exact string equality on canonical_key)
    2. Semantic embedding match (if candidate_embeddings provided)
    3. No candidate constraint found → treat as compatible
    """
    # 1. Canonical key
    for can_c in candidate_constraints:
        result = canonical_key_match(employer_c, can_c)
        if result is not None:
            return result

    # 2. Semantic (if embeddings available)
    if candidate_embeddings and candidate_texts:
        emp_emb = _batch_embed([employer_c.description])[0]
        best_score = 0.0
        best_idx = -1
        for idx, can_emb in enumerate(candidate_embeddings):
            sim = _cosine_similarity(emp_emb, can_emb)
            if sim > best_score:
                best_score = sim
                best_idx = idx

        if best_idx >= 0 and best_score >= SEMANTIC_THRESHOLD:
            can_c = candidate_constraints[best_idx]
            compatible, score = _evaluate_operator_pair(employer_c, can_c)
            return ConstraintMatch(
                employer_constraint_id=employer_c.id,
                candidate_constraint_id=can_c.id,
                match_type=MatchType.semantic,
                compatible=compatible,
                score=score,
                reason=(
                    f"Semantic match (sim={best_score:.2f}): "
                    f"'{employer_c.description}' ~ '{can_c.description}'"
                ),
                flagged_for_review=(
                    (can_c.confidence < 0.85) or best_score < 0.85
                ),
            )

    # 3. No match — compatible (candidate hasn't expressed a conflicting preference)
    flagged = employer_c.canonical_key in CLEARANCE_KEYS and employer_c.type == ConstraintType.hard
    return ConstraintMatch(
        employer_constraint_id=employer_c.id,
        candidate_constraint_id=None,
        match_type=MatchType.no_candidate_constraint,
        compatible=True,
        score=1.0,
        reason="No candidate constraint found for this employer constraint",
        flagged_for_review=flagged,
    )


# ---------------------------------------------------------------------------
# run_constraint_engine — full engine over a job + candidate pair
# ---------------------------------------------------------------------------
def run_constraint_engine(
    job: JobDescription,
    candidate: Candidate,
) -> CompatibilityResult:
    """Run the full constraint engine for a (job, candidate) pair.

    Three-phase matching:
    1. Canonical key matching (deterministic, no API calls)
    2. Batch-embed all unmatched employer constraints at once → semantic matching
    3. No-match fallback for remaining unmatched employer constraints

    Returns a CompatibilityResult indicating whether the candidate is eliminated
    and the full set of per-constraint match results.
    """
    emp_constraints = job.constraints
    can_constraints = candidate.constraints

    # Pre-compute candidate embeddings for semantic fallback (one batch call)
    can_embeddings: list[np.ndarray] = []
    if can_constraints:
        try:
            can_embeddings = _batch_embed([c.description for c in can_constraints])
        except Exception:
            can_embeddings = []

    unmatched_candidate_ids: set[str] = {c.id for c in can_constraints}
    matched_candidate_ids: set[str] = set()

    # Phase 1: canonical key matching
    canonical_results: dict[str, ConstraintMatch] = {}
    unmatched_emp_ids: set[str] = set()

    for emp_c in emp_constraints:
        found = False
        for can_c in can_constraints:
            m = canonical_key_match(emp_c, can_c)
            if m is not None:
                canonical_results[emp_c.id] = m
                if m.candidate_constraint_id:
                    matched_candidate_ids.add(m.candidate_constraint_id)
                found = True
                break
        if not found:
            unmatched_emp_ids.add(emp_c.id)

    # Phase 2: batch-embed all unmatched employer constraints, then semantic match
    semantic_results: dict[str, ConstraintMatch] = {}
    if unmatched_emp_ids and can_embeddings:
        emp_unmatched = [c for c in emp_constraints if c.id in unmatched_emp_ids]
        try:
            emp_embeddings = _batch_embed([c.description for c in emp_unmatched])
            for i, emp_c in enumerate(emp_unmatched):
                best_score = 0.0
                best_j = -1
                for j, can_c in enumerate(can_constraints):
                    if can_c.id in matched_candidate_ids:
                        continue
                    sim = _cosine_similarity(emp_embeddings[i], can_embeddings[j])
                    if sim > best_score:
                        best_score = sim
                        best_j = j

                if best_j >= 0 and best_score >= SEMANTIC_THRESHOLD:
                    can_c = can_constraints[best_j]
                    compatible, score = _evaluate_operator_pair(emp_c, can_c)
                    semantic_results[emp_c.id] = ConstraintMatch(
                        employer_constraint_id=emp_c.id,
                        candidate_constraint_id=can_c.id,
                        match_type=MatchType.semantic,
                        compatible=compatible,
                        score=score,
                        reason=(
                            f"Semantic match (similarity={best_score:.2f}) between "
                            f"'{emp_c.description}' and '{can_c.description}'"
                        ),
                        flagged_for_review=(
                            (can_c.confidence < 0.85)
                            or (emp_c.confidence < 0.85)
                            or (AMBIGUOUS_BAND_LOW < best_score < SEMANTIC_THRESHOLD)
                        ),
                    )
                    matched_candidate_ids.add(can_c.id)
        except Exception:
            pass  # Fall through to no-match for unmatched constraints

    # Phase 3: assemble final match list (canonical → semantic → no-match fallback)
    constraint_matches: list[ConstraintMatch] = []
    elimination_reasons: list[str] = []
    flagged_for_review: list[str] = []

    for emp_c in emp_constraints:
        if emp_c.id in canonical_results:
            match = canonical_results[emp_c.id]
        elif emp_c.id in semantic_results:
            match = semantic_results[emp_c.id]
        else:
            flagged = emp_c.canonical_key in CLEARANCE_KEYS and emp_c.type == ConstraintType.hard
            match = ConstraintMatch(
                employer_constraint_id=emp_c.id,
                candidate_constraint_id=None,
                match_type=MatchType.no_candidate_constraint,
                compatible=True,
                score=1.0,
                reason="No candidate constraint found for this employer constraint",
                flagged_for_review=flagged,
            )

        constraint_matches.append(match)

        if match.candidate_constraint_id:
            unmatched_candidate_ids.discard(match.candidate_constraint_id)

        if not match.compatible and emp_c.type == ConstraintType.hard:
            elimination_reasons.append(
                f"Hard constraint failure on '{emp_c.canonical_key or emp_c.description}': "
                f"{match.reason}"
            )

        if match.flagged_for_review:
            flagged_for_review.append(emp_c.id)

    return CompatibilityResult(
        candidate_id=candidate.id,
        eliminated=len(elimination_reasons) > 0,
        elimination_reasons=elimination_reasons,
        constraint_matches=constraint_matches,
        unmatched_candidate_constraints=list(unmatched_candidate_ids),
        flagged_for_review=flagged_for_review,
    )
