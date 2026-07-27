from __future__ import annotations

from fastapi import APIRouter, Query

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.catalogo import (
    CategoriaOut,
    FamiliaOut,
    HistorialEntryOut,
    ServicioChoice,
    ServicioOut,
    SubcategoriaOut,
)

router = APIRouter(prefix="/catalogo", tags=["catalogo"])

# Solo lectura: toda alta, cambio o baja del Catálogo Maestro pasa por una solicitud
# de Gobierno del Catálogo (ver /solicitudes-catalogo) — no hay endpoints de escritura
# aquí. Aprobar una solicitud es lo único que crea/edita/inactiva estos registros.


@router.get("/categorias", response_model=list[CategoriaOut])
def list_categorias(
    current_user: CurrentUser, repo: RepoDep, estado: str | None = None, _: dict = require_permission("catalogo", "ver")
) -> list[CategoriaOut]:
    return [CategoriaOut.from_row(row) for row in repo.list_categorias(estado=estado)]


@router.get("/subcategorias", response_model=list[SubcategoriaOut])
def list_subcategorias(
    current_user: CurrentUser, repo: RepoDep, category_id: int | None = None, estado: str | None = None,
    _: dict = require_permission("catalogo", "ver"),
) -> list[SubcategoriaOut]:
    return [SubcategoriaOut.from_row(row) for row in repo.list_subcategorias(category_id=category_id, estado=estado)]


@router.get("/familias", response_model=list[FamiliaOut])
def list_familias(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("catalogo", "ver")) -> list[FamiliaOut]:
    return [FamiliaOut.from_row(row) for row in repo.list_familias()]


@router.get("/servicios", response_model=list[ServicioOut])
def list_servicios(
    current_user: CurrentUser,
    repo: RepoDep,
    subcategory_id: int | None = None,
    category_id: int | None = None,
    estado: str | None = None,
    q: str | None = None,
    _: dict = require_permission("catalogo", "ver"),
) -> list[ServicioOut]:
    rows = repo.list_servicios(subcategory_id=subcategory_id, category_id=category_id, estado=estado, q=q)
    return [ServicioOut.from_row(row) for row in rows]


@router.get("/servicios/choices", response_model=list[ServicioChoice])
def servicio_choices(
    current_user: CurrentUser,
    repo: RepoDep,
    q: str | None = None,
    estado: str = "Activo",
    limit: int = Query(25, le=100),
    _: dict = require_permission("catalogo", "ver"),
) -> list[ServicioChoice]:
    """Búsqueda por código o nombre — usada para seleccionar servicio en expedientes."""
    return [ServicioChoice.from_row(row) for row in repo.servicio_choices(q=q, estado=estado, limit=limit)]


@router.get("/historial", response_model=list[HistorialEntryOut])
def historial(
    current_user: CurrentUser, repo: RepoDep, tipo_registro: str, entity_id: int, _: dict = require_permission("catalogo", "ver")
) -> list[HistorialEntryOut]:
    return [HistorialEntryOut.from_row(row) for row in repo.historial_catalogo(tipo_registro=tipo_registro, entity_id=entity_id)]
