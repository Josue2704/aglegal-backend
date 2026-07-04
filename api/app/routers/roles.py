from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, RepoDep, require_permission
from ..schemas.role import PermissionOut, RoleCreate, RoleDetailOut, RoleOut, RoleUpdate

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(current_user: CurrentUser, repo: RepoDep) -> list[PermissionOut]:
    return [PermissionOut.from_row(r) for r in repo.list_all_permissions()]


@router.get("", response_model=list[RoleOut])
def list_roles(current_user: CurrentUser, repo: RepoDep) -> list[RoleOut]:
    return [RoleOut.from_row(r) for r in repo.list_roles()]


@router.get("/{role_id}", response_model=RoleDetailOut)
def get_role(role_id: int, current_user: CurrentUser, repo: RepoDep) -> RoleDetailOut:
    row = repo.get_role(role_id)
    if not row:
        raise HTTPException(404, "Rol no encontrado")
    perms = [PermissionOut.from_row(p) for p in repo.get_role_permissions(role_id)]
    out = RoleDetailOut.from_row(row)
    out.permissions = perms
    out.permission_count = len(perms)
    return out


@router.post("", response_model=RoleDetailOut, status_code=201,
             dependencies=[require_permission("roles", "crear")])
def create_role(body: RoleCreate, current_user: AdminRequired, repo: RepoDep) -> RoleDetailOut:
    existing = repo.conn.execute("SELECT id FROM roles WHERE name=%s", (body.name,)).fetchone()
    if existing:
        raise HTTPException(409, "Ya existe un rol con ese nombre")
    role_id = repo.create_role(body.name, body.description, now_iso())
    if body.permission_ids:
        repo.set_role_permissions(role_id, body.permission_ids)
    return get_role(role_id, current_user, repo)


@router.put("/{role_id}", response_model=RoleDetailOut,
            dependencies=[require_permission("roles", "editar")])
def update_role(role_id: int, body: RoleUpdate, current_user: AdminRequired, repo: RepoDep) -> RoleDetailOut:
    row = repo.get_role(role_id)
    if not row:
        raise HTTPException(404, "Rol no encontrado")
    if row["is_system"]:
        # System roles: only permissions can be changed, not name/description
        repo.set_role_permissions(role_id, body.permission_ids)
    else:
        repo.update_role(role_id, body.name, body.description)
        repo.set_role_permissions(role_id, body.permission_ids)
    return get_role(role_id, current_user, repo)


@router.delete("/{role_id}", status_code=204,
               dependencies=[require_permission("roles", "eliminar")])
def delete_role(role_id: int, current_user: AdminRequired, repo: RepoDep):
    row = repo.get_role(role_id)
    if not row:
        raise HTTPException(404, "Rol no encontrado")
    if row["is_system"]:
        raise HTTPException(400, "No se puede eliminar un rol del sistema")
    repo.delete_role(role_id)
