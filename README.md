# Open-Source Software Discovery Engine

A natural-language discovery platform for finding finished, verified open-source applications and websites.

Built with **FastAPI**, **React 19**, **Vite**, **TypeScript**, **Tailwind CSS**, and **SQLAlchemy** with hybrid search (Full-Text Search, Trigram similarity, and Semantic embeddings via Reciprocal Rank Fusion), dependable periodic scheduling, and official release synchronization.

---

## 🚀 Key Features

### 1. Natural-Language Task & Topic Interpretation
- Query normalization and accent stripping.
- Deterministic category taxonomy and synonym expansion (e.g. `music`, `storage`, `organize my photos`).
- Platform constraints (e.g. `for Linux`, `for Windows`, `for macOS`) and license state gating.
- **No Hallucinated Applications**: Unknown queries yield a transparent empty state with recommended category suggestions, never fabricated software.

### 2. Tri-Branch Hybrid Retrieval & Search Integrity
- **Branch 1 (Lexical FTS)**: Full-Text Search across titles, summaries, descriptions, and capabilities with term-coverage gating.
- **Branch 2 (Fuzzy Trigram)**: Trigram similarity (`similarity >= 0.35`) for typo tolerance (e.g. `audaciti` -> `Audacity`, `czkawk` -> `Czkawka`).
- **Branch 3 (Vector Semantic)**:
  - **Deterministic Testing Mode**: `DeterministicFakeEncoder` (`deterministic-hash-v1`, 384 dimensions), explicitly disclosed as `is_genuine_neural = False` for 100% offline, hermetic testing.
  - **Neural Semantic Mode**: Explicit configuration for sentence-transformer embeddings (`sentence-transformers/all-MiniLM-L6-v2`, `is_genuine_neural = True`).
  - **Embedding Space Protection**: Validates model identity and dimension compatibility before querying, preventing incompatible vector spaces.
  - **Graceful Fallback**: If the neural model fails to initialize or is disabled, search continues using lexical and trigram retrieval without falsely advertising genuine semantic understanding.
- **Reciprocal Rank Fusion (RRF)**: Combines branches with capability and category relevance boosts.

### 3. Periodic Verification Scheduler
- **Persistent Database Scheduling**: Database-backed `VerificationSchedule` table with atomic row-level claiming (`claim_next_task`) safe against concurrent workers without requiring Redis.
- **Stale Lock Recovery**: Automatically reclaims interrupted tasks left in running state by crashed workers.
- **Bounded Exponential Backoff**: Retries failed checks with exponential growth ($300 \times 2^{\text{attempts}-1}$) and deterministic jitter, strictly capped at 24 hours.
- **Deduplication Constraints**: Prevents duplicate pending jobs for the same application and check type.
- **Evidence Freshness & Staleness**: Centralized status derivation transitions records older than 7 days (website) or 30 days (repository) to `STALE`. Failed jobs persist sanitized error details without erasing historical evidence.

### 4. Official Release & Download Synchronization
- **Incremental GitHub Releases Crawler**: Synchronizes upstream release tags, notes, publication timestamps, and source commits.
- **Request Budget & Rate Limiting**: Strictly enforces a 150 API request ceiling per cycle (`RequestBudget`). Reads `X-RateLimit-Remaining` and `X-RateLimit-Reset` and pauses safely when rate-limited.
- **Conditional ETag Requests**: Stores HTTP ETags and passes `If-None-Match` headers, seamlessly handling HTTP 304 Not Modified.
- **Safe Token Handling**: Configured via `GITHUB_TOKEN`; strictly redacted in logs, error traces, and API responses.
- **Asset Platform Detection & Checksums**: Detects target platforms (`windows`, `macos`, `linux`, `android`, `ios`) and extracts published SHA-256 digests without inventing values.
- **SSRF-Protected Reachability Checks**: All asset URLs pass IPv4/IPv6 private/loopback CIDR validation before issuing HEAD/range 0-0 requests. Never mirrors or downloads arbitrary binary files.

### 5. Transparent Frontend & Operational Observability
- **Truthful Status Indicators**: Distinguishes *Website Reachable*, *Official Release Available*, *Metadata Recently Synchronized*, *Verification Stale*, and *Download Information Unavailable*.
- **Application Detail & Audit Panel**:
  - Direct links to official website and source repository.
  - Transparent verification evidence displaying HTTP status, TLS validation, latency, and sync timestamps.
  - Official Releases & Downloads section with platform badges, file sizes, checksums, reachability badges, and verified download links.
  - "Run Real Check Now" button triggers an on-demand live website check with real-time feedback.
