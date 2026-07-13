from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..config import get_settings
from ..deps import CurrentUser, RepoDep
from ..services import outlook_calendar as ocal

router = APIRouter(prefix="/outlook-cal", tags=["outlook-calendar"])


class StatusOut(BaseModel):
    connected: bool


class AuthUrlOut(BaseModel):
    url: str


@router.get("/status", response_model=StatusOut)
def outlook_status(current_user: CurrentUser, repo: RepoDep) -> StatusOut:
    row = repo.get_outlook_tokens(current_user["username"])
    return StatusOut(connected=row is not None)


@router.get("/authorize", response_model=AuthUrlOut)
def outlook_authorize(current_user: CurrentUser) -> AuthUrlOut:
    s = get_settings()
    if not s.outlook_client_id or not s.outlook_client_secret:
        raise HTTPException(503, "Outlook Calendar no está configurado. Añade OUTLOOK_CLIENT_ID y OUTLOOK_CLIENT_SECRET al .env")
    url = ocal.get_auth_url(current_user["username"])
    return AuthUrlOut(url=url)


@router.get("/callback")
def outlook_callback(code: str, state: str, repo: RepoDep):
    """OAuth2 callback from Microsoft. `state` = username."""
    s = get_settings()
    try:
        access_token, refresh_token, expiry_at = ocal.exchange_code(code)
        repo.save_outlook_tokens(state, access_token, refresh_token, expiry_at)
        return RedirectResponse(f"{s.frontend_url}/settings?outlook=connected")
    except Exception as e:
        return RedirectResponse(f"{s.frontend_url}/settings?outlook=error&msg={str(e)[:100]}")


@router.delete("/disconnect", status_code=204)
def outlook_disconnect(current_user: CurrentUser, repo: RepoDep):
    repo.delete_outlook_tokens(current_user["username"])
