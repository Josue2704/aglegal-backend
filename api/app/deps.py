from __future__ import annotations

import sqlite3
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aglegal.db import connect, init_db
from aglegal.repositories import Repository

from .auth.service import decode_token

_bearer = HTTPBearer()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect()
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    conn: DbDep,
) -> str:
    username = decode_token(credentials.credentials)
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado")
    row = conn.execute(
        "SELECT username FROM users WHERE username=? AND COALESCE(active, 1)=1",
        (username,),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado o inactivo")
    return username


CurrentUser = Annotated[str, Depends(get_current_user)]


def get_repo(conn: DbDep) -> Repository:
    return Repository(conn)


RepoDep = Annotated[Repository, Depends(get_repo)]
