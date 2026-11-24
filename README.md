# Lyftr AI Chatbot - LLM Chatbot with Key Failover and Response Caching

A resilient full-stack AI chatbot application featuring LiteLLM-based multi-key failover, automated response caching, session-based multi-turn memory in SQLite, and per-request token usage tracking.

---

## 1. Live URLs
*(To be populated after live deployment)*
- **Frontend URL:** TBD
- **Backend URL:** TBD

---

## 2. Run Locally: With Docker and Without

### Prerequisites
- Node.js (v18+) & npm
- Python (v3.11+)
- Docker & Docker Compose (optional for containerized execution)

### Without Docker (Local Development)

#### 1. Backend Setup
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
cp ../.env.example .env
# Edit .env to add your LLM API keys
uvicorn app.main:app --reload --port 8000
```

#### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### With Docker
```bash
# Start both backend (http://localhost:8000) and frontend (http://localhost:3000)
make up

# Stop services
make down
```

---

## 3. Design Decisions: Key Fallback, Caching, SQLite Session Storage

- **Key Pool & Fallback:** Configure LiteLLM with a sequence of API keys (`key_1`, `key_2`, ...). Upon receiving HTTP 429, quota exhaustion, or 5xx server errors, the gateway automatically falls back to the next available key without exposing errors to the user.
- **Failover Simulation Hook:** Supported via `X-Simulate-Failure` request header when `ENABLE_FAILURE_SIMULATION=true` is enabled on the backend.
- **Response Caching:** Built-in LiteLLM caching (in-memory/disk) hashed against the model and complete message context (system prompt + history + current message). Returns `LLM_CACHE` on cache hit and `LIVE_INFERENCE` on novel generation.
- **SQLite Storage:** Persistent session history stored in SQLite with schema migrations, mounted to a Docker volume (`/data`) to survive container restarts.

---

## 4. Verification: How to See Failover, Cache Hits and Per-Message Token Usage

- **Cache Hits:** Send identical prompts in identical conversation contexts to observe `resolution_source: LLM_CACHE` with lower latency and cached token metrics.
- **Failover Simulation:** Pass header `X-Simulate-Failure: key_1=429` to observe automatic transition to `key_2`.
- **Token Usage:** Real-time prompt (`input_tokens`) and completion (`output_tokens`) displayed alongside each assistant response in the UI.

---

## 5. Setup Used: Your Editor and AI Tools

- **Frontend:** React (Vite)
- **Backend:** Python, FastAPI, LiteLLM, aiosqlite
- **Testing:** Pytest, pytest-asyncio, HTTPX
- **Containerization:** Docker, Docker Compose, Multi-stage builds

---

## 6. Bonus Features (If Any): What You Added Beyond the Requirements and Why

*(To be populated as incremental features are added)*
