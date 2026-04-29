"""
Structured logging configuration for KALYX.
"""
import logging
import os
import sys
import json
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any

from app.config import settings


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        
        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Text formatter for human-readable logs."""
    
    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


def setup_logging():
    """Configure logging for the application."""
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Set formatter
    if settings.LOG_FORMAT == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set levels for third-party loggers
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("kiteconnect").setLevel(logging.INFO)


def setup_account_logger(account_name: str, log_base_dir: str = "logs") -> None:
    """Set up per-account log files with daily rotation."""
    account_dir = os.path.join(log_base_dir, "accounts", account_name)
    os.makedirs(account_dir, exist_ok=True)

    log_types = ["decisions", "trades", "agent", "ws"]
    for log_type in log_types:
        logger_name = f"kalyx.{account_name}.{log_type}"
        acct_logger = logging.getLogger(logger_name)

        # Skip if handlers already attached (avoid duplicates on re-init)
        if acct_logger.handlers:
            continue

        acct_logger.setLevel(logging.INFO)
        acct_logger.propagate = False  # don't bubble to root

        handler = TimedRotatingFileHandler(
            filename=os.path.join(account_dir, f"{log_type}.log"),
            when="midnight",
            interval=1,
            backupCount=90,
            encoding="utf-8",
        )
        handler.setFormatter(JSONFormatter())
        acct_logger.addHandler(handler)


def setup_system_logging(log_base_dir: str = "logs") -> None:
    """Set up system-level log files."""
    for subdir in ["system", "orchestrator", "performance"]:
        os.makedirs(os.path.join(log_base_dir, subdir), exist_ok=True)

    # System error log
    error_logger = logging.getLogger("kalyx.errors")
    if not error_logger.handlers:
        error_logger.setLevel(logging.ERROR)
        error_logger.propagate = False
        handler = TimedRotatingFileHandler(
            filename=os.path.join(log_base_dir, "system", "error.log"),
            when="midnight", interval=1, backupCount=180, encoding="utf-8",
        )
        handler.setFormatter(JSONFormatter())
        error_logger.addHandler(handler)

