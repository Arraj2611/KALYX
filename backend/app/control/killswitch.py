"""Kill switch: stop all new risk, globally or for one account.

State lives in the database, so it survives restarts and any process (pods, API, future fleet
workers) sees it. Reads fail closed: if the state cannot be read, new entries are treated as
halted. Exits, stops and flatten are never blocked by the switch.
"""

import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.control.models import ControlFlag

logger = logging.getLogger(__name__)

GLOBAL_KEY = "halt:all"
ACCOUNT_PREFIX = "halt:account:"


def _key(scope: str) -> str:
    scope = scope.strip()
    return GLOBAL_KEY if scope.lower() == "all" else f"{ACCOUNT_PREFIX}{scope}"


class KillSwitch:
    def __init__(self, session_provider: Callable[[], Session]) -> None:
        self._provider = session_provider

    def is_halted(self, account: str) -> bool:
        """True when a global or account halt is on, or when the state cannot be read."""
        session: Optional[Session] = None
        try:
            session = self._provider()
            return (
                session.query(ControlFlag)
                .filter(ControlFlag.key.in_((GLOBAL_KEY, f"{ACCOUNT_PREFIX}{account}")), ControlFlag.active.is_(True))
                .count()
                > 0
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Kill switch unreadable, treating %s as halted: %s", account, exc)
            if session is not None:
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            return True

    def halt(self, scope: str, reason: str, by: str) -> None:
        self._set(scope, True, reason, by)
        logger.critical("KILL SWITCH ON scope=%s by=%s reason=%s", scope, by, reason)

    def resume(self, scope: str, by: str) -> None:
        self._set(scope, False, f"resumed by {by}", by)
        logger.warning("Kill switch off scope=%s by=%s", scope, by)

    def _set(self, scope: str, active: bool, reason: str, by: str) -> None:
        session = self._provider()
        try:
            flag = session.get(ControlFlag, _key(scope))
            if flag is None:
                flag = ControlFlag(key=_key(scope))
                session.add(flag)
            flag.active, flag.reason, flag.updated_by = active, reason, by
            session.commit()
        except Exception:
            session.rollback()
            raise

    def status(self) -> dict:
        session = self._provider()
        rows = session.query(ControlFlag).filter(ControlFlag.active.is_(True)).all()
        out: dict = {"global": None, "accounts": {}}
        for row in rows:
            entry = {"reason": row.reason, "by": row.updated_by, "since": str(row.updated_at)}
            if row.key == GLOBAL_KEY:
                out["global"] = entry
            elif row.key.startswith(ACCOUNT_PREFIX):
                out["accounts"][row.key[len(ACCOUNT_PREFIX):]] = entry
        return out
