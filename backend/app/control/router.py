"""Operator controls: kill switch, flatten, status. Mounted behind the API key."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.router import get_pods
from app.control.killswitch import KillSwitch
from app.data.database import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter()
_alert_service: Optional[Any] = None


def set_alert_service(service: Optional[Any]) -> None:
    global _alert_service
    _alert_service = service


class HaltRequest(BaseModel):
    scope: str = Field(min_length=1, description='"all" or an account name')
    reason: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    scope: str = Field(min_length=1)


async def _alert(kind: str, scope: str, message: str) -> None:
    """kind is the alert service method suffix: "critical" or "info". A failed alert never fails the request."""
    if _alert_service is None:
        return
    try:
        await getattr(_alert_service, f"send_{kind}")(scope, message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not send kill-switch alert: %s", exc)


@router.get("/status")
async def status(db: Session = Depends(get_db_session)):
    return {
        "kill_switch": KillSwitch(lambda: db).status(),
        "pods": {name: pod.get_status() for name, pod in get_pods().items()},
    }


@router.post("/halt")
async def halt(request: HaltRequest, db: Session = Depends(get_db_session)):
    KillSwitch(lambda: db).halt(request.scope, request.reason, by="api")
    await _alert("critical", request.scope, f"KILL SWITCH ON ({request.scope}): {request.reason}")
    return {"status": "halted", "scope": request.scope}


@router.post("/resume")
async def resume(request: ResumeRequest, db: Session = Depends(get_db_session)):
    KillSwitch(lambda: db).resume(request.scope, by="api")
    await _alert("info", request.scope, f"Kill switch off ({request.scope})")
    return {"status": "resumed", "scope": request.scope}


@router.post("/flatten/{account_name}")
async def flatten(account_name: str):
    pods = get_pods()
    if account_name not in pods:
        raise HTTPException(status_code=404, detail=f"No agent pod for account '{account_name}'")
    closed = await pods[account_name].flatten(f"flatten requested through the API for {account_name}")
    return {"status": "flattened", "account": account_name, "closed": closed}
