# KALYX - Automated Index Options Trading System

An elite, production-grade automated trading system for index options using Zerodha Kite Connect API.

## Features

- **Live Trading**: Automated order execution with Zerodha Kite Connect
- **Strategy Engine**: Plugin-based strategy system with import/export
- **Backtesting**: Historical data backtesting with comprehensive metrics
- **Risk Management**: Capital usage limits, daily loss limits, circuit breakers
- **Real-time Monitoring**: Live dashboard with WebSocket updates
- **AI Agents**: Market analysis, strategy critique, trade explanation
- **Dark UI**: Sleek, modern dark-themed interface

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

