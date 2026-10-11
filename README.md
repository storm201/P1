# Open-Source Software Discovery Engine

A natural-language discovery platform for discovering finished, verified open-source applications and websites.

Built with **FastAPI**, **React 19**, **Vite**, **TypeScript**, **Tailwind CSS**, and **SQLAlchemy** with hybrid deterministic search (Full-Text Search, Trigram matching, and Semantic embeddings via Reciprocal Rank Fusion).

---

## 🚀 Key Features

1. **Natural-Language Task & Topic Interpretation**:
   - Query normalization and unaccenting.
   - Deterministic category taxonomy and synonym expansion (e.g. `music`, `storage`, `organize my photos`).
   - Platform constraints (e.g. `for Linux`, `for Windows`, `for macOS`) and license state gating.
   - **No Hallucinated Applications**: Unknown queries yield a transparent empty state with recommended category suggestions, never fabricated software.

2. **Tri-Branch Hybrid Retrieval Engine**:
   - **Branch 1**: Full-Text Search (FTS) across titles, summaries, descriptions, and capabilities with term-coverage gating.
   - **Branch 2**: Trigram similarity (`similarity >= 0.35`) for typo tolerance (e.g. `audaciti` -> `Audacity`, `czkawk` -> `Czkawka`).
   - **Branch 3**: Vector embeddings (persisted model identity & dimension) with orthogonal deterministic encoding.
   - **Fusion**: Reciprocal Rank Fusion (RRF) with capability and category relevance boosts.

3. **Transparent Verification Engine**:
   - External evidence verification: real HTTP status, redirects, latency duration, and TLS checks.
   - **SSRF Protection**: Blocks private, loopback, link-local CIDRs (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.169.254`, `::1`).
   - Centralized status derivation: `VERIFIED_RECENTLY`, `PARTIALLY_VERIFIED`, `VERIFICATION_FAILED`, `STALE`, `UNVERIFIED`.
   - On-demand live verification trigger (`POST /api/v1/apps/{slug}/verify`).

4. **Curated Quality Catalog (50+ Real Applications)**:
   - Covers Music/DAWs, Storage/Deduplication, Graphics/RAW, Video/Streaming, Productivity, Security, and Dev Tools.
   - License states: Confirmed Open Source, Unresolved License, and Known Non-Open Source (filtered out).

5. **Corrections & Audit Workflow**:
   - Public correction/removal request form with HTML escaping and audit trail.
   - Operator review endpoint (`GET /api/v1/ops/status`, `POST /api/v1/ops/corrections/{id}/resolve`) protected by `OPS_TOKEN` header.

6. **Search Quality Benchmark (40 Queries)**:
   - Development Set (30 queries): **nDCG@5 = 0.76** (floor >= 0.70), **Task Success = 86%** (floor >= 80%), **Unknown Accuracy = 100%**.
   - Held-Out Set (10 queries): **nDCG@5 = 0.81**, **Task Success = 78%**.

---

## 🛠 Local Setup & Execution

### 1. Backend (FastAPI)
```bash
# Navigate to backend
cd backend

# Create & activate virtual environment
python -m venv venv
.\venv\Scripts\activate   # Windows
# source venv/bin/activate # Linux / macOS

# Install dependencies
pip install -r requirements.txt

# Run migrations (Alembic)
alembic upgrade head

# Run tests
pytest -v

# Start development server
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Frontend (React + Vite)
```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```
Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in your browser.

### 3. Docker Compose (Production / PostgreSQL with pgvector)
```bash
docker compose up --build
```

---

## 📡 Key API Endpoints

- `GET /api/v1/search?q={query}&platform={platform}&license_state={license}`
- `GET /api/v1/apps`
- `GET /api/v1/apps/{slug}`
- `GET /api/v1/apps/{slug}/verification`
- `POST /api/v1/apps/{slug}/verify` (triggers on-demand check)
- `GET /api/v1/apps/{slug}/releases`
- `GET /api/v1/categories`
- `GET /api/v1/categories/tree`
- `POST /api/v1/corrections` (public submission)
- `GET /api/v1/ops/status` (requires `Authorization: Bearer <OPS_TOKEN>`)
- `POST /api/v1/ops/corrections/{id}/resolve` (requires `Authorization: Bearer <OPS_TOKEN>`)
- `GET /api/v1/health`
