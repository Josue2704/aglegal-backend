from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..access import require_any
from ..schemas.case import (
    CopiarPlantillaIn,
    EtiquetaTareaIn,
    EtiquetaTareaOut,
    PlantillaTareaIn,
    PlantillaTareaOut,
    ReordenarPlantillaIn,
)
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
    _: dict = require_any('catalogo.ver','expedientes.crear','expedientes.editar','pipeline.crear','pipeline.editar','flujo_caja.crear','flujo_caja.editar'),
) -> list[ServicioChoice]:
    """Búsqueda por código o nombre — usada para seleccionar servicio en expedientes."""
    return [ServicioChoice.from_row(row) for row in repo.servicio_choices(q=q, estado=estado, limit=limit)]


# Plantillas de tareas por servicio — a diferencia del catálogo maestro (categorías,
# servicios), esto no pasa por Gobierno del Catálogo: es un checklist operativo que
# conviene poder ajustar rápido, no una alta/baja del catálogo de precios/servicios.

@router.get("/servicios/{service_id}/plantilla-tareas", response_model=list[PlantillaTareaOut])
def list_plantilla_tareas(service_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_any('catalogo.ver','expedientes.crear','pipeline.editar')) -> list[PlantillaTareaOut]:
    return [PlantillaTareaOut.from_row(row) for row in repo.list_plantilla_tareas(service_id)]


@router.post("/servicios/{service_id}/plantilla-tareas", response_model=PlantillaTareaOut, status_code=201)
def create_plantilla_tarea(service_id: int, body: PlantillaTareaIn, current_user: CurrentUser, repo: RepoDep) -> PlantillaTareaOut:
    if not current_user["is_admin"]:
        raise HTTPException(403, "Solo un administrador puede editar plantillas de tareas")
    plantilla_id = repo.create_plantilla_tarea(
        service_id=service_id, titulo=body.titulo, orden=body.orden,
        dias_plazo_relativo=body.dias_plazo_relativo, es_critico_default=body.es_critico_default,
        costo_estimado_text=str(body.costo_estimado) if body.costo_estimado is not None else "0",
        honorario_sugerido_text=str(body.honorario_sugerido) if body.honorario_sugerido is not None else "0",
        descripcion=body.descripcion, responsable_sugerido=body.responsable_sugerido,
        etiqueta_ids=body.etiqueta_ids,
        created_at=now_iso(),
    )
    row = next(r for r in repo.list_plantilla_tareas(service_id) if r["id"] == plantilla_id)
    return PlantillaTareaOut.from_row(row)


