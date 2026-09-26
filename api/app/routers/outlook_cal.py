from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..config import get_settings
from ..deps import CurrentUser, RepoDep, require_permission
from ..services import outlook_calendar as ocal
from ..services import calendar_oauth
from urllib.parse import urlencode

router = APIRouter(prefix="/outlook-cal", tags=["outlook-calendar"])


class StatusOut(BaseModel):
    connected: bool


class AuthUrlOut(BaseModel):
    url: str


@router.get("/status", response_model=StatusOut)
def outlook_status(current_user: CurrentUser, repo: RepoDep) -> StatusOut:
    row = repo.get_outlook_tokens(current_user["username"])
    return StatusOut(connected=row is not None)


@router.get("/authorize", response_model=AuthUrlOut, dependencies=[require_permission("agenda", "ver")])
def outlook_authorize(current_user: CurrentUser, repo: RepoDep, response: Response) -> AuthUrlOut:
    s = get_settings()
    if not s.outlook_client_id or not s.outlook_client_secret:
        raise HTTPException(503, "Outlook Calendar no está configurado. Añade OUTLOOK_CLIENT_ID y OUTLOOK_CLIENT_SECRET al .env")
    url = ocal.get_auth_url(calendar_oauth.begin(repo,current_user["username"],"outlook",response))
    return AuthUrlOut(url=url)


@router.get("/callback")
def outlook_callback(request: Request, repo: RepoDep, code: str = '', state: str = '', error: str = ''):
    username = calendar_oauth.consume(repo,'outlook',state,request.cookies.get('outlook_oauth'))
    query = {'outlook':'connected'}
    try:
        if error or not code:
            raise ValueError()
        access, refresh, expiry = ocal.exchange_code(code)
        repo.save_outlook_tokens(username,access,refresh,expiry)
    except Exception:
        query = {'outlook':'error','msg':'No se completó la autorización. Vuelve a conectar Outlook.'}
    response = RedirectResponse(get_settings().frontend_url+'/settings?'+urlencode(query))
    response.delete_cookie('outlook_oauth',path='/')
    return response


@router.delete("/disconnect", status_code=204)
def outlook_disconnect(current_user: CurrentUser, repo: RepoDep):
    repo.delete_outlook_tokens(current_user["username"])