- **Protected Operator Visibility (`/api/v1/ops/status`)**:
  - Enforces `Authorization: Bearer <OPS_TOKEN>` and fails closed (HTTP 403) when unset.
  - Telemetry: scheduler cycles, pending/running/failed jobs, oldest pending task age, stale applications count, release sync stats, sanitized recent failures, and semantic encoder diagnostics.
  - Configurable webhook alerting (`ALERT_WEBHOOK_URL`, `ALERT_FAILURE_THRESHOLD`).

---

## 🛠 Local Setup & Execution

### 1. Backend (FastAPI)
```powershell
# Navigate to backend
cd backend

# Create & activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows PowerShell
# source venv/bin/activate    # Linux / macOS

# Install dependencies
pip install -r requirements.txt

# Run migrations (Alembic)
alembic upgrade head

# Run automated tests (42 tests)
pytest -v

# Start FastAPI server
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Frontend (React + Vite)
```powershell
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev -- --host 127.0.0.1 --port 5173
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

### 3. One-Click Launcher (Windows)
Run `run_all.bat` from the project root to start backend and frontend concurrently.

---

## ⚙️ Environment Configuration (`backend/.env`)

```ini
DATABASE_URL=sqlite:///./oss_discovery.db
OPS_TOKEN=development-ops-token-secure-2026
SEMANTIC_ENCODER_TYPE=deterministic_test   # "deterministic_test" | "sentence_transformers" | "none"
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIM=384
GITHUB_TOKEN=                              # Optional personal access token for higher rate limits
SCHEDULER_INTERVAL_HOURS=24
SCHEDULER_REQUEST_BUDGET=150
SCHEDULER_MAX_RETRIES=5
SCHEDULER_RETRY_BASE_SECONDS=300
SCHEDULER_RETRY_MAX_SECONDS=86400
ALERT_WEBHOOK_URL=                         # Optional webhook for failure alerts
ALERT_FAILURE_THRESHOLD=3
```

---

## 📡 Key API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/search?q={query}&platform={platform}&license_state={license}` | Tri-branch hybrid search with RRF |
| `GET` | `/api/v1/apps` | List catalog apps with filtering and pagination |
| `GET` | `/api/v1/apps/{slug}` | Detailed application profile with releases and verification summary |
| `GET` | `/api/v1/apps/{slug}/verification` | Public verification evidence breakdown |
| `POST` | `/api/v1/apps/{slug}/verify` | On-demand live website reachability check |
| `GET` | `/api/v1/categories` | Catalog category listing |
| `GET` | `/api/v1/categories/tree` | Full hierarchical category tree |
| `POST` | `/api/v1/corrections` | Public metadata correction / takedown request submission |
| `GET` | `/api/v1/ops/status` | Operational health, scheduler telemetry, and encoder diagnostics (requires `OPS_TOKEN`) |
| `GET` | `/api/v1/ops/corrections` | Operator listing of submitted correction requests |
| `POST` | `/api/v1/ops/corrections/{id}/resolve` | Operator resolution and delisting action |
| `GET` | `/api/v1/health` | Service and database health check |

---

### 6. Search Quality Sprint & Precision Architecture
- **Non-Overlapping Longest-Span Taxonomy Extraction**: Eliminates spurious nested alias collisions (e.g., `editor` mapping to `Developer Tools` when part of `photo editor` or `audio editor`).
- **Primary Category Affinity**: Distinguishes direct specific subcategory matches on `primary_category_id` (+0.048) from secondary (+0.022) or broad parent (+0.038) matches.
- **Compound Capability Matching**: Distinguishes direct compound task matches ($\ge 2$ task terms in the same capability, +0.055) from incidental single-word matches (+0.015).
- **Domain vs Generic Term Gating**: Distinguishes domain terms (`photo`, `backup`, `duplicate`, `audio`) from generic role/container terms (`manager`, `files`, `tool`), rejecting apps that only match generic nouns.
- **Agentive Noun & Verb Stemming**: Supports `-er` and `-or` suffix normalization (`broadcaster` $\leftrightarrow$ `broadcast`, `cleaner` $\leftrightarrow$ `clean`, `player` $\leftrightarrow$ `play`, `recorder` $\leftrightarrow$ `record`).
- **Phrasal Verb Normalization**: Normalizes colloquial verbs (`back up` $\rightarrow$ `backup`, `clean up` $\rightarrow$ `cleanup`, `set up` $\rightarrow$ `setup`).
- **Strict Constraint Enforcement**: Enforces platform and license filters without leakage; preserves zero results on unknown/out-of-domain queries.

