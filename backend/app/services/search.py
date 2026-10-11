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


GENERIC_TERMS = {
    "file", "files", "manager", "management", "tool", "tools", "app", "apps",
    "software", "utility", "system", "program", "suite", "client", "browser", "viewer", "helper"
}

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
    if w.endswith("er") and len(w) > 5 and not w.endswith("other") and not w.endswith("under"):
        return w[:-2]
    if w.endswith("or") and len(w) > 5:
        return w[:-2]
    return w


def normalize_query(query: str) -> str:
    """Normalize query: lower, unaccent, normalize phrasal verbs, remove excess whitespace and special characters."""
    clean = unaccent_text(query).lower()
    clean = re.sub(r"\bback\s+up\b", "backup", clean)
    clean = re.sub(r"\bset\s+up\b", "setup", clean)
    clean = re.sub(r"\bclean\s+up\b", "cleanup", clean)
    clean = re.sub(r"[^\w\s\-\:]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def parse_query_constraints(query: str) -> Tuple[str, Dict[str, Any]]:
    """
    Extract deterministic intent filters:
    e.g., 'open-source photo editor for linux' -> platform='linux', license_state='confirmed_open_source'
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
    if re.search(r"\b(open-source|open source|foss)\b", normalized):
        constraints["license_state"] = "confirmed_open_source"
        normalized = re.sub(r"\b(open-source|open source|foss)\b", "", normalized).strip()

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, constraints


def match_categories_and_aliases(db: Session, text: str) -> Tuple[List[Category], List[str]]:
    """
    Greedy non-overlapping longest-span entity matching for taxonomy aliases and category names.
    Prevents shorter nested sub-tokens (e.g. 'editor' -> Developer Tools) from matching
    when part of a longer specific phrase (e.g. 'photo editor' -> Image & Photo Editors).
    """
    aliases = db.query(CategoryAlias).all()
    categories = db.query(Category).all()

    candidates: List[Tuple[str, Category, int]] = []
    for al in aliases:
        candidates.append((al.alias.lower().strip(), al.category, len(al.alias.split())))
    for cat in categories:
        candidates.append((cat.name.lower().strip(), cat, len(cat.name.split())))

    # Longest phrase first
    candidates.sort(key=lambda x: (x[2], len(x[0])), reverse=True)

    matched_cats: Dict[int, Category] = {}
    detected_names: List[str] = []
    occupied_spans: List[Tuple[int, int]] = []

    for phrase, cat, word_count in candidates:
        if not phrase:
            continue
        p_pattern = rf"\b{re.escape(phrase)}\b"
        matched_m = list(re.finditer(p_pattern, text, re.IGNORECASE))
        if matched_m:
            for m in matched_m:
                start, end = m.span()
                overlap = any(max(start, o_start) < min(end, o_end) for o_start, o_end in occupied_spans)
                if not overlap:
                    occupied_spans.append((start, end))
                    if cat.id not in matched_cats:
                        matched_cats[cat.id] = cat
                        detected_names.append(cat.name)
        else:
            # Check stemmed match for single-word aliases on unoccupied spans
            p_words = [w for w in phrase.split() if w not in STOP_WORDS]
            if len(p_words) == 1:
                p_stem = light_stem(p_words[0])
                if len(p_stem) >= 4:
                    for m in re.finditer(r"\b\w+\b", text):
                        word = m.group(0).lower()
                        if word not in STOP_WORDS and light_stem(word) == p_stem:
                            start, end = m.span()
                            overlap = any(max(start, o_start) < min(end, o_end) for o_start, o_end in occupied_spans)
                            if not overlap:
                                occupied_spans.append((start, end))
                                if cat.id not in matched_cats:
                                    matched_cats[cat.id] = cat
                                    detected_names.append(cat.name)

    # Check stemmed set match for multi-word queries (e.g. 'organize photos' -> 'photo organizer')
    query_tokens = [t for t in text.lower().split() if t not in STOP_WORDS]
    query_stems = {light_stem(t) for t in query_tokens}
    if len(query_stems) >= 2:
        for phrase, cat, _ in candidates:
            p_tokens = [t for t in phrase.split() if t not in STOP_WORDS]
            p_stems = {light_stem(t) for t in p_tokens}
            if len(p_stems) >= 2 and p_stems.issubset(query_stems):
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


def search_fts_branch(db: Session, query_terms: List[str], limit: int = 25) -> List[Tuple[App, float]]:
    """Branch 1: Full-Text search on document title, summary, description, and capabilities."""
    if not query_terms:
        return []

    substantive = [t for t in query_terms if t not in STOP_WORDS]
    eval_terms = substantive if substantive else query_terms
    specific_terms = [t for t in eval_terms if t not in GENERIC_TERMS and light_stem(t) not in GENERIC_TERMS]

    apps = db.query(App).filter(App.is_delisted == False).all()
    results = []
    total_terms = len(eval_terms)

    for app in apps:
        name_words = set(re.findall(r"\w+", app.name.lower()))
        name_stems = {light_stem(w) for w in name_words}
        summary_words = set(re.findall(r"\w+", app.summary.lower()))
        summary_stems = {light_stem(w) for w in summary_words}
        desc_words = set(re.findall(r"\w+", app.description.lower()))
        desc_stems = {light_stem(w) for w in desc_words}

        cap_word_list = []
        for cap in app.capabilities:
            cap_w = set(re.findall(r"\w+", cap.capability.lower()))
            cap_s = {light_stem(w) for w in cap_w}
            cap_word_list.append((cap_w, cap_s))

        matched_term_count = 0
        specific_term_matches = 0
        score = 0.0

        for term in eval_terms:
            t_stem = light_stem(term)
            term_matched = False

            if term in name_words or t_stem in name_stems:
                score += 5.0
                term_matched = True
            if term in summary_words or t_stem in summary_stems:
                score += 3.0
                term_matched = True
            for cap_w, cap_s in cap_word_list:
                if term in cap_w or t_stem in cap_s:
                    score += 3.5
                    term_matched = True
                    break
            if term in desc_words or t_stem in desc_stems:
                score += 1.5
                term_matched = True

            if term_matched:
                matched_term_count += 1
                if term in specific_terms:
                    specific_term_matches += 1

        # Gating: If query has substantive specific terms, matching ONLY generic terms (like 'files') gives 0 score
        if specific_terms and specific_term_matches == 0:
            continue

        # Multi-word queries require meaningful term coverage
        if total_terms >= 2:
            coverage = matched_term_count / float(total_terms)
            has_name_match = any(t in name_words or light_stem(t) in name_stems for t in eval_terms)
            if coverage < 0.30 and not has_name_match:
                continue
            # Coordination factor: reward full coverage of query terms
            score = score * (0.4 + 0.6 * coverage)
            if matched_term_count == total_terms:
                score += 3.5

        if score > 0:
            results.append((app, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


def search_trigram_branch(db: Session, query_str: str, threshold: float = 0.35, limit: int = 25) -> List[Tuple[App, float]]:
    """Branch 2: Trigram similarity for typo-tolerance (threshold >= 0.35)."""
    if not query_str or len(query_str) < 3:
        return []

    words_in_q = [w for w in query_str.lower().split() if w not in STOP_WORDS]
    apps = db.query(App).filter(App.is_delisted == False).all()
    candidates = []

    for app in apps:
        max_sim = 0.0
        # Compare with app name
        sim_name = trigram_sim(query_str, app.name)
        max_sim = max(max_sim, sim_name)

        # Word-level comparisons against name, slug, and capabilities
        for w in words_in_q:
            if len(w) >= 3:
                sim_w_name = trigram_sim(w, app.name)
                max_sim = max(max_sim, sim_w_name)
                sim_w_slug = trigram_sim(w, app.slug)
                max_sim = max(max_sim, sim_w_slug)
                for cap in app.capabilities:
                    sim_cap = trigram_sim(w, cap.capability)
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
    2. Detect taxonomy categories and aliases with non-overlapping span extraction.
    3. Run 3 branches (FTS, Trigram, Vector), capped at 25 each.
    4. Reciprocal Rank Fusion (RRF) with primary category & compound capability match bonuses.
    5. Hard filtering by platform and license.
    6. Return deduplicated, scored results with evidence.
    """
    clean_query, detected_constraints = parse_query_constraints(raw_query)
    filter_platform = platform or detected_constraints.get("platform")
    filter_license = license_state or detected_constraints.get("license_state")

    matched_categories, detected_cat_names = match_categories_and_aliases(db, clean_query)
    specific_cat_ids = {c.id for c in matched_categories if c.parent_id is not None}
    broad_parent_cat_ids = {c.id for c in matched_categories if c.parent_id is None}
    all_matched_cat_ids = {c.id for c in matched_categories}

    # Expand broad parent categories to their children
    for cat in matched_categories:
        if cat.parent_id is None:
            for sub in cat.subcategories:
                all_matched_cat_ids.add(sub.id)

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

    is_broad_topic = len(eval_terms) <= 2 or any(clean_query == c.name.lower() for c in matched_categories)

    # 1. Category Matching & Affinity
    if all_matched_cat_ids:
        for app in db.query(App).filter(App.is_delisted == False).all():
            app_id = app.id
            app_primary_id = app.primary_category_id
            app_cat_ids = {ac.category_id for ac in app.categories}

            # Only consider apps that matched a retrieval branch OR when it's a broad topic search
            if app_id not in app_scores and not is_broad_topic:
                continue

            app_objects[app_id] = app
            if app_id not in app_scores:
                app_scores[app_id] = 0.0
                app_sources[app_id] = set()

            # Direct Specific Subcategory match on primary category
            if app_primary_id in specific_cat_ids:
                app_scores[app_id] += 0.048
                app_sources[app_id].add("primary_category_match")
            # Specific Subcategory match on secondary category
            elif specific_cat_ids.intersection(app_cat_ids):
                app_scores[app_id] += 0.022
                app_sources[app_id].add("secondary_category_match")
            # Broad Parent Category match on primary category
            elif app.primary_category and app.primary_category.parent_id in broad_parent_cat_ids:
                app_scores[app_id] += 0.038
                app_sources[app_id].add("broad_parent_primary_match")
            # Umbrella / Broad match
            elif all_matched_cat_ids.intersection(app_cat_ids | ({app_primary_id} if app_primary_id else set())):
                app_scores[app_id] += 0.015
                app_sources[app_id].add("category_match")

    # 2. Capability Matching: Direct Compound vs Incidental
    for app_id, app in app_objects.items():
        max_cap_terms = 0
        for cap in app.capabilities:
            cap_words = set(re.findall(r"\w+", cap.capability.lower()))
            cap_stems = {light_stem(w) for w in cap_words}
            matched_in_cap = sum(1 for t in eval_terms if t in cap_words or light_stem(t) in cap_stems)
            max_cap_terms = max(max_cap_terms, matched_in_cap)

        if max_cap_terms >= 2:
            # Direct Compound Capability match
            app_scores[app_id] += 0.055
            app_sources[app_id].add("direct_capability_match")
        elif max_cap_terms == 1:
            # Incidental capability match
            app_scores[app_id] += 0.015
            app_sources[app_id].add("capability_match")

    # 3. Named Entity / Typo Name Match Bonus
    for app_id, app in app_objects.items():
        app_name_lower = app.name.lower()
        app_slug = app.slug.lower()
        sim_full = trigram_sim(clean_query, app_name_lower)
        sim_words = max([trigram_sim(w, app_name_lower) for w in clean_query.split() if len(w) >= 3] + [0.0])
        sim_slug = max([trigram_sim(w, app_slug) for w in clean_query.split() if len(w) >= 3] + [0.0])
        best_name_sim = max(sim_full, sim_words, sim_slug)

        if best_name_sim >= 0.65:
            bonus = 0.045 * best_name_sim
            app_scores[app_id] += bonus
            app_sources[app_id].add("named_entity_match")

    # 4. Multi-term coverage bonus
    if len(eval_terms) >= 2:
        for app_id, app in app_objects.items():
            full_text = f"{app.name} {app.summary} {app.description}".lower()
            all_text_words = set(re.findall(r"\w+", full_text))
            all_text_stems = {light_stem(w) for w in all_text_words}
            for cap in app.capabilities:
                c_words = set(re.findall(r"\w+", cap.capability.lower()))
                all_text_words.update(c_words)
                all_text_stems.update({light_stem(w) for w in c_words})

            all_terms_matched = all(
                t in all_text_words or light_stem(t) in all_text_stems
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
        "matched_category_ids": list(all_matched_cat_ids),
        "applied_filters": {
            "platform": filter_platform,
            "license_state": filter_license,
        },
        "encoder_diagnostics": get_encoder_diagnostics(),
        "semantic_search_active": (get_embedding_encoder() is not None) and settings.ENABLE_VECTOR_SEARCH,
    }

    return filtered_results[:limit], metadata
