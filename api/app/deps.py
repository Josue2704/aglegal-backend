from __future__ import annotations

from typing import Annotated, Any, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aglegal.db import connect, init_db
from aglegal.repositories import Repository

from .auth.service import decode_token

_bearer = HTTPBearer()


def get_db() -> Generator[Any, None, None]:
    conn = connect()
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[Any, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    conn: DbDep,
) -> dict:
    username = decode_token(credentials.credentials)
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado")
    row = conn.execute(
        """SELECT u.id, u.username, u.full_name, u.role_id,
                  r.name AS role_name, r.is_system
           FROM users u
           LEFT JOIN roles r ON r.id = u.role_id
           WHERE u.username=%s AND COALESCE(u.active, 1)=1""",
        (username,),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado o inactivo")

    is_admin = bool(row["is_system"]) or row["role_name"] == "Administrador"
    role_name = str(row["role_name"] or "")

    if is_admin:
        permissions: set[str] = set()  # admin bypasses all checks
    else:
        perm_rows = conn.execute(
            """SELECT p.module || '.' || p.action AS perm
               FROM role_permissions rp
               JOIN permissions p ON p.id = rp.permission_id
               WHERE rp.role_id = %s""",
            (row["role_id"],),
        ).fetchall()
        permissions = {str(r["perm"]) for r in perm_rows}

    return {
        "username": str(row["username"]),
        "role": role_name,
        "role_id": row["role_id"],
        "is_admin": is_admin,
        "permissions": permissions,
    }


CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_permission(module: str, action: str):
    """Returns a FastAPI dependency that verifies the user has module.action permission."""
    perm_key = f"{module}.{action}"

    def _check(user: CurrentUser) -> dict:
        if user["is_admin"]:
            return user
        if perm_key not in user["permissions"]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Sin permiso: {perm_key}",
            )
        return user

    return Depends(_check)


def require_admin(user: CurrentUser) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Se requiere rol Administrador")
    return user


def require_lawyer_plus(user: CurrentUser) -> dict:
    """Legacy: allow admin or users with any financial permission."""
    if user["is_admin"]:
        return user
    if "flujo_caja.ver" in user["permissions"] or "facturas.ver" in user["permissions"]:
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta operación")


AdminRequired = Annotated[dict, Depends(require_admin)]
LawyerRequired = Annotated[dict, Depends(require_lawyer_plus)]


def get_repo(conn: DbDep) -> Repository:
    return Repository(conn)


RepoDep = Annotated[Repository, Depends(get_repo)]