@router.put("/plantilla-tareas/{plantilla_id}", response_model=PlantillaTareaOut)
def update_plantilla_tarea(plantilla_id: int, body: PlantillaTareaIn, current_user: CurrentUser, repo: RepoDep) -> PlantillaTareaOut:
    if not current_user["is_admin"]:
        raise HTTPException(403, "Solo un administrador puede editar plantillas de tareas")
    repo.update_plantilla_tarea(
        plantilla_id, titulo=body.titulo, orden=body.orden,
        dias_plazo_relativo=body.dias_plazo_relativo, es_critico_default=body.es_critico_default,
        costo_estimado_text=str(body.costo_estimado) if body.costo_estimado is not None else "0",
        honorario_sugerido_text=str(body.honorario_sugerido) if body.honorario_sugerido is not None else "0",
        descripcion=body.descripcion, responsable_sugerido=body.responsable_sugerido,
        etiqueta_ids=body.etiqueta_ids,
    )
    row = repo.conn.execute("SELECT * FROM plantillas_tareas WHERE id=%s", (plantilla_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Plantilla no encontrada")
    return PlantillaTareaOut.from_row(row)


@router.delete("/plantilla-tareas/{plantilla_id}", status_code=204)
def delete_plantilla_tarea(plantilla_id: int, current_user: CurrentUser, repo: RepoDep):
    if not current_user["is_admin"]:
        raise HTTPException(403, "Solo un administrador puede editar plantillas de tareas")
    repo.delete_plantilla_tarea(plantilla_id)


@router.put("/servicios/{service_id}/plantilla-tareas/orden", response_model=list[PlantillaTareaOut])
def reordenar_plantilla(service_id: int, body: ReordenarPlantillaIn, current_user: CurrentUser,
                        repo: RepoDep) -> list[PlantillaTareaOut]:
    """El orden de la plantilla es el orden en que se trabaja el caso."""
    if not current_user["is_admin"]:
        raise HTTPException(403, "Solo un administrador puede editar plantillas de tareas")
    repo.reordenar_plantilla_tareas(service_id, body.orden_ids)
    return [PlantillaTareaOut.from_row(r) for r in repo.list_plantilla_tareas(service_id)]


@router.post("/servicios/{service_id}/plantilla-tareas/copiar", response_model=list[PlantillaTareaOut])
def copiar_plantilla(service_id: int, body: CopiarPlantillaIn, current_user: CurrentUser,
                     repo: RepoDep) -> list[PlantillaTareaOut]:
    """Copiar la plantilla de otro servicio parecido y ajustarla."""
    if not current_user["is_admin"]:
        raise HTTPException(403, "Solo un administrador puede editar plantillas de tareas")
    repo.copiar_plantilla_tareas(origen_service_id=body.origen_service_id, destino_service_id=service_id,
                                 reemplazar=body.reemplazar, created_at=now_iso())
    return [PlantillaTareaOut.from_row(r) for r in repo.list_plantilla_tareas(service_id)]


# ── Etiquetas de tarea (las del tablero) ───────────────────────────────────

@router.get("/etiquetas-tarea", response_model=list[EtiquetaTareaOut])
def list_etiquetas(current_user: CurrentUser, repo: RepoDep) -> list[EtiquetaTareaOut]:
    return [EtiquetaTareaOut.from_row(r) for r in repo.list_etiquetas_tarea()]


@router.post("/etiquetas-tarea", response_model=EtiquetaTareaOut, status_code=201)
def create_etiqueta(body: EtiquetaTareaIn, current_user: CurrentUser, repo: RepoDep,
                    _: dict = require_permission("tareas", "editar")) -> EtiquetaTareaOut:
    etiqueta_id = repo.create_etiqueta_tarea(nombre=body.nombre, color=body.color, created_at=now_iso())
    row = next(r for r in repo.list_etiquetas_tarea() if int(r["id"]) == etiqueta_id)
    return EtiquetaTareaOut.from_row(row)


@router.put("/etiquetas-tarea/{etiqueta_id}", response_model=EtiquetaTareaOut)
def update_etiqueta(etiqueta_id: int, body: EtiquetaTareaIn, current_user: CurrentUser, repo: RepoDep,
                    _: dict = require_permission("tareas", "editar")) -> EtiquetaTareaOut:
    repo.update_etiqueta_tarea(etiqueta_id, nombre=body.nombre, color=body.color)
    row = next(r for r in repo.list_etiquetas_tarea() if int(r["id"]) == etiqueta_id)
    return EtiquetaTareaOut.from_row(row)


@router.delete("/etiquetas-tarea/{etiqueta_id}", status_code=204)
def delete_etiqueta(etiqueta_id: int, current_user: CurrentUser, repo: RepoDep,
                    _: dict = require_permission("tareas", "editar")):
    repo.delete_etiqueta_tarea(etiqueta_id)


@router.get("/historial", response_model=list[HistorialEntryOut])
def historial(
    current_user: CurrentUser, repo: RepoDep, tipo_registro: str, entity_id: int, _: dict = require_permission("catalogo", "ver")
) -> list[HistorialEntryOut]:
    return [HistorialEntryOut.from_row(row) for row in repo.historial_catalogo(tipo_registro=tipo_registro, entity_id=entity_id)]