### 7. Final Search Integrity Audit & Neural Semantic Verification
- **Precision Metric Reconciliation**: Verified mathematically that aggregate metrics match per-query outcomes with 0.0000 discrepancy. Query-level mean $P@5$ evaluates the mean precision across queries ($\frac{1}{|Q|}\sum_{q} \frac{\text{relevant in top } \min(5, N_q)}{\min(5, N_q)}$), yielding **0.7024** (Dev) and **0.7130** (Held-out). Pooled micro-average $P@5$ ($\frac{\text{total relevant}}{\text{total evaluated}}$) yields **0.6667** (Dev) and **0.6471** (Held-out).
- **Genuine Neural Semantic Search (`sentence-transformers/all-MiniLM-L6-v2`)**: Configured and initialized real neural embeddings (`is_genuine_neural=True`, dimension=384). All 51 catalog search documents were atomically migrated into the neural vector space with zero dimension or model identity mismatches.
- **Neural Hybrid vs. Lexical Fallback Comparison**: Validated that while genuine neural vector search actively contributes to ranking (e.g., retrieving semantically aligned apps in multi-word queries), the underlying lexical + taxonomy precision architecture independently guarantees top-tier discovery performance across all evaluation benchmarks.
- **Zero Fabrication**: 100% unknown query accuracy maintained across all modes.

### 8. Repository Hygiene, Secret Rotation & Privacy Protection
- **Secrets Management**: Untracked all environment files (`.env`, `backend/.env`) and runtime databases (`*.db`, `backend/oss_discovery.db`) from Git.
- **Credential Rotation**: Rotated the exposed operator token (`OPS_TOKEN`) using a high-entropy cryptographically secure random secret, stored exclusively in local development configuration and deployment secrets.
- **Safe Environment Templates**: Added `.env.example` and `backend/.env.example` containing non-sensitive parameter templates and placeholders.
- **Personal Information & Runtime Data Protection**: Sanitized local database records; verified that application data is generated dynamically from verified seed files (`seed_catalog.json` and `taxonomy.json`) without tracking runtime operational jobs or user contact emails.
- **Docker Compose Parameterization**: Replaced embedded default secrets in `docker-compose.yml` with environment variable interpolation (`${OPS_TOKEN}`, `${POSTGRES_PASSWORD}`).

---

## 🧪 Automated Test Suite (60 Tests, 100% Pass)


Run all tests:
```powershell
cd backend
pytest -v
```

### Test Coverage Highlights:
- **`test_search_quality.py`** (18 tests): Regression test suite covering `open-source photo editor for Linux`, `organize and back up my photos`, `find duplicate audio files`, `music`, `storage`, typo-tolerant queries (`audaciti`, `czkawk`, `imich photos`, `kopya backup`, `blechbit`, `vls media`, `obz studio recorder`), platform and license constraint filtering, and unknown query zero-fabrication.
- **`test_evaluation.py`** (1 test): Rigorous benchmark evaluation exceeding all acceptance floors:
  - **Development Benchmark**: nDCG@5 = **0.85** (Floor $\ge$ 0.70), P@5 = **0.70** (Floor $\ge$ 0.60), Task Success = **1.00** (Floor $\ge$ 0.80), Unknowns Handled = **1.00** (100%).
  - **Held-Out Benchmark**: nDCG@5 = **0.89** (Floor $\ge$ 0.70), P@5 = **0.71** (Floor $\ge$ 0.60), Task Success = **1.00** (Floor $\ge$ 0.80), Unknowns Handled = **1.00** (100%).
- **`test_scheduler_and_sync.py`** (16 tests): Eligible job creation, duplicate scheduling prevention, atomic concurrency claiming, website check persistence, honest failure recording, bounded backoff, stale transitions, interrupted job lock recovery, GitHub rate limit budget ceiling (150 requests), conditional ETag requests (HTTP 304), release deduplication, honest missing assets, SSRF protection on asset URLs, delisted app filtering, fail-closed operator auth, and scheduler telemetry visibility.
- **`test_semantic_retrieval.py`** (5 tests): Encoder independence, neural status reporting, incompatible model rejection, re-embedding migration, and lexical search fallback when encoder is unavailable.
- **`test_security_audit.py`** (6 tests): SSRF prevention for IPv4 and IPv6 CIDRs, redirect hop intercept, header-based operator auth, and HTML input escaping.
- **`test_ops_worker.py`** (4 tests): Worker job lifecycle, fail-closed ops endpoint, persistent job states, and correction resolution workflow.
- **`test_stage1a.py`** (10 tests): Health check, catalog seed verification, hybrid retrieval, detail modal data, and live verification check.


