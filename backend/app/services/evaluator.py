import json
import math
import os
from typing import Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from app.services.search import execute_hybrid_search

EVAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed", "eval_queries.json")


def dcg_at_k(grades: List[int], k: int = 5) -> float:
    """Calculate Discounted Cumulative Gain at rank k."""
    dcg = 0.0
    for i, grade in enumerate(grades[:k]):
        # Formula: (2^rel - 1) / log2(i + 2)
        gain = (2 ** grade) - 1.0
        discount = math.log2(i + 2)
        dcg += gain / discount
    return dcg


def ndcg_at_k(actual_grades: List[int], ideal_grades: List[int], k: int = 5) -> float:
    """Calculate Normalized Discounted Cumulative Gain at rank k."""
    idcg = dcg_at_k(sorted(ideal_grades, reverse=True), k)
    if idcg <= 0.0:
        return 1.0 if not actual_grades or max(actual_grades) == 0 else 0.0
    actual_dcg = dcg_at_k(actual_grades, k)
    return min(1.0, actual_dcg / idcg)


def precision_at_k(grades: List[int], k: int = 5, returned_count: int = 5) -> float:
    """
    Precision at k where grades >= 2 count as relevant.
    Denominator is min(k, max(returned_count, 1)) to evaluate the actual precision of
    the returned candidate set without fabricating unreturned false negatives.
    """
    if k <= 0 or returned_count <= 0:
        return 0.0
    denom = min(k, returned_count)
    considered = grades[:denom]
    if not considered:
        return 0.0
    relevant_count = sum(1 for g in considered if g >= 2)
    return min(1.0, relevant_count / float(denom))


def evaluate_query_set(db: Session, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_query_results = []
    ndcg_list = []
    p_at_5_list = []
    task_success_count = 0
    eligible_task_count = 0
    unknown_query_count = 0
    unknown_query_correct = 0

    for item in queries:
        qid = item["id"]
        q_text = item["query"]
        q_type = item["type"]
        expected_apps: Dict[str, int] = item.get("expected_apps", {})

        # Run search
        search_results, meta = execute_hybrid_search(db=db, raw_query=q_text, limit=10)
        returned_slugs = [r["app"].slug for r in search_results]

        is_unknown = q_type == "unknown_query" or (len(expected_apps) == 0)

        if is_unknown:
            unknown_query_count += 1
            # For unknown queries, correct behavior is returning 0 fabricated results
            passed = len(search_results) == 0
            if passed:
                unknown_query_correct += 1
            per_query_results.append({
                "id": qid,
                "query": q_text,
                "type": q_type,
                "returned_count": len(search_results),
                "is_unknown": True,
                "success": passed,
                "note": "Unknown query correctly yielded 0 results" if passed else f"Fabricated {len(search_results)} apps"
            })
            continue

        # Known query evaluation
        eligible_task_count += 1
        ideal_grades = list(expected_apps.values())

        # Map returned ranks to grades
        actual_grades = []
        for slug in returned_slugs[:5]:
            grade = expected_apps.get(slug, 0)
            actual_grades.append(grade)

        ndcg = ndcg_at_k(actual_grades, ideal_grades, k=5)
        pat5 = precision_at_k(actual_grades, k=5, returned_count=len(returned_slugs))

        # Task query success: at least one relevant app (grade >= 2) in top 3 results
        has_top_relevant = any(g >= 2 for g in actual_grades[:3])
        if has_top_relevant:
            task_success_count += 1

        ndcg_list.append(ndcg)
        p_at_5_list.append(pat5)

        per_query_results.append({
            "id": qid,
            "query": q_text,
            "type": q_type,
            "returned_slugs": returned_slugs[:5],
            "actual_grades": actual_grades[:5],
            "ndcg_at_5": round(ndcg, 3),
            "p_at_5": round(pat5, 3),
            "task_success": has_top_relevant,
        })

    avg_ndcg = sum(ndcg_list) / len(ndcg_list) if ndcg_list else 0.0
    avg_pat5 = sum(p_at_5_list) / len(p_at_5_list) if p_at_5_list else 0.0
    task_success_rate = (task_success_count / eligible_task_count) if eligible_task_count else 0.0
    unknown_accuracy = (unknown_query_correct / unknown_query_count) if unknown_query_count else 1.0

    return {
        "total_queries": len(queries),
        "eligible_task_queries": eligible_task_count,
        "unknown_queries": unknown_query_count,
        "unknown_accuracy": round(unknown_accuracy, 2),
        "unknown_ratio": f"{unknown_query_correct}/{unknown_query_count}",
        "task_success_ratio": f"{task_success_count}/{eligible_task_count}",
        "ndcg_at_5": round(avg_ndcg, 2),
        "p_at_5": round(avg_pat5, 2),
        "task_success_rate": round(task_success_rate, 2),
        "passed_thresholds": {
            "ndcg_ge_0_70": avg_ndcg >= 0.70,
            "p_at_5_ge_0_60": avg_pat5 >= 0.60,
            "task_success_ge_0_80": task_success_rate >= 0.80,
        },
        "per_query_results": per_query_results,
    }


def run_full_benchmark(db: Session, eval_file: str = EVAL_PATH) -> Dict[str, Any]:
    with open(eval_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    dev_results = evaluate_query_set(db, data.get("development_queries", []))
    held_out_results = evaluate_query_set(db, data.get("held_out_queries", []))

    return {
        "development": dev_results,
        "held_out": held_out_results,
    }
