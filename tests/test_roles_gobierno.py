"""Verifica de punta a punta:
1. Roles: crear rol con permisos concretos, asignarlo a un usuario real, loguearse de
   verdad (contraseña + JWT, no dependency_override) y comprobar que el token trae
   exactamente esos permisos — y que un endpoint fuera de esos permisos da 403.
2. Gobierno del catálogo: un administrador que crea una solicitud de Alta queda
   Activa de inmediato (sin pasar por aprobación manual); un usuario sin permiso de
   aprobar que crea la misma solicitud se queda en 'Solicitado'.
"""
from __future__ import annotations

import random
import string

import pytest
from fastapi.testclient import TestClient

ADMIN = {"id": 1, "username": "tester_admin", "role": "Administrador", "role_id": None, "is_admin": True, "permissions": set()}


def _uniq(n: int = 4) -> str:
    return "".join(random.choices(string.ascii_uppercase, k=n))


@pytest.fixture(scope="module")
def app_client(db_conn):
    from api.app.deps import get_current_user
    from api.app.main import app

    app.dependency_overrides[get_current_user] = lambda: ADMIN
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app_ref = app
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, user: dict | None):
    from api.app.deps import get_current_user

    if user is None:
        client.app_ref.dependency_overrides.pop(get_current_user, None)
    else:
        client.app_ref.dependency_overrides[get_current_user] = lambda: user


def test_role_crud_and_real_login_gets_exact_permissions(app_client, repo):
    _as(app_client, ADMIN)

    perms = app_client.get("/roles/permissions").json()
    ver_catalogo = next(p["id"] for p in perms if p["module"] == "catalogo" and p["action"] == "ver")
    ver_roles = next(p["id"] for p in perms if p["module"] == "roles" and p["action"] == "ver")

    role_name = f"Rol {_uniq()}"
    created = app_client.post("/roles", json={"name": role_name, "description": "prueba", "permission_ids": [ver_catalogo]})
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["permission_count"] == 1
    role_id = role["id"]

    fetched = app_client.get(f"/roles/{role_id}").json()
    assert {p["module"] + "." + p["action"] for p in fetched["permissions"]} == {"catalogo.ver"}

    updated = app_client.put(f"/roles/{role_id}", json={"name": role_name, "description": "prueba", "permission_ids": [ver_catalogo, ver_roles]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["permission_count"] == 2

    username = f"tester_{_uniq().lower()}"
    from aglegal.db import now_iso
    user_id = repo.create_user(username=username, password="Clave12345", full_name="Usuario de prueba",
                                role=role_name, active=True, created_at=now_iso())
    repo.assign_user_role(user_id, role_id)

    login = app_client.post("/auth/login", json={"username": username, "password": "Clave12345"})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["user"]["is_admin"] is False
    assert set(body["user"]["permissions"]) == {"catalogo.ver", "roles.ver"}
    token = body["access_token"]

    _as(app_client, None)  # usar el token real, no el override de admin
    try:
        headers = {"Authorization": f"Bearer {token}"}
        assert app_client.get("/catalogo/categorias", headers=headers).status_code == 200
        assert app_client.get("/roles", headers=headers).status_code == 200
        # sin permiso de crear rol -> 403 (y AdminRequired también lo bloquea por no ser admin)
        assert app_client.post("/roles", json={"name": "otro", "permission_ids": []}, headers=headers).status_code == 403
        # sin permiso sobre usuarios -> 403
        assert app_client.get("/users", headers=headers).status_code == 403
    finally:
        _as(app_client, ADMIN)

    # un rol de sistema no se puede borrar; el rol nuevo sí
    admin_role = next(r for r in app_client.get("/roles").json() if r["is_system"])
    assert app_client.delete(f"/roles/{admin_role['id']}").status_code in (400, 403)
    assert app_client.delete(f"/roles/{role_id}").status_code == 204
    assert app_client.get(f"/roles/{role_id}").status_code == 404


def test_gobierno_catalogo_admin_bypasses_aprobacion(app_client, codigo_unico):
    _as(app_client, ADMIN)
    body = {
        "tipo_solicitud": "Alta", "tipo_registro": "Categoria",
        "nombre_propuesto": f"Categoria admin {codigo_unico}", "categoria_padre": None,
        "subcategoria_padre": None, "codigo_propuesto": codigo_unico,
    }
    r = app_client.post("/solicitudes-catalogo", json=body)
    assert r.status_code == 201, r.text
    solicitud = r.json()
    assert solicitud["estado"] == "Activo", solicitud
    assert solicitud["aprobador"] == ADMIN["username"]

    listado = app_client.get("/catalogo/categorias").json()
    assert any(c["category_code"] == codigo_unico for c in listado)


def test_gobierno_catalogo_no_admin_queda_pendiente(app_client, codigo_unico):
    solicitante = {"id": 99, "username": "abogada_prueba", "role": "Abogado", "role_id": None, "is_admin": False,
                    "permissions": {"gobierno_catalogo.ver", "gobierno_catalogo.crear"}}
    _as(app_client, solicitante)
    try:
        body = {
            "tipo_solicitud": "Alta", "tipo_registro": "Categoria",
            "nombre_propuesto": f"Categoria no admin {codigo_unico}", "categoria_padre": None,
            "subcategoria_padre": None, "codigo_propuesto": codigo_unico,
        }
        r = app_client.post("/solicitudes-catalogo", json=body)
        assert r.status_code == 201, r.text
        solicitud = r.json()
        assert solicitud["estado"] == "Solicitado", solicitud
    finally:
        _as(app_client, ADMIN)

    listado = app_client.get("/catalogo/categorias").json()
    assert not any(c["category_code"] == codigo_unico for c in listado)
