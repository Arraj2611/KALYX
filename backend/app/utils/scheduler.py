"""
Task scheduler using APScheduler.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.auth.service import AuthService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def refresh_token_job():
    """Job to refresh Zerodha access token."""
    try:
        auth_service = AuthService()
        await auth_service.refresh_token()
        logger.info("Token refresh job executed")
    except Exception as e:
        logger.error(f"Token refresh job failed: {e}", exc_info=True)


def setup_scheduler():
    """Setup scheduled tasks."""
    # Schedule token refresh (if needed - Zerodha tokens typically last 24 hours)
    # This is a placeholder - adjust based on actual token expiry
    # scheduler.add_job(
    #     refresh_token_job,
    #     trigger=CronTrigger(hour=0, minute=0),  # Daily at midnight
    #     id="refresh_token",
    #     replace_existing=True
    # )
    
    logger.info("Scheduler setup complete")


def start_scheduler():
    """Start the scheduler."""
    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler shut down")

