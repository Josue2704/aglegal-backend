"""Bootstrap de pytest — corre el esquema completo dentro de un schema de Postgres
desechable (aglegal_test), separado por completo de los datos reales que viven en
`public` dentro de la misma base apuntada por DATABASE_URL. El usuario de la app no
tiene privilegio CREATEDB (no puede crear una base nueva), pero sí CREATE SCHEMA — así
que el aislamiento es por schema, vía `search_path`, no por base de datos.

Cada prueba crea su propio catálogo mínimo con nombres/códigos únicos para no interferir
entre sí (varias pruebas acumulan comisión por persona+mes, así que compartir una persona
entre pruebas daría resultados cruzados)."""
from __future__ import annotations

import os
import random
import string
import urllib.parse

import psycopg2
import pytest

TEST_SCHEMA = "aglegal_test"


def _base_database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://aglegal:aglegal@localhost:5432/aglegal")


def _test_database_url() -> str:
    options = urllib.parse.quote(f"-csearch_path={TEST_SCHEMA}")
    sep = "&" if "?" in _base_database_url() else "?"
    return f"{_base_database_url()}{sep}options={options}"


@pytest.fixture(scope="session", autouse=True)
def _test_schema_env() -> None:
    """Recrea el schema de pruebas en blanco al inicio de la sesión, y apunta DATABASE_URL
    ahí (vía search_path) para que aglegal.db.connect() nunca toque `public`."""
    conn = psycopg2.connect(_base_database_url())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
    conn.close()
    os.environ["DATABASE_URL"] = _test_database_url()


@pytest.fixture(scope="session")
def db_conn(_test_schema_env):
    import aglegal.db as db

    conn = db.connect()
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture()
def repo(db_conn):
    from aglegal.repositories import Repository

    return Repository(db_conn)


@pytest.fixture()
def apertura():
    from datetime import date
    return dict(mes_cobro_esperado=date.today().isoformat()[:7], probabilidad_cobro=0.7, honorarios_pactados=900, alcance='Servicio aceptado por el cliente',
        condiciones_cobro='Al finalizar', revision_confirmada=True,
        revision_observaciones='Ficha y coincidencias revisadas', responsable_expediente='admin',
        tareas_iniciales=[dict(titulo='Revisar documentación',due_date=date.today().isoformat())])


_CODIGOS_USADOS: set[str] = set()


@pytest.fixture()
def codigo_unico(db_conn) -> str:
    """3 letras mayúsculas — cumple con el formato de código de categoría/subcategoría
    (2-4 letras, sin números) y es distinto en cada prueba.

    Con azar puro dos pruebas sacaban el mismo código de vez en cuando (con ~200 pruebas
    la colisión deja de ser improbable) y la segunda reventaba con "el código ya existe".
    Se descartan los ya usados en esta corrida y los que quedaron en el schema."""
    for _ in range(200):
        codigo = "".join(random.choices(string.ascii_uppercase, k=3))
        if codigo in _CODIGOS_USADOS:
            continue
        if db_conn.execute("SELECT 1 FROM categorias WHERE category_code=%s", (codigo,)).fetchone():
            _CODIGOS_USADOS.add(codigo)
            continue
        _CODIGOS_USADOS.add(codigo)
        return codigo
    raise RuntimeError("No se encontró un código de catálogo libre para la prueba")


@pytest.fixture()
def catalogo(repo, codigo_unico):
    """Categoría → subcategoría → servicio, más una cuenta contable de ingreso, una persona
    y un cliente — el mínimo que cualquier prueba de comisión/movimiento necesita, con
    nombres únicos por prueba para no chocar con otras pruebas ni con corridas anteriores."""
    from aglegal.db import now_iso

    now = now_iso()
    categoria_id = repo.create_categoria(category_code=codigo_unico, nombre=f"Categoria {codigo_unico}", created_at=now)
    subcategoria_id = repo.create_subcategoria(category_id=categoria_id, subcategory_code=codigo_unico, nombre=f"Subcategoria {codigo_unico}", created_at=now)
    servicio_id = repo.create_servicio(subcategory_id=subcategoria_id, nombre=f"Servicio {codigo_unico}", created_at=now)
    cuenta_id = repo.create_cuenta(
        account_code=f"ING-{codigo_unico}-001", tipo="Ingreso", grupo="Honorarios", nombre=f"Ingresos {codigo_unico}",
        naturaleza="Operativo", centro_costo="Operación jurídica", created_at=now,
    )
    persona_id = repo.create_persona(persona=f"Persona {codigo_unico}", mes_inicio="2026-01", created_at=now)
    cliente_id = repo.create_client(name=f"Cliente {codigo_unico}", created_at=now)
    return {
        "categoria_id": categoria_id, "subcategoria_id": subcategoria_id, "servicio_id": servicio_id,
        "cuenta_id": cuenta_id, "persona_id": persona_id, "cliente_id": cliente_id,
    }
