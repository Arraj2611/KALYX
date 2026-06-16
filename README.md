# KALYX — Autonomous Multi-Market AI Trading Platform

KALYX is an autonomous, multi-broker, multi-asset trading platform. A broker-abstraction
layer (Zerodha, Groww, Paper) feeds per-account AI agent pods (analyst → debate → guardian →
executor → memory → strategist) enriched by a multi-source intelligence layer (market data,
news/sentiment, prediction-market odds, geopolitical events, cross-market correlation).
Every decision — including trades **not** taken — is logged with full reasoning for a
self-improving learning loop.

## Features

- **Multi-broker execution**: unified `BrokerAdapter` over Zerodha, Groww, and a Paper simulator
- **Per-account agent pods**: analyst, bull/bear debate + judge, math-based guardian, executor, memory, overnight strategist
- **Intelligence layer**: 6+ data sources with vendor fallback, FinBERT sentiment, composite signal-quality scoring, cross-market convergence detection
- **Decision log + hindsight**: every signal/skip/block recorded; outcomes filled post-session to drive learning
- **Two-tier local LLM**: Ollama quick/deep routing — near-zero inference cost for 24/7 loops
- **Risk management**: capital/loss/trade limits, circuit breakers, paper-mode default

## Tech Stack

### Backend
- Python 3.10+
- FastAPI
- PostgreSQL
- Redis
- Zerodha Kite Connect SDK
- APScheduler

### Frontend
- Next.js 14+
- TypeScript
- TailwindCSS
- ShadCN UI
- Recharts / TradingView Lightweight Charts

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+
- Zerodha Kite Connect API credentials

### Backend Setup

1. Create virtual environment:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Start PostgreSQL and Redis (using Docker):
```bash
cd docker
docker-compose up -d
```

5. Run database migrations:
```bash
# Alembic migrations will be created automatically on first run
```

6. Start the backend server:
```bash
cd backend
uvicorn app.main:app --reload
```

### Frontend Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Set up environment variables:
```bash
# Create .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

3. Start the development server:
```bash
npm run dev
```

## Usage

### Authentication

1. Get request token from Zerodha:
   - Visit: https://kite.trade/connect/login?api_key=YOUR_API_KEY
   - Login and authorize
   - Copy the request_token from redirect URL

2. Login via API:
```bash
POST /api/auth/login
{
  "request_token": "your_request_token"
}
```

### Strategy Management

- Create strategies via API or UI
- Import/export strategies as JSON
- Activate/deactivate strategies
- Run backtests on historical data

### Trading

- Strategies execute automatically when active
- Orders are placed via execution engine
- Risk limits are enforced automatically
- Circuit breaker activates on breaches

## Project Structure

```
KALYX/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── auth/
│   │   ├── strategies/
│   │   ├── execution/
│   │   ├── risk/
│   │   ├── data/
│   │   ├── agents/
│   │   └── utils/
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
└── docker/
    └── docker-compose.yml
```

## License

Proprietary - All rights reserved

