import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from app.models.models import (
    App, Category, CategoryAlias, AppCapability, AppCategory, SearchDocument, VerificationCheck
)
from app.services.verification import derive_verification_status
from app.database import unaccent_text, trigram_sim
from app.config import settings

class IncompatibleEmbeddingModelError(Exception):
    """Raised when the active embedding model does not match the model identity or dimension stored in search_documents."""
    pass


# Injectable embedding model interface
class EmbeddingEncoderInterface:
    dim: int = 384
    model_name: str = "generic-encoder"
    is_genuine_neural: bool = False
    encoder_type: str = "generic"

    def encode(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class DeterministicFakeEncoder(EmbeddingEncoderInterface):
    """Deterministic hash-based encoder for test suites and environments without heavy neural model downloads."""
    def __init__(self, dim: int = 384, model_name: str = "deterministic-hash-v1"):
        self.dim = dim
        self.model_name = model_name
        self.is_genuine_neural = False
        self.encoder_type = "deterministic_test"

    def encode(self, texts: List[str]) -> List[List[float]]:
        import hashlib
        vectors = []
        for text in texts:
            words = text.lower().split()
            vec = [0.0] * self.dim
            for w in words:
                h = int(hashlib.sha256(w.encode("utf-8")).hexdigest()[:8], 16)
                slot = h % self.dim
                vec[slot] += 1.0
            norm = sum(x*x for x in vec) ** 0.5
            if norm > 0:
                vec = [x / norm for x in vec]
            vectors.append(vec)
        return vectors


class SentenceTransformerEncoder(EmbeddingEncoderInterface):
    """Real local neural embedding model using sentence-transformers."""
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)
            self.model_name = model_name
            self.dim = self._model.get_sentence_embedding_dimension()
            self.is_genuine_neural = True
            self.encoder_type = "sentence_transformers"
        except ImportError as e:
            raise RuntimeError("sentence-transformers is not installed. Install with `pip install sentence-transformers`.") from e

    def encode(self, texts: List[str]) -> List[List[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings.tolist()


_current_encoder: Optional[EmbeddingEncoderInterface] = None
_encoder_diagnostics: Dict[str, Any] = {
    "configured_type": settings.SEMANTIC_ENCODER_TYPE,
    "active_model_name": None,
    "embedding_dim": None,
    "is_genuine_neural": False,
    "status": "uninitialized",
    "error": None,
    "fallback_to_lexical": False,
}


def initialize_encoder(encoder_type: Optional[str] = None) -> Tuple[Optional[EmbeddingEncoderInterface], Dict[str, Any]]:
    """
    Explicitly initialize the embedding encoder according to configuration.
    Never silently use hash-generated vectors as a substitute for neural semantic embeddings.
    If neural model is unavailable, reports failure and falls back cleanly to lexical search.
    """
    global _current_encoder, _encoder_diagnostics
    enc_type = encoder_type if encoder_type is not None else settings.SEMANTIC_ENCODER_TYPE

    if enc_type == "deterministic_test":
        _current_encoder = DeterministicFakeEncoder(
            dim=settings.EMBEDDING_DIM,
            model_name="deterministic-hash-v1"
        )
        _encoder_diagnostics = {
            "configured_type": enc_type,
            "active_model_name": _current_encoder.model_name,
            "embedding_dim": _current_encoder.dim,
            "is_genuine_neural": False,
            "status": "active",
            "error": None,
            "fallback_to_lexical": False,
        }
    elif enc_type == "sentence_transformers":
        try:
            _current_encoder = SentenceTransformerEncoder(model_name=settings.EMBEDDING_MODEL_NAME)
            _encoder_diagnostics = {
                "configured_type": enc_type,
                "active_model_name": _current_encoder.model_name,
                "embedding_dim": _current_encoder.dim,
                "is_genuine_neural": True,
                "status": "active",
                "error": None,
                "fallback_to_lexical": False,
            }
        except Exception as e:
            # Predictable failure reporting: do NOT substitute fake encoder silently
            _current_encoder = None
            _encoder_diagnostics = {
                "configured_type": enc_type,
                "active_model_name": None,
                "embedding_dim": None,
                "is_genuine_neural": False,
                "status": "failed",
                "error": str(e),
                "fallback_to_lexical": True,
            }
    elif enc_type == "none":
        _current_encoder = None
        _encoder_diagnostics = {
            "configured_type": "none",
            "active_model_name": None,
            "embedding_dim": None,
            "is_genuine_neural": False,
            "status": "disabled",
            "error": None,
            "fallback_to_lexical": True,
        }
    else:
        _current_encoder = None
        _encoder_diagnostics = {
            "configured_type": enc_type,
            "active_model_name": None,
            "embedding_dim": None,
            "is_genuine_neural": False,
            "status": "failed",
            "error": f"Unknown encoder type '{enc_type}'",
            "fallback_to_lexical": True,
        }
    return _current_encoder, _encoder_diagnostics


# Initialize default encoder
initialize_encoder()


def get_encoder_diagnostics() -> Dict[str, Any]:
    return _encoder_diagnostics.copy()


def set_embedding_encoder(encoder: Optional[EmbeddingEncoderInterface]):
    global _current_encoder, _encoder_diagnostics
    _current_encoder = encoder
    if encoder:
        _encoder_diagnostics = {
            "configured_type": getattr(encoder, "encoder_type", "custom"),
            "active_model_name": encoder.model_name,
            "embedding_dim": encoder.dim,
            "is_genuine_neural": getattr(encoder, "is_genuine_neural", False),
            "status": "active",
            "error": None,
            "fallback_to_lexical": False,
        }
    else:
        _encoder_diagnostics = {
            "configured_type": "none",
            "active_model_name": None,
            "embedding_dim": None,
            "is_genuine_neural": False,
            "status": "disabled",
            "error": None,
            "fallback_to_lexical": True,
        }


def get_embedding_encoder() -> Optional[EmbeddingEncoderInterface]:
    return _current_encoder


def assert_embedding_compatibility(db: Session, encoder: Optional[EmbeddingEncoderInterface] = None) -> None:
    """
    Assert dimensional and model identity compatibility at startup and before vector search.
    Never mix incompatible embedding models silently.
    """
    enc = encoder if encoder is not None else get_embedding_encoder()
    if enc is None:
        return

    mismatched = db.query(SearchDocument).filter(
        (SearchDocument.model_name != enc.model_name) | (SearchDocument.embedding_dim != enc.dim)
    ).first()

    if mismatched:
        raise IncompatibleEmbeddingModelError(
            f"Embedding model mismatch detected! Database records use model='{mismatched.model_name}' "
            f"(dim={mismatched.embedding_dim}), but active encoder is model='{enc.model_name}' "
            f"(dim={enc.dim}). Re-embedding into a compatible search space is required."
        )


def reembed_catalog(db: Session, encoder: Optional[EmbeddingEncoderInterface] = None) -> int:
    """Perform a full re-embedding into a compatible search space when model changes."""
    enc = encoder if encoder is not None else get_embedding_encoder()
    if not enc:
        raise ValueError("Cannot reembed catalog: no active or provided encoder.")
    docs = db.query(SearchDocument).all()
    if not docs:
        return 0

    texts = [d.document_text for d in docs]
    vectors = enc.encode(texts)
    for doc, vec in zip(docs, vectors):
        doc.embedding = vec
        doc.model_name = enc.model_name
        doc.embedding_dim = enc.dim
        doc.updated_at = datetime.utcnow()

    db.commit()
    return len(docs)


def normalize_query(query: str) -> str:
    """Normalize query: lower, unaccent, remove excess whitespace and special characters."""
    clean = unaccent_text(query).lower()
    clean = re.sub(r"[^\w\s\-\:]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def parse_query_constraints(query: str) -> Tuple[str, Dict[str, Any]]:
    """
    Extract deterministic intent filters:
    e.g., 'open-source photo editor for linux' -> platform='linux'
    'mit backup' -> license='mit'
    """
    normalized = normalize_query(query)
    constraints: Dict[str, Any] = {}

    # Platform constraints
    platforms = ["linux", "windows", "macos", "mac", "web", "docker"]
    for p in platforms:
        pattern = rf"\b(for|on)?\s*{p}\b"
        if re.search(pattern, normalized):
            target_p = "macos" if p == "mac" else p
            constraints["platform"] = target_p
            normalized = re.sub(pattern, "", normalized).strip()

    # License constraints
    if "open-source" in normalized or "open source" in normalized or "foss" in normalized:
        constraints["license_state"] = "confirmed_open_source"
        normalized = re.sub(r"\b(open-source|open source|foss)\b", "", normalized).strip()

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, constraints


def match_categories_and_aliases(db: Session, text: str) -> Tuple[List[Category], List[str]]:
    """Detect taxonomy categories matching text or curated aliases using word boundaries."""
    tokens = set(text.lower().split())
    matched_cats: Dict[int, Category] = {}
    detected_names: List[str] = []
    stop_words = {"tools", "tool", "and", "or", "&", "for", "the", "system", "management", "app", "utility"}

    aliases = db.query(CategoryAlias).all()
    for al in aliases:
        al_text = al.alias.lower()
        # Enforce whole word/phrase boundary matching
        pattern = rf"\b{re.escape(al_text)}\b"
        if re.search(pattern, text):
            cat = db.query(Category).filter(Category.id == al.category_id).first()
            if cat and cat.id not in matched_cats:
                matched_cats[cat.id] = cat
                detected_names.append(cat.name)

    # Check direct category names
    cats = db.query(Category).all()
    for cat in cats:
        c_name = cat.name.lower()
        if re.search(rf"\b{re.escape(c_name)}\b", text):
            if cat.id not in matched_cats:
                matched_cats[cat.id] = cat
                detected_names.append(cat.name)
        else:
            cat_words = set(c_name.split()) - stop_words
            if cat_words and cat_words.issubset(tokens):
                if cat.id not in matched_cats:
                    matched_cats[cat.id] = cat
                    detected_names.append(cat.name)

    return list(matched_cats.values()), detected_names


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


STOP_WORDS = {
    "my", "a", "an", "the", "and", "or", "for", "in", "to", "of", "with", "is", "at", "by", "on", "from",
    "tool", "tools", "app", "apps", "software", "program", "utility"
}


def light_stem(w: str) -> str:
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 3:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 2:
        return w[:-1]
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("ation") and len(w) > 6:
        return w[:-5]
    if w.endswith("izing") and len(w) > 6:
        return w[:-4]
    if w.endswith("izer") and len(w) > 6:
        return w[:-2]
    if w.endswith("ize") and len(w) > 5:
        return w[:-1]
    return w


def search_fts_branch(db: Session, query_terms: List[str], limit: int = 25) -> List[Tuple[App, float]]:
    """Branch 1: Full-Text search on document title, summary, description, and capabilities."""
    if not query_terms:
        return []

    substantive = [t for t in query_terms if t not in STOP_WORDS]
    eval_terms = substantive if substantive else query_terms

    apps = db.query(App).filter(App.is_delisted == False).all()
    results = []
    total_terms = len(eval_terms)

    for app in apps:
        search_text = f"{app.name} {app.summary} {app.description}".lower()
        cap_texts = [cap.capability.lower() for cap in app.capabilities]
        all_words = set(re.findall(r"\w+", search_text + " " + " ".join(cap_texts)))
        all_stems = {light_stem(w) for w in all_words}

        matched_term_count = 0
        score = 0.0

        for term in eval_terms:
            t_stem = light_stem(term)
            term_matched = False

            if term in app.name.lower() or t_stem in app.name.lower():
                score += 4.0
                term_matched = True
            if term in app.summary.lower() or t_stem in app.summary.lower():
                score += 2.5
                term_matched = True
            if term in app.description.lower() or t_stem in app.description.lower():
                score += 1.5
                term_matched = True

            for cap_t in cap_texts:
                if term in cap_t or t_stem in cap_t:
                    score += 3.0
                    term_matched = True
                    break

            if not term_matched and (term in all_words or t_stem in all_stems):
                score += 1.0
                term_matched = True

            if term_matched:
                matched_term_count += 1

        # Multi-word queries require meaningful term coverage
        if total_terms >= 2:
            coverage = matched_term_count / float(total_terms)
            name_lower = app.name.lower()
            has_name_match = any(t in name_lower or light_stem(t) in name_lower for t in eval_terms)
            if coverage < 0.30 and not has_name_match:
                continue
            # Coordination factor: reward full coverage of query terms
            score = score * (0.4 + 0.6 * coverage)
            if matched_term_count == total_terms:
                score += 3.0

        if score > 0:
            results.append((app, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


def search_trigram_branch(db: Session, query_str: str, threshold: float = 0.35, limit: int = 25) -> List[Tuple[App, float]]:
    """Branch 2: Trigram similarity for typo-tolerance (threshold >= 0.35)."""
    if not query_str or len(query_str) < 3:
        return []

    words_in_q = query_str.lower().split()
    apps = db.query(App).filter(App.is_delisted == False).all()
    candidates = []

    for app in apps:
        max_sim = 0.0
        # Compare with app name
        sim_name = trigram_sim(query_str, app.name)
        max_sim = max(max_sim, sim_name)

        # For single-word / typo queries, compare with individual words
        if len(words_in_q) <= 2:
            for cap in app.capabilities:
                sim_cap = trigram_sim(query_str, cap.capability)
                max_sim = max(max_sim, sim_cap)

            words = app.summary.lower().split()
            for w in words:
                if len(w) >= 3:
                    sim_w = trigram_sim(query_str, w)
                    max_sim = max(max_sim, sim_w)
        else:
            # For multi-word queries, compare against capabilities phrases
            for cap in app.capabilities:
                sim_cap = trigram_sim(query_str, cap.capability)
                max_sim = max(max_sim, sim_cap)

        if max_sim >= threshold:
            candidates.append((app, max_sim))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:limit]


def search_vector_branch(db: Session, query_str: str, limit: int = 25) -> List[Tuple[App, float]]:
    """Branch 3: Semantic vector search using local embedding model."""
    if not settings.ENABLE_VECTOR_SEARCH:
        return []
    encoder = get_embedding_encoder()
    if not encoder:
        return []
    query_vec = encoder.encode([query_str])[0]

    docs = db.query(SearchDocument).all()
    candidates = []

    for doc in docs:
        if not doc.embedding:
            continue
        sim = cosine_similarity(query_vec, doc.embedding)
        # Meaningful semantic relevance floor
        if sim >= 0.55:
            candidates.append((doc.app, sim))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:limit]


def execute_hybrid_search(
    db: Session,
    raw_query: str,
    platform: Optional[str] = None,
    license_state: Optional[str] = None,
    limit: int = 20,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Execute hybrid search pipeline:
    1. Parse constraints and normalize query.
    2. Detect taxonomy categories and aliases.
    3. Run 3 branches (FTS, Trigram, Vector), capped at 25 each.
    4. Reciprocal Rank Fusion (RRF) with category & capability match bonuses.
    5. Hard filtering by platform and license.
    6. Return deduplicated, scored results with evidence.
    """
    clean_query, detected_constraints = parse_query_constraints(raw_query)
    filter_platform = platform or detected_constraints.get("platform")
    filter_license = license_state or detected_constraints.get("license_state")

    matched_categories, detected_cat_names = match_categories_and_aliases(db, clean_query)
    matched_cat_ids = {c.id for c in matched_categories}

    # Add child category IDs if broad category matched
    for cat in matched_categories:
        for sub in cat.subcategories:
            matched_cat_ids.add(sub.id)

    query_terms = [t for t in clean_query.split() if len(t) > 1]
    substantive_terms = [t for t in query_terms if t not in STOP_WORDS]
    eval_terms = substantive_terms if substantive_terms else query_terms

    # Run the three branches
    fts_branch = search_fts_branch(db, eval_terms, limit=25)
    trigram_branch = search_trigram_branch(db, clean_query, threshold=settings.SIMILARITY_THRESHOLD, limit=25)
    vector_branch = search_vector_branch(db, clean_query, limit=25)

    # Reciprocal Rank Fusion (RRF)
    # RRF score: 1.0 / (60 + rank)
    app_scores: Dict[int, float] = {}
    app_objects: Dict[int, App] = {}
    app_sources: Dict[int, Set[str]] = {}

    def add_branch_ranks(branch: List[Tuple[App, float]], source_name: str):
        for rank, (app, _) in enumerate(branch):
            app_id = app.id
            app_objects[app_id] = app
            if app_id not in app_scores:
                app_scores[app_id] = 0.0
                app_sources[app_id] = set()
            app_scores[app_id] += 1.0 / (60.0 + rank + 1)
            app_sources[app_id].add(source_name)

    add_branch_ranks(fts_branch, "fts")
    add_branch_ranks(trigram_branch, "trigram")
    add_branch_ranks(vector_branch, "semantic")

    # Category matching bonus
    is_broad_topic = len(eval_terms) <= 2 or any(clean_query == c.name.lower() for c in matched_categories)
    if matched_cat_ids:
        for app in db.query(App).filter(App.is_delisted == False).all():
            app_cat_ids = {ac.category_id for ac in app.categories}
            if app.primary_category_id:
                app_cat_ids.add(app.primary_category_id)
            if matched_cat_ids.intersection(app_cat_ids):
                app_id = app.id
                if app_id in app_scores or is_broad_topic:
                    app_objects[app_id] = app
                    if app_id not in app_scores:
                        app_scores[app_id] = 0.0
                        app_sources[app_id] = set()
                    app_scores[app_id] += 0.025  # Category relevance bonus
                    app_sources[app_id].add("category_match")

    # Capability matching bonus
    for app_id, app in app_objects.items():
        for cap in app.capabilities:
            cap_lower = cap.capability.lower()
            if any(term in cap_lower or light_stem(term) in cap_lower for term in eval_terms):
                app_scores[app_id] += 0.015
                app_sources[app_id].add("capability_match")

    # Term coverage bonus: prioritize apps that match ALL distinct query terms
    if len(eval_terms) >= 2:
        for app_id, app in app_objects.items():
            full_text = f"{app.name} {app.summary} {app.description}".lower()
            caps_text = " ".join(c.capability.lower() for c in app.capabilities)
            combined = f"{full_text} {caps_text}"
            all_terms_matched = all(
                t in combined or light_stem(t) in combined
                for t in eval_terms
            )
            if all_terms_matched:
                app_scores[app_id] += 0.035
                app_sources[app_id].add("full_term_match")

    # Hard filters
    filtered_results = []
    for app_id, score in app_scores.items():
        app = app_objects[app_id]
        if app.is_delisted:
            continue
        if filter_license and app.license_state != filter_license:
            continue
        if filter_platform and filter_platform not in [p.lower() for p in (app.platforms or [])]:
            continue

        checks = db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).all()
        v_status = derive_verification_status(checks)
        latest_check = max([c.checked_at for c in checks]) if checks else None

        filtered_results.append({
            "app": app,
            "score": round(score, 4),
            "sources": sorted(list(app_sources.get(app_id, set()))),
            "verification_status": v_status,
            "latest_check_at": latest_check,
        })

    # Sort descending by score
    filtered_results.sort(key=lambda x: x["score"], reverse=True)

    metadata = {
        "clean_query": clean_query,
        "detected_categories": detected_cat_names,
        "matched_category_ids": list(matched_cat_ids),
        "applied_filters": {
            "platform": filter_platform,
            "license_state": filter_license,
        },
        "encoder_diagnostics": get_encoder_diagnostics(),
        "semantic_search_active": (get_embedding_encoder() is not None) and settings.ENABLE_VECTOR_SEARCH,
    }

    return filtered_results[:limit], metadata
