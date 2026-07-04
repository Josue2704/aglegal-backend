from fastapi import APIRouter, HTTPException, Request, status

from ..deps import CurrentUser, RepoDep
from ..limiter import limiter
from ..schemas.auth import LoginRequest, TokenResponse, UserInfo
from .service import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_user_info(conn, username: str) -> UserInfo:
    row = conn.execute(
        """SELECT u.id, u.username, u.full_name,
                  r.id AS role_id, r.name AS role_name, r.is_system
           FROM users u
           LEFT JOIN roles r ON r.name = u.role OR r.id::text = u.role
           WHERE u.username=%s""",
        (username,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Usuario no encontrado")

    is_admin = bool(row["is_system"]) or row["role_name"] == "Administrador"

    if is_admin:
        perm_rows = conn.execute(
            "SELECT module || '.' || action AS perm FROM permissions"
        ).fetchall()
    else:
        perm_rows = conn.execute(
            """SELECT p.module || '.' || p.action AS perm
               FROM role_permissions rp
               JOIN permissions p ON p.id = rp.permission_id
               WHERE rp.role_id = %s""",
            (row["role_id"],),
        ).fetchall()

    return UserInfo(
        id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"] or ""),
        role=str(row["role_name"] or ""),
        role_id=row["role_id"],
        is_admin=is_admin,
        permissions=[str(r["perm"]) for r in perm_rows],
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, repo: RepoDep) -> TokenResponse:
    if not repo.authenticate(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    token = create_access_token(body.username)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_build_user_info(repo.conn, body.username),
    )


@router.get("/me", response_model=UserInfo)
def me(current_user: CurrentUser, repo: RepoDep) -> UserInfo:
    return _build_user_info(repo.conn, current_user["username"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: CurrentUser):
    pass
