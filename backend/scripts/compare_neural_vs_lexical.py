import json
from app.database import SessionLocal
from app.services.search import initialize_encoder, set_embedding_encoder, DeterministicFakeEncoder
from app.services.evaluator import run_full_benchmark

def run_comparison():
    db = SessionLocal()
    try:
        # 1. Neural-enabled benchmark
        print("=== 1. RUNNING NEURAL-ENABLED HYBRID BENCHMARK ===")
        enc_neural, diag_neural = initialize_encoder("sentence_transformers")
        print(f"Active encoder: {diag_neural['active_model_name']}, is_genuine_neural={diag_neural['is_genuine_neural']}")
        neural_report = run_full_benchmark(db)
        
        # 2. Lexical-only benchmark (disable vector search / encoder=None)
        print("\n=== 2. RUNNING LEXICAL-ONLY BENCHMARK (NO VECTOR RETRIEVAL) ===")
        enc_none, diag_none = initialize_encoder("none")
        print(f"Active encoder: None, is_genuine_neural=False, fallback_to_lexical=True")
        lexical_report = run_full_benchmark(db)
        
        # 3. Deterministic test encoder benchmark (for comparison)
        print("\n=== 3. RUNNING DETERMINISTIC TEST ENCODER BENCHMARK ===")
        enc_det, diag_det = initialize_encoder("deterministic_test")
        print(f"Active encoder: {diag_det['active_model_name']}")
        deterministic_report = run_full_benchmark(db)
        
        # Restore neural encoder
        initialize_encoder("sentence_transformers")
        
        # Comparison summary
        print("\n=======================================================")
        print("COMPARISON SUMMARY: NEURAL vs. LEXICAL-ONLY vs. DETERMINISTIC")
        print("=======================================================")
        for set_name in ["development", "held_out"]:
            print(f"\n--- {set_name.upper()} QUERIES ---")
            neu = neural_report[set_name]
            lex = lexical_report[set_name]
            det = deterministic_report[set_name]
            
            print(f"Metric                | Neural Hybrid | Lexical Only | Deterministic Test")
            print(f"----------------------|---------------|--------------|-------------------")
            print(f"nDCG@5                | {neu['ndcg_at_5']:.4f}        | {lex['ndcg_at_5']:.4f}       | {det['ndcg_at_5']:.4f}")
            print(f"P@5 (Query Mean)      | {neu['p_at_5']:.4f}        | {lex['p_at_5']:.4f}       | {det['p_at_5']:.4f}")
            print(f"Task Success Rate     | {neu['task_success_rate']:.4f}        | {lex['task_success_rate']:.4f}       | {det['task_success_rate']:.4f}")
            print(f"Unknown Accuracy      | {neu['unknown_accuracy']:.4f}        | {lex['unknown_accuracy']:.4f}       | {det['unknown_accuracy']:.4f}")
            
            # Per-query differences
            print(f"\nPer-Query Differences between Neural and Lexical ({set_name}):")
            diff_count = 0
            for q_neu, q_lex in zip(neu["per_query_results"], lex["per_query_results"]):
                if q_neu.get("is_unknown"):
                    continue
                diff_ndcg = q_neu["ndcg_at_5"] - q_lex["ndcg_at_5"]
                diff_p = q_neu["p_at_5"] - q_lex["p_at_5"]
                slugs_neu = q_neu["returned_slugs"]
                slugs_lex = q_lex["returned_slugs"]
                
                if slugs_neu != slugs_lex or abs(diff_ndcg) > 0.001 or abs(diff_p) > 0.001:
                    diff_count += 1
                    print(f"  [{q_neu['id']}] '{q_neu['query']}':")
                    print(f"    Neural:  nDCG={q_neu['ndcg_at_5']:.3f}, P@5={q_neu['p_at_5']:.3f}, Slugs={slugs_neu[:5]}")
                    print(f"    Lexical: nDCG={q_lex['ndcg_at_5']:.3f}, P@5={q_lex['p_at_5']:.3f}, Slugs={slugs_lex[:5]}")
                    print(f"    Delta:   d_nDCG={diff_ndcg:+.3f}, d_P@5={diff_p:+.3f}")
            if diff_count == 0:
                print("  Zero ranking differences observed between neural and lexical.")
                
        # Save complete comparison JSON
        comparison_data = {
            "neural_hybrid": neural_report,
            "lexical_only": lexical_report,
            "deterministic_test": deterministic_report
        }
        with open("neural_vs_lexical_comparison.json", "w", encoding="utf-8") as cf:
            json.dump(comparison_data, cf, indent=2)
        print("\n[OK] Comparison saved to neural_vs_lexical_comparison.json")
        
    finally:
        db.close()

if __name__ == "__main__":
    run_comparison()
