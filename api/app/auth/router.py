from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, RepoDep
from ..schemas.auth import LoginRequest, TokenResponse, UserInfo
from .service import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, repo: RepoDep) -> TokenResponse:
    if not repo.authenticate(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")

    token = create_access_token(body.username)
    row = repo.conn.execute(
        "SELECT id, username, full_name, role FROM users WHERE username=?",
        (body.username,),
    ).fetchone()

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserInfo(
            id=int(row["id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"] or ""),
            role=str(row["role"] or "Administrador"),
        ),
    )


@router.get("/me", response_model=UserInfo)
def me(current_user: CurrentUser, repo: RepoDep) -> UserInfo:
    row = repo.conn.execute(
        "SELECT id, username, full_name, role FROM users WHERE username=?",
        (current_user,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Usuario no encontrado")
    return UserInfo(
        id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"] or ""),
        role=str(row["role"] or "Administrador"),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: CurrentUser):
    # JWT es stateless — el cliente simplemente descarta el token
    pass
