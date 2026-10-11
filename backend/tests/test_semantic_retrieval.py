import pytest
from app.database import SessionLocal
from app.models.models import SearchDocument, App
from app.services.search import (
    EmbeddingEncoderInterface,
    DeterministicFakeEncoder,
    SentenceTransformerEncoder,
    IncompatibleEmbeddingModelError,
    assert_embedding_compatibility,
    reembed_catalog,
    get_embedding_encoder,
    set_embedding_encoder,
    initialize_encoder,
    get_encoder_diagnostics,
    search_fts_branch,
    search_trigram_branch,
    search_vector_branch,
    execute_hybrid_search,
)
from app.config import settings


def test_encoder_identity_and_independence():
    """Required Test 17: Confirm fake encoder is used only when explicitly configured or within tests."""
    initialize_encoder("deterministic_test")
    encoder = get_embedding_encoder()
    diag = get_encoder_diagnostics()

    assert isinstance(encoder, DeterministicFakeEncoder)
    assert encoder.dim == 384
    assert encoder.model_name == "deterministic-hash-v1"
    assert diag["is_genuine_neural"] is False
    assert diag["configured_type"] == "deterministic_test"
    assert diag["status"] == "active"

    # Verify deterministic encoding behavior
    v1 = encoder.encode(["open source audio editor"])[0]
    v2 = encoder.encode(["open source audio editor"])[0]
    assert len(v1) == 384
    assert v1 == v2
    # Unit norm check
    norm = sum(x*x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-4

    # Restore configured encoder
    initialize_encoder(settings.SEMANTIC_ENCODER_TYPE)


def test_neural_mode_reporting_and_initialization_failure():
    """Required Test 18: Semantic mode accurately reports when genuine neural embeddings are active or failed."""
    # When configured for neural but sentence-transformers is missing or fails:
    # Must report failure accurately, not silently substitute fake hash encoder
    enc, diag = initialize_encoder("sentence_transformers")
    assert diag["configured_type"] == "sentence_transformers"
    if enc is None:
        # Predictable failure reporting:
        assert diag["status"] == "failed"
        assert diag["error"] is not None
        assert diag["is_genuine_neural"] is False
        assert diag["fallback_to_lexical"] is True
    else:
        # If installed:
        assert diag["status"] == "active"
        assert diag["is_genuine_neural"] is True

    # Restore configured encoder for remainder of suite
    initialize_encoder(settings.SEMANTIC_ENCODER_TYPE)


def test_incompatible_model_rejection():
    """Required Test 19: Verify changing the embedding model cannot mix incompatible vectors."""
    db = SessionLocal()
    try:
        sample = db.query(SearchDocument).first()
        current_model = sample.model_name if sample else "current-model"
        current_dim = sample.embedding_dim if sample else 384

        # 1. Dimension mismatch
        bad_dim_encoder = DeterministicFakeEncoder(dim=current_dim + 128, model_name=current_model)
        with pytest.raises(IncompatibleEmbeddingModelError) as exc_dim:
            assert_embedding_compatibility(db, bad_dim_encoder)
        assert "Embedding model mismatch detected" in str(exc_dim.value)

        # 2. Model name mismatch
        bad_model_encoder = DeterministicFakeEncoder(dim=current_dim, model_name="different-incompatible-model-v2")
        with pytest.raises(IncompatibleEmbeddingModelError) as exc_name:
            assert_embedding_compatibility(db, bad_model_encoder)
        assert "Embedding model mismatch detected" in str(exc_name.value)
    finally:
        db.close()


def test_reembedding_and_migration():
    """Verify that reembed_catalog successfully updates search space dimensions and model names."""
    db = SessionLocal()
    orig_encoder = get_embedding_encoder()
    try:
        new_test_encoder = DeterministicFakeEncoder(dim=256, model_name="test-migrated-encoder-v2")
        reembed_count = reembed_catalog(db, new_test_encoder)
        assert reembed_count > 0

        # Now new_test_encoder must be compatible
        assert_embedding_compatibility(db, new_test_encoder)

        # And original encoder must now be rejected
        with pytest.raises(IncompatibleEmbeddingModelError):
            assert_embedding_compatibility(db, orig_encoder)
    finally:
        # Restore original test search space
        reembed_catalog(db, orig_encoder)
        set_embedding_encoder(orig_encoder)
        assert_embedding_compatibility(db, orig_encoder)
        db.close()


def test_search_continues_when_encoder_unavailable():
    """Required Test 20: The application continues searching when the encoder is unavailable."""
    db = SessionLocal()
    orig_encoder = get_embedding_encoder()
    try:
        # Disable encoder
        set_embedding_encoder(None)
        assert get_embedding_encoder() is None

        # Vector branch returns empty list gracefully
        vec_res = search_vector_branch(db, "audio editor")
        assert vec_res == []

        # Hybrid search continues to work and return relevant apps via keyword and trigram
        results, meta = execute_hybrid_search(db, "audacity", limit=5)
        assert len(results) > 0
        assert results[0]["app"].slug == "audacity"
        assert meta["semantic_search_active"] is False
        assert meta["encoder_diagnostics"]["status"] == "disabled"
    finally:
        set_embedding_encoder(orig_encoder)
        db.close()
