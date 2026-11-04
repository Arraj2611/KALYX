"""
KALYX Trading System - FastAPI Application Entry Point
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import yaml as _yaml
from app.config import settings
from app.control.router import router as control_router
from app.security import check_ws_token, require_api_key
from app.utils.logging import setup_logging
from app.data.database import init_db, close_db, SessionLocal
from app.data.redis_client import init_redis, close_redis, get_redis_client
from app.intelligence.registry import DataSourceRegistry
from app.intelligence.context import IntelligenceContextBuilder
from app.intelligence.correlation.engine import CorrelationEngine
from app.intelligence.correlation.adapters import (
    EquityDomainAdapter, CryptoDomainAdapter, ForexDomainAdapter, CrossMarketAdapter,
)
from app.intelligence.sentiment.finbert import FinBertSentiment
from app.intelligence.sources import (
    YFinanceSource,
    PolymarketSource,
    GdeltSource,
    NewsScraperSource,
    ScraplingSource,
)
from app.auth.router import router as auth_router
from app.strategies.router import router as strategies_router
from app.execution.router import router as execution_router, set_account_manager as set_execution_account_manager
from app.risk.router import router as risk_router, set_account_manager as set_risk_account_manager
from app.data.router import router as data_router
from app.agents.router import router as agents_router, set_pods
from app.decisions.router import router as decisions_router
from app.utils.scheduler import setup_scheduler, start_scheduler, shutdown_scheduler
from app.brokers.account_manager import AccountManager
from app.brokers.paper.adapter import PaperAdapter
from app.brokers.paper.prices import YahooPriceSource

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    logger.info("Starting KALYX Trading System...")
    logger.info(f"Version: {settings.APP_VERSION}")
    logger.info(f"Debug mode: {settings.DEBUG}")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize Redis
    await init_redis()
    logger.info("Redis initialized")

    # Initialize account manager
    account_manager = AccountManager()
    config = None
    config_path = os.path.join(os.path.dirname(__file__), "..", settings.ACCOUNTS_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
            for name, acct in config.get("accounts", {}).items():
                if acct.get("broker") == "paper":
                    paper_cfg = acct.get("config", {})
                    price_source = (
                        YahooPriceSource(paper_cfg["price_symbols"])
                        if paper_cfg.get("price_symbols")
                        else None
                    )
                    adapter = PaperAdapter(config=paper_cfg, price_source=price_source)
                    account_manager.register(name, adapter, acct)
            logger.info(f"Loaded accounts config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load accounts config: {e}. Falling back to paper_test.")
            account_manager.register("paper_test", PaperAdapter(), {"broker": "paper"})
    else:
        account_manager.register("paper_test", PaperAdapter(), {"broker": "paper"})

    logger.info(f"AccountManager: {len(account_manager.get_account_names())} accounts registered")
    set_execution_account_manager(account_manager)
    set_risk_account_manager(account_manager)

    # Initialize intelligence layer (SP3) — opt-in via INTELLIGENCE_ENABLED
    intelligence_builder = None
    if settings.INTELLIGENCE_ENABLED:
        try:
            intel_config_path = os.path.join(os.path.dirname(__file__), "..", settings.INTELLIGENCE_CONFIG_PATH)
            with open(intel_config_path, "r", encoding="utf-8") as f:
                intel_config = _yaml.safe_load(f) or {}

            registry = DataSourceRegistry(intel_config)
            registry.register(ScraplingSource())
            registry.register(YFinanceSource())
            registry.register(PolymarketSource())
            registry.register(GdeltSource())
            registry.register(NewsScraperSource())

            engine = CorrelationEngine()
            engine.register_adapter(EquityDomainAdapter())
            engine.register_adapter(CryptoDomainAdapter())
            engine.register_adapter(ForexDomainAdapter())
            engine.register_adapter(CrossMarketAdapter())

            sentiment = FinBertSentiment()
            redis_client = get_redis_client()

            intelligence_builder = IntelligenceContextBuilder(
                registry=registry,
                correlation_engine=engine,
                sentiment=sentiment,
                redis_client=redis_client,
                cache_ttl_seconds=60,
            )
            logger.info("Intelligence layer initialised")
        except Exception as exc:
            logger.error(f"Intelligence layer init failed: {exc}")
            intelligence_builder = None

    # Initialize agent pods for accounts with agents enabled
    from app.agents.pod import AgentPod

    agent_pods = {}
    if os.path.exists(config_path):
        for name in account_manager.get_account_names():
            adapter = account_manager.get_adapter(name)
            acct_config = config.get("accounts", {}).get(name, {}) if config else {}
            if acct_config.get("agents", {}).get("enabled", False):
                try:
                    db_session = SessionLocal()
                    pod = AgentPod(
                        account_name=name,
                        adapter=adapter,
                        config=acct_config,
                        db=db_session,
                        alert_service=None,
                        intelligence_builder=intelligence_builder,
                    )
                    agent_pods[name] = pod
                    logger.info(f"Agent pod created: {name}")
                except Exception as e:
                    logger.error(f"Failed to create agent pod {name}: {e}")

    set_pods(agent_pods)
    logger.info(f"Agent pods initialized: {len(agent_pods)}")

    # Setup and start scheduler
    setup_scheduler()
    start_scheduler()
    logger.info("Scheduler started")

    yield

    # Shutdown scheduler
    shutdown_scheduler()

    # Shutdown
    logger.info("Shutting down KALYX Trading System...")
    await close_db()
    await close_redis()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Automated Index Options Trading System",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "service": settings.APP_NAME
    }


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    """WebSocket endpoint for real-time updates. Needs ?token=<CONTROL_API_KEY>."""
    if not check_ws_token(token):
        await websocket.close(code=1008)
        return
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo back or process message
            await websocket.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")


# API routers
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"], dependencies=[Depends(require_api_key)])
app.include_router(strategies_router, prefix="/api/strategies", tags=["Strategies"], dependencies=[Depends(require_api_key)])
app.include_router(execution_router, prefix="/api/execution", tags=["Execution"], dependencies=[Depends(require_api_key)])
app.include_router(risk_router, prefix="/api/risk", tags=["Risk Management"], dependencies=[Depends(require_api_key)])
app.include_router(data_router, prefix="/api/data", tags=["Data"], dependencies=[Depends(require_api_key)])
app.include_router(agents_router, prefix="/api/agents", tags=["AI Agents"], dependencies=[Depends(require_api_key)])
app.include_router(decisions_router, prefix="/api/decisions", tags=["Decisions"], dependencies=[Depends(require_api_key)])
app.include_router(control_router, prefix="/api/control", tags=["Control"], dependencies=[Depends(require_api_key)])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
