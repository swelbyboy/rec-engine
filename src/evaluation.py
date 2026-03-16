"""Evaluation utilities — measures ranking quality against hand-labelled ground truth.

Usage:
    from src.evaluation import kendall_tau, ndcg_at_k, evaluate_ranking

All functions are pure (no I/O, no API calls) so they can be tested offline.
"""
from __future__ import annotations

import math


def kendall_tau(ranked_ids: list[str], ground_truth_ids: list[str]) -> float:
    """Kendall's tau-b: agreement between two ranked candidate lists.

    Only candidates present in BOTH lists are evaluated. Returns a value in
    [-1.0, +1.0] where +1.0 = perfect agreement, -1.0 = perfect reversal.

    Tau is useful for showing whether the system's ordering agrees with expert
    judgement without needing probability scores — interpretable to non-ML users.

    Example:
        kendall_tau(["A","B","C"], ["A","B","C"])  → 1.0  (perfect)
        kendall_tau(["A","B","C"], ["C","B","A"])  → -1.0 (perfect reversal)
        kendall_tau(["A","B","C"], ["A","C","B"])  → 0.33 (one swap)
    """
    common = [cid for cid in ground_truth_ids if cid in set(ranked_ids)]
    n = len(common)
    if n < 2:
        return 1.0  # trivially agree when fewer than 2 overlap items

    rank_pred = {cid: i for i, cid in enumerate(ranked_ids)}
    rank_true = {cid: i for i, cid in enumerate(ground_truth_ids)}

    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = common[i], common[j]
            # ground truth says a is ranked before b (rank_true[a] < rank_true[b])
            gt_sign = rank_true[a] - rank_true[b]
            pred_sign = rank_pred[a] - rank_pred[b]
            if gt_sign * pred_sign > 0:
                concordant += 1
            elif gt_sign * pred_sign < 0:
                discordant += 1
            # ties: neither concordant nor discordant

    pairs = n * (n - 1) / 2
    return round((concordant - discordant) / pairs, 4) if pairs > 0 else 1.0


def ndcg_at_k(ranked_ids: list[str], ground_truth_ids: list[str], k: int = 5) -> float:
    """Normalised Discounted Cumulative Gain at k (binary relevance).

    A candidate is relevant (rel=1) if it appears anywhere in ground_truth_ids.
    Returns 1.0 for a perfect top-k match, lower when relevant candidates are
    pushed down the list (penalty grows logarithmically with position).

    Penalises errors at the top of the list more heavily than errors lower down —
    which matches real recruiter behaviour (they read from the top).
    """
    if not ground_truth_ids:
        return 1.0

    gt_set = set(ground_truth_ids)
    k = min(k, len(ranked_ids))

    def _dcg(order: list[str], k_: int) -> float:
        return sum(
            (1.0 if cid in gt_set else 0.0) / math.log2(i + 2)
            for i, cid in enumerate(order[:k_])
        )

    # Ideal: all relevant candidates at the top, then irrelevant
    ideal = list(ground_truth_ids) + [c for c in ranked_ids if c not in gt_set]
    idcg = _dcg(ideal, k)
    return round(_dcg(ranked_ids, k) / idcg, 4) if idcg > 0 else 1.0


def evaluate_ranking(
    predicted_ranked: list[str],
    predicted_eliminated: list[str],
    ground_truth_ranked: list[str],
    ground_truth_eliminated: list[str],
) -> dict:
    """Compare pipeline output against ground truth and return evaluation metrics.

    Args:
        predicted_ranked: Candidate IDs in the pipeline's ranked order.
        predicted_eliminated: Candidate IDs the pipeline eliminated.
        ground_truth_ranked: Expected ranked IDs (expert-labelled, ordered).
        ground_truth_eliminated: Expected eliminated IDs (expert-labelled).

    Returns dict with:
        kendall_tau            — [-1,+1] ranking agreement across common candidates
        ndcg_at_5              — [0,1] top-5 position quality (penalises top errors)
        elimination_precision  — fraction of pipeline eliminations that were correct
        elimination_recall     — fraction of expected eliminations that were caught
        elimination_f1         — harmonic mean of precision and recall
        ranking_comparison     — per-candidate expected vs actual rank, with delta
        false_positives        — incorrectly eliminated (should have been ranked)
        false_negatives        — missed eliminations (should have been eliminated)
    """
    tau = kendall_tau(predicted_ranked, ground_truth_ranked)
    ndcg = ndcg_at_k(predicted_ranked, ground_truth_ranked, k=5)

    # Elimination classification
    pred_elim_set = set(predicted_eliminated)
    gt_elim_set = set(ground_truth_eliminated)

    tp = pred_elim_set & gt_elim_set       # correctly eliminated
    fp = pred_elim_set - gt_elim_set       # eliminated but shouldn't be
    fn = gt_elim_set - pred_elim_set       # should be eliminated but wasn't

    precision = len(tp) / len(pred_elim_set) if pred_elim_set else 1.0
    recall = len(tp) / len(gt_elim_set) if gt_elim_set else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )

    # Per-candidate rank comparison (expected vs actual)
    pred_rank = {cid: i + 1 for i, cid in enumerate(predicted_ranked)}
    gt_rank = {cid: i + 1 for i, cid in enumerate(ground_truth_ranked)}

    all_ranked_ids = list(dict.fromkeys(ground_truth_ranked + predicted_ranked))
    ranking_comparison = []
    for cid in all_ranked_ids:
        in_pred = cid in pred_rank
        in_gt = cid in gt_rank
        delta = (pred_rank[cid] - gt_rank[cid]) if (in_pred and in_gt) else None
        ranking_comparison.append({
            "candidate_id": cid,
            "predicted_rank": pred_rank.get(cid),
            "expected_rank": gt_rank.get(cid),
            "delta": delta,
            "status": (
                "match" if delta == 0
                else "ranked_lower" if (delta is not None and delta > 0)
                else "ranked_higher" if (delta is not None and delta < 0)
                else "unexpected_ranked" if in_pred
                else "missing_from_ranked"
            ),
        })

    return {
        "kendall_tau": tau,
        "ndcg_at_5": ndcg,
        "elimination_precision": round(precision, 4),
        "elimination_recall": round(recall, 4),
        "elimination_f1": round(f1, 4),
        "ranking_comparison": ranking_comparison,
        "false_positives": sorted(fp),   # incorrectly eliminated
        "false_negatives": sorted(fn),   # missed eliminations
    }
