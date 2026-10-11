import json
import math
import os
from typing import Dict, Any, List
from app.database import SessionLocal
from app.services.evaluator import run_full_benchmark, dcg_at_k, ndcg_at_k, precision_at_k
from app.services.search import execute_hybrid_search

def run_reconciliation():
    db = SessionLocal()
    try:
        # Run standard benchmark
        report = run_full_benchmark(db)
        
        # Save raw benchmark output
        output_file = "benchmark_reconciliation_output.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[1] Saved complete benchmark report to {output_file}")
        
        # Now verify and reconcile both development and held-out queries
        reconciliation_results = {}
        for set_name in ["development", "held_out"]:
            print(f"\n=======================================================")
            print(f"RECONCILING {set_name.upper()} SET")
            print(f"=======================================================")
            
            set_data = report[set_name]
            per_query = set_data["per_query_results"]
            
            ndcg_vals = []
            pat5_vals = []
            task_successes = []
            unknown_successes = []
            
            detailed_table = []
            
            total_relevant_retrieved = 0
            total_k_considered = 0
            
            for q in per_query:
                qid = q["id"]
                q_text = q["query"]
                q_type = q["type"]
                
                if q.get("is_unknown"):
                    # Unknown query
                    returned_count = q["returned_count"]
                    passed = (returned_count == 0)
                    unknown_successes.append(1 if passed else 0)
                    detailed_table.append({
                        "id": qid,
                        "query": q_text,
                        "type": q_type,
                        "is_unknown": True,
                        "returned_count": returned_count,
                        "passed": passed,
                        "ratio": f"{1 if passed else 0}/1"
                    })
                    print(f"[{qid}] '{q_text}' (UNKNOWN) -> returned={returned_count}, pass={passed}")
                    continue
                
                # Known query
                slugs = q["returned_slugs"]
                grades = q["actual_grades"]
                
                # Retrieve expected grades from seed file
                eval_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "seed", "eval_queries.json")
                with open(eval_file, "r", encoding="utf-8") as ef:
                    seed_data = json.load(ef)
                query_spec = next(item for item in seed_data[f"{set_name}_queries"] if item["id"] == qid)
                expected_apps = query_spec.get("expected_apps", {})
                ideal_grades = list(expected_apps.values())
                
                # 1. DCG@5 and IDCG@5
                actual_dcg = dcg_at_k(grades, k=5)
                ideal_dcg = dcg_at_k(sorted(ideal_grades, reverse=True), k=5)
                recomputed_ndcg = ndcg_at_k(grades, ideal_grades, k=5)
                ndcg_vals.append(recomputed_ndcg)
                
                # 2. P@5 calculation:
                # Denominator is min(5, returned_count)
                # Numerator is count of grades in top min(5, returned_count) where grade >= 2
                returned_count = len(slugs)
                denom = min(5, returned_count) if returned_count > 0 else 5
                considered_grades = grades[:denom]
                num_relevant = sum(1 for g in considered_grades if g >= 2)
                recomputed_pat5 = num_relevant / float(denom) if denom > 0 else 0.0
                pat5_vals.append(recomputed_pat5)
                
                total_relevant_retrieved += num_relevant
                total_k_considered += denom
                
                # 3. Task Success: at least 1 grade >= 2 in top 3
                has_task_success = any(g >= 2 for g in grades[:3])
                task_successes.append(1 if has_task_success else 0)
                
                # Compare recomputed against evaluator reported
                ndcg_diff = abs(recomputed_ndcg - q["ndcg_at_5"])
                pat5_diff = abs(recomputed_pat5 - q["p_at_5"])
                task_match = (has_task_success == q["task_success"])
                
                detailed_table.append({
                    "id": qid,
                    "query": q_text,
                    "type": q_type,
                    "is_unknown": False,
                    "returned_slugs": slugs,
                    "grades": grades,
                    "ideal_grades": sorted(ideal_grades, reverse=True)[:5],
                    "actual_dcg": round(actual_dcg, 4),
                    "ideal_dcg": round(ideal_dcg, 4),
                    "ndcg_at_5": round(recomputed_ndcg, 4),
                    "pat5_numerator": num_relevant,
                    "pat5_denominator": denom,
                    "pat5_ratio": f"{num_relevant}/{denom}",
                    "p_at_5": round(recomputed_pat5, 4),
                    "task_success": has_task_success,
                    "ndcg_match": ndcg_diff < 0.001,
                    "pat5_match": pat5_diff < 0.001,
                    "task_match": task_match
                })
                
                print(f"[{qid}] '{q_text}'")
                print(f"   Slugs: {slugs}")
                print(f"   Grades: {grades}")
                print(f"   nDCG@5: {recomputed_ndcg:.4f} (DCG={actual_dcg:.4f}, IDCG={ideal_dcg:.4f}) | Reported={q['ndcg_at_5']:.3f} | Match={ndcg_diff < 0.001}")
                print(f"   P@5: {recomputed_pat5:.4f} (Num={num_relevant}, Denom={denom}) | Reported={q['p_at_5']:.3f} | Match={pat5_diff < 0.001}")
                print(f"   Task Success: {has_task_success} (top-3 relevant) | Reported={q['task_success']} | Match={task_match}")
            
            # Aggregate calculations
            mean_ndcg = sum(ndcg_vals) / len(ndcg_vals) if ndcg_vals else 0.0
            mean_pat5 = sum(pat5_vals) / len(pat5_vals) if pat5_vals else 0.0
            pooled_pat5 = total_relevant_retrieved / float(total_k_considered) if total_k_considered > 0 else 0.0
            task_success_rate = sum(task_successes) / len(task_successes) if task_successes else 0.0
            unknown_accuracy = sum(unknown_successes) / len(unknown_successes) if unknown_successes else 1.0
            
            reported_mean_ndcg = set_data["ndcg_at_5"]
            reported_mean_pat5 = set_data["p_at_5"]
            reported_task_success = set_data["task_success_rate"]
            reported_unknown_accuracy = set_data["unknown_accuracy"]
            
            print(f"\n--- {set_name.upper()} AGGREGATE RECONCILIATION ---")
            print(f"Mean nDCG@5: Recomputed={mean_ndcg:.4f} (Rounded={round(mean_ndcg, 2)}) | Reported in Benchmark={reported_mean_ndcg}")
            print(f"  Discrepancy: {abs(round(mean_ndcg, 2) - reported_mean_ndcg):.4f}")
            print(f"Mean P@5 (Query-level): Recomputed={mean_pat5:.4f} (Rounded={round(mean_pat5, 2)}) | Reported in Benchmark={reported_mean_pat5}")
            print(f"  Discrepancy: {abs(round(mean_pat5, 2) - reported_mean_pat5):.4f}")
            print(f"Pooled P@5 (Micro-average): Total Relevant={total_relevant_retrieved}, Total Considered={total_k_considered} -> {pooled_pat5:.4f}")
            print(f"Task Success Rate: Recomputed={sum(task_successes)}/{len(task_successes)} = {task_success_rate:.4f} (Rounded={round(task_success_rate, 2)}) | Reported in Benchmark={reported_task_success}")
            print(f"  Discrepancy: {abs(round(task_success_rate, 2) - reported_task_success):.4f}")
            print(f"Unknown Query Accuracy: Recomputed={sum(unknown_successes)}/{len(unknown_successes)} = {unknown_accuracy:.4f} (Rounded={round(unknown_accuracy, 2)}) | Reported in Benchmark={reported_unknown_accuracy}")
            print(f"  Discrepancy: {abs(round(unknown_accuracy, 2) - reported_unknown_accuracy):.4f}")
            
            reconciliation_results[set_name] = {
                "per_query_details": detailed_table,
                "aggregates": {
                    "eligible_queries": len(ndcg_vals),
                    "unknown_queries": len(unknown_successes),
                    "mean_ndcg_recomputed": round(mean_ndcg, 4),
                    "mean_ndcg_reported": reported_mean_ndcg,
                    "mean_pat5_recomputed": round(mean_pat5, 4),
                    "mean_pat5_reported": reported_mean_pat5,
                    "pooled_pat5": round(pooled_pat5, 4),
                    "pooled_pat5_num": total_relevant_retrieved,
                    "pooled_pat5_denom": total_k_considered,
                    "task_success_rate_recomputed": round(task_success_rate, 4),
                    "task_success_rate_reported": reported_task_success,
                    "task_success_num": sum(task_successes),
                    "task_success_denom": len(task_successes),
                    "unknown_accuracy_recomputed": round(unknown_accuracy, 4),
                    "unknown_accuracy_reported": reported_unknown_accuracy,
                    "unknown_accuracy_num": sum(unknown_successes),
                    "unknown_accuracy_denom": len(unknown_successes),
                }
            }
        
        with open("reconciliation_full_results.json", "w", encoding="utf-8") as rf:
            json.dump(reconciliation_results, rf, indent=2)
        print(f"\n[OK] Full reconciliation saved to reconciliation_full_results.json")
    finally:
        db.close()

if __name__ == "__main__":
    run_reconciliation()
