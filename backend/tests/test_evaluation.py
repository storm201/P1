import pytest
from app.database import SessionLocal
from app.services.evaluator import run_full_benchmark


def test_search_engine_evaluation_benchmark():
    db = SessionLocal()
    try:
        report = run_full_benchmark(db)
        dev = report["development"]
        held = report["held_out"]

        print("\n--- DEVELOPMENT BENCHMARK ---")
        print(f"nDCG@5: {dev['ndcg_at_5']:.2f} (Floor >= 0.70)")
        print(f"P@5: {dev['p_at_5']:.2f}")
        print(f"Task Success: {dev['task_success_rate']:.2f} (Floor >= 0.80)")
        print(f"Unknown Queries Handled: {dev['unknown_accuracy']:.2f} (Expected 1.00)")

        print("\n--- HELD-OUT BENCHMARK ---")
        print(f"nDCG@5: {held['ndcg_at_5']:.2f}")
        print(f"P@5: {held['p_at_5']:.2f}")
        print(f"Task Success: {held['task_success_rate']:.2f}")

        # Assert Stage 2 Acceptance Floors strictly
        assert dev["ndcg_at_5"] >= 0.70, f"Development nDCG@5 {dev['ndcg_at_5']} below floor 0.70"
        assert dev["p_at_5"] >= 0.60, f"Development P@5 {dev['p_at_5']} below floor 0.60"
        assert dev["task_success_rate"] >= 0.80, f"Development task success {dev['task_success_rate']} below floor 0.80"
        assert dev["unknown_accuracy"] == 1.0, f"Unknown dev queries failed: {dev['unknown_ratio']}"

        # Assert Held-Out Independence and Quality Floors
        assert held["ndcg_at_5"] >= 0.70, f"Held-out nDCG@5 {held['ndcg_at_5']} below floor 0.70"
        assert held["p_at_5"] >= 0.60, f"Held-out P@5 {held['p_at_5']} below floor 0.60"
        assert held["task_success_rate"] >= 0.80, f"Held-out task success {held['task_success_rate']} below floor 0.80"
        assert held["unknown_accuracy"] == 1.0, f"Unknown held-out queries failed: {held['unknown_ratio']}"
    finally:
        db.close()
