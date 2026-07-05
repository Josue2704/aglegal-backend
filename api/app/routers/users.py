from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, RepoDep
from ..schemas.user import PasswordChange, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(current_user: AdminRequired, repo: RepoDep) -> list[UserOut]:
    return [UserOut.from_row(row) for row in repo.list_users()]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, current_user: AdminRequired, repo: RepoDep) -> UserOut:
    user_id = repo.create_user(
        username=body.username,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
        active=body.active,
        created_at=now_iso(),
    )
    if body.role_id is not None:
        repo.assign_user_role(user_id, body.role_id)
    row = repo.conn.execute(
        """SELECT u.id, u.username, u.full_name, u.role_id, u.active, u.created_at,
                  r.name AS role_name
           FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE u.id=%s""",
        (user_id,),
    ).fetchone()
    return UserOut.from_row(row)


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, current_user: AdminRequired, repo: RepoDep) -> UserOut:
    repo.update_user(user_id, full_name=body.full_name, role=body.role, active=body.active)
    if body.role_id is not None:
        repo.assign_user_role(user_id, body.role_id)
    row = repo.conn.execute(
        """SELECT u.id, u.username, u.full_name, u.role_id, u.active, u.created_at,
                  r.name AS role_name
           FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE u.id=%s""",
        (user_id,),
    ).fetchone()
    return UserOut.from_row(row)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, current_user: AdminRequired, repo: RepoDep):
    repo.delete_user(user_id)


@router.post("/{user_id}/password", status_code=204)
def change_password(user_id: int, body: PasswordChange, current_user: CurrentUser, repo: RepoDep):
    is_admin = current_user["is_admin"]
    self_row = repo.conn.execute(
        "SELECT id FROM users WHERE username=%s", (current_user["username"],)
    ).fetchone()
    is_self = self_row and int(self_row["id"]) == user_id
    if not is_admin and not is_self:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes cambiar tu propia contraseña")
    repo.update_user_password(user_id, body.password)
