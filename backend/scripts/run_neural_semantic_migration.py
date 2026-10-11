import json
from app.database import SessionLocal
from app.config import settings
from app.models.models import SearchDocument, App
from app.services.search import (
    initialize_encoder, get_encoder_diagnostics, get_embedding_encoder,
    assert_embedding_compatibility, reembed_catalog, execute_hybrid_search,
    IncompatibleEmbeddingModelError, SentenceTransformerEncoder
)

def run():
    print("=== TASK 2: RUN GENUINE NEURAL SEMANTIC SEARCH ===")
    print(f"Configured SEMANTIC_ENCODER_TYPE: {settings.SEMANTIC_ENCODER_TYPE}")
    
    # Step 1 & 2: Initialize encoder
    enc, diag = initialize_encoder("sentence_transformers")
    print("\n[Step 1 & 2] Encoder Diagnostics:")
    for k, v in diag.items():
        print(f"  {k}: {v}")
        
    assert isinstance(enc, SentenceTransformerEncoder), "Encoder must be SentenceTransformerEncoder"
    assert diag["is_genuine_neural"] is True, "is_genuine_neural must be True"
    assert diag["fallback_to_lexical"] is False, "fallback_to_lexical must be False"
    assert diag["status"] == "active", "status must be active"
    
    # Step 3: Report actual model identity and dimension
    print(f"\n[Step 3] Active Model Identity: '{enc.model_name}'")
    print(f"         Embedding Dimension: {enc.dim}")
    
    db = SessionLocal()
    try:
        # Pre-reembedding check: should detect mismatch if DB still has deterministic-hash-v1
        print("\n[Pre-Check] Checking compatibility before re-embedding...")
        try:
            assert_embedding_compatibility(db, enc)
            print("  DB documents already match model identity.")
        except IncompatibleEmbeddingModelError as e:
            print(f"  Expected mismatch caught before migration: {e}")
            
        # Step 4: Re-embed complete catalog
        print("\n[Step 4] Re-embedding complete catalog...")
        total_docs = db.query(SearchDocument).count()
        print(f"  Total search documents in DB: {total_docs}")
        reembedded_count = reembed_catalog(db, enc)
        print(f"  Successfully re-embedded {reembedded_count} documents into '{enc.model_name}' space.")
        assert reembedded_count == total_docs, f"Expected {total_docs} re-embedded, got {reembedded_count}"
        
        # Step 5: Verify model identity and dimension compatibility
        print("\n[Step 5] Verifying model identity and dimension compatibility post-migration...")
        assert_embedding_compatibility(db, enc)
        print("  Compatibility check passed with zero errors!")
        
        # Sample document check
        sample_doc = db.query(SearchDocument).first()
        print(f"  Sample Doc ({sample_doc.app.slug}):")
        print(f"    model_name: {sample_doc.model_name}")
        print(f"    embedding_dim: {sample_doc.embedding_dim}")
        print(f"    embedding vector length: {len(sample_doc.embedding)}")
        print(f"    embedding vector sample (first 5 floats): {sample_doc.embedding[:5]}")
        
        # Step 6: Execute search queries using genuine neural model
        print("\n[Step 6] Executing actual queries with genuine neural semantic search...")
        test_queries = [
            "photo editor for linux",
            "music production daw",
            "clean junk files",
            "find duplicate audio files",
            "client side encrypted backup"
        ]
        for q in test_queries:
            results, meta = execute_hybrid_search(db, q, limit=3)
            print(f"\n  Query: '{q}'")
            print(f"  Semantic active: {meta.get('semantic_search_active')}")
            print(f"  Encoder type: {meta['encoder_diagnostics']['configured_type']} (neural={meta['encoder_diagnostics']['is_genuine_neural']})")
            for i, r in enumerate(results, 1):
                app = r['app']
                print(f"    {i}. {app.slug:15} | Score: {r['score']} | Sources: {r['sources']}")
                
    finally:
        db.close()

if __name__ == "__main__":
    run()
