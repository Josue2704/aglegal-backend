from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep
from ..schemas.user import PasswordChange, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(current_user: CurrentUser, repo: RepoDep) -> list[UserOut]:
    return [UserOut.from_row(row) for row in repo.list_users()]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, current_user: CurrentUser, repo: RepoDep) -> UserOut:
    user_id = repo.create_user(
        username=body.username,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
        active=body.active,
        created_at=now_iso(),
    )
    row = repo.conn.execute(
        "SELECT id, username, full_name, role, active, created_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    return UserOut.from_row(row)


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, current_user: CurrentUser, repo: RepoDep) -> UserOut:
    repo.update_user(user_id, full_name=body.full_name, role=body.role, active=body.active)
    row = repo.conn.execute(
        "SELECT id, username, full_name, role, active, created_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    return UserOut.from_row(row)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_user(user_id)


@router.post("/{user_id}/password", status_code=204)
def change_password(user_id: int, body: PasswordChange, current_user: CurrentUser, repo: RepoDep):
    repo.update_user_password(user_id, body.password)
