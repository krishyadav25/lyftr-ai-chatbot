# Lyftr AI Chatbot - LLM Chatbot with Key Failover and Response Caching

A full-stack AI chatbot featuring LiteLLM multi-key failover, built-in response caching, SQLite multi-turn session persistence, and per-request token usage tracking.

---

## 1. Live URLs
*(Populate after deploying to Vercel and Render)*
- **Frontend URL (Vercel):** TBD
- **Backend URL (Render):** TBD

---

## 2. Run Locally: With Docker and Without

### Prerequisites
- Node.js (v18+) & npm
- Python (v3.12+)
- Docker & Docker Compose (for containerized run)

### Environment Setup
Copy `.env.example` to `.env` at the repository root and add at least two Gemini API keys:
```bash
cp .env.example .env
```

### With Docker
```bash
# Build and start backend (http://localhost:8000) and frontend (http://localhost:3000)
make up

# Stop and remove containers (SQLite data persists in named volume lyftr_sqlite_data)
make down
```

### Without Docker (Local Development)

#### 1. Backend
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000`.

---

## 3. Design Decisions: Key Fallback, Caching, SQLite Session Storage

- **Key Pool & Failover (`backend/app/llm_service.py`):** Keys from `LLM_API_KEYS` are assigned sequential IDs (`key_1`, `key_2`, ...). Requests try `key_1` first and automatically fail over on HTTP `429`, quota exhaustion, or retryable `5xx` errors (`500`, `502`, `503`, `504`, timeouts). `fallback_attempts` and winning `key_id` are returned in metadata. If all keys fail, the API returns HTTP `503` (`{"detail": "all providers unavailable"}`) without mutating SQLite history.
- **Response Caching:** Uses LiteLLM's built-in local in-memory cache (`litellm.caching.Cache(type="local", max_messages=None)`) initialized on startup. `max_messages=None` ensures multi-turn conversations of any length remain cacheable. Cache keys hash the model and full effective message list (`system` + `history` + `user`) while excluding `api_key`, so failover does not fragment cache identity. Cache hits are detected via LiteLLM's `_hidden_params["cache_hit"]` flag and return `resolution_source: "LLM_CACHE"`, `key_id: null`, `fallback_attempts: 0`, and preserved token counts. Active `X-Simulate-Failure` requests pass `cache={"no-cache": True, "no-store": True}` so cache hits cannot bypass simulated failures.
- **SQLite Session Storage (`backend/app/database.py`):** Uses `aiosqlite` with automatic schema and `session_id` index creation on startup. Failed requests (`422`, `503`) never write partial turns.

---

## 4. Verification: How to See Failover, Cache Hits and Per-Message Token Usage

1. **Health Check:**
   ```bash
   curl http://localhost:8000/health
   ```
2. **Live Inference vs. Cache Hit:**
   ```bash
   # Request 1 -> resolution_source: LIVE_INFERENCE, key_id: key_1
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id":"demo-1","message":"What is the capital of France?"}'

   # Request 2 (new session, identical first message) -> resolution_source: LLM_CACHE, key_id: null
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id":"demo-2","message":"What is the capital of France?"}'
   ```
3. **Failover Simulation (requires `ENABLE_FAILURE_SIMULATION=true`):**
   ```bash
   # Simulates key_1 returning 429 -> fails over to key_2 (fallback_attempts: 1)
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: key_1=429" \
     -d '{"session_id":"demo-3","message":"What is the capital of France?"}'

   # Simulates all keys failing -> HTTP 503 {"detail":"all providers unavailable"}
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: *=429" \
     -d '{"session_id":"demo-4","message":"What is the capital of France?"}'
   ```
4. **Per-Message Token Usage:** Shown in the UI metadata bar (`In` / `Out`) beneath each assistant reply and returned in `metadata.input_tokens` and `metadata.output_tokens`.

---

## 5. Setup Used: Your Editor and AI Tools

- **Editor / IDE:** VS Code / Antigravity
- **AI Tools:** Antigravity AI coding assistant
- **Stack:** React (Vite), Python (FastAPI, LiteLLM, aiosqlite), SQLite, Pytest, Docker

---

## 6. Bonus Features (If Any): What You Added Beyond the Requirements and Why

- **Collapsible System Prompt Editor (`data-testid="system-prompt-input"`):** Allows testing custom system instructions per session and observing cache isolation when system prompts change.
- **Live Gateway Health Indicator:** Displays backend reachability, configured key count, and cache state in the sidebar.
- **Suggested Prompts & Responsive Mobile Drawer:** Improves first-load UX and usability across desktop and mobile viewports.
