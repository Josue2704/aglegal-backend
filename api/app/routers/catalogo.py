from __future__ import annotations

from fastapi import APIRouter, Query

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.catalogo import (
    CategoriaIn,
    CategoriaOut,
    CategoriaUpdate,
    FamiliaIn,
    FamiliaOut,
    FamiliaUpdate,
    HistorialEntryOut,
    ServicioChoice,
    ServicioIn,
    ServicioOut,
    ServicioUpdate,
    SubcategoriaIn,
    SubcategoriaOut,
    SubcategoriaUpdate,
)

router = APIRouter(prefix="/catalogo", tags=["catalogo"])


# --- Categorías

@router.get("/categorias", response_model=list[CategoriaOut])
def list_categorias(current_user: CurrentUser, repo: RepoDep, estado: str | None = None) -> list[CategoriaOut]:
    return [CategoriaOut.from_row(row) for row in repo.list_categorias(estado=estado)]


@router.post("/categorias", response_model=CategoriaOut, status_code=201)
def create_categoria(
    body: CategoriaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "crear")
) -> CategoriaOut:
    cat_id = repo.create_categoria(category_code=body.category_code, nombre=body.nombre, created_at=now_iso())
    return CategoriaOut.from_row(repo.get_categoria(cat_id))


@router.put("/categorias/{categoria_id}", response_model=CategoriaOut)
def update_categoria(
    categoria_id: int,
    body: CategoriaUpdate,
    current_user: CurrentUser,
    repo: RepoDep,
    _: dict = require_permission("categorias", "editar"),
) -> CategoriaOut:
    repo.update_categoria(categoria_id, nombre=body.nombre, estado=body.estado, usuario_id=current_user["id"])
    return CategoriaOut.from_row(repo.get_categoria(categoria_id))


# --- Subcategorías

@router.get("/subcategorias", response_model=list[SubcategoriaOut])
def list_subcategorias(
    current_user: CurrentUser, repo: RepoDep, category_id: int | None = None, estado: str | None = None
) -> list[SubcategoriaOut]:
    return [SubcategoriaOut.from_row(row) for row in repo.list_subcategorias(category_id=category_id, estado=estado)]


@router.post("/subcategorias", response_model=SubcategoriaOut, status_code=201)
def create_subcategoria(
    body: SubcategoriaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "crear")
) -> SubcategoriaOut:
    sub_id = repo.create_subcategoria(
        category_id=body.category_id,
        subcategory_code=body.subcategory_code,
        nombre=body.nombre,
        created_at=now_iso(),
    )
    return SubcategoriaOut.from_row(repo.get_subcategoria(sub_id))


@router.put("/subcategorias/{subcategoria_id}", response_model=SubcategoriaOut)
def update_subcategoria(
    subcategoria_id: int,
    body: SubcategoriaUpdate,
    current_user: CurrentUser,
    repo: RepoDep,
    _: dict = require_permission("categorias", "editar"),
) -> SubcategoriaOut:
    repo.update_subcategoria(subcategoria_id, nombre=body.nombre, estado=body.estado, usuario_id=current_user["id"])
    return SubcategoriaOut.from_row(repo.get_subcategoria(subcategoria_id))


# --- Familias

@router.get("/familias", response_model=list[FamiliaOut])
def list_familias(current_user: CurrentUser, repo: RepoDep) -> list[FamiliaOut]:
    return [FamiliaOut.from_row(row) for row in repo.list_familias()]


@router.post("/familias", response_model=FamiliaOut, status_code=201)
def create_familia(
    body: FamiliaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "crear")
) -> FamiliaOut:
    fam_id = repo.create_familia(category_id=body.category_id, nombre=body.nombre, created_at=now_iso())
    return FamiliaOut.from_row(repo.get_familia(fam_id))


@router.put("/familias/{familia_id}", response_model=FamiliaOut)
def update_familia(
    familia_id: int,
    body: FamiliaUpdate,
    current_user: CurrentUser,
    repo: RepoDep,
    _: dict = require_permission("categorias", "editar"),
) -> FamiliaOut:
    repo.update_familia(familia_id, nombre=body.nombre, usuario_id=current_user["id"])
    return FamiliaOut.from_row(repo.get_familia(familia_id))


# --- Servicios

@router.get("/servicios", response_model=list[ServicioOut])
def list_servicios(
    current_user: CurrentUser,
    repo: RepoDep,
    subcategory_id: int | None = None,
    category_id: int | None = None,
    estado: str | None = None,
    q: str | None = None,
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
) -> list[ServicioChoice]:
    """Búsqueda por código o nombre — usada para seleccionar servicio en expedientes."""
    return [ServicioChoice.from_row(row) for row in repo.servicio_choices(q=q, estado=estado, limit=limit)]


@router.post("/servicios", response_model=ServicioOut, status_code=201)
def create_servicio(
    body: ServicioIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "crear")
) -> ServicioOut:
    svc_id = repo.create_servicio(
        subcategory_id=body.subcategory_id,
        nombre=body.nombre,
        etiquetas=body.etiquetas,
        unidad_cobro=body.unidad_cobro,
        responsable_sugerido=body.responsable_sugerido,
        tarifa_referencia_text=str(body.tarifa_referencia) if body.tarifa_referencia is not None else "",
        costo_referencia_text=str(body.costo_referencia) if body.costo_referencia is not None else "",
        horas_estandar=body.horas_estandar,
        estado=body.estado,
        created_at=now_iso(),
    )
    return ServicioOut.from_row(repo.get_servicio(svc_id))


@router.put("/servicios/{servicio_id}", response_model=ServicioOut)
def update_servicio(
    servicio_id: int,
    body: ServicioUpdate,
    current_user: CurrentUser,
    repo: RepoDep,
    _: dict = require_permission("categorias", "editar"),
) -> ServicioOut:
    repo.update_servicio(
        servicio_id,
        nombre=body.nombre,
        etiquetas=body.etiquetas,
        unidad_cobro=body.unidad_cobro,
        responsable_sugerido=body.responsable_sugerido,
        tarifa_referencia_text=str(body.tarifa_referencia) if body.tarifa_referencia is not None else "",
        costo_referencia_text=str(body.costo_referencia) if body.costo_referencia is not None else "",
        horas_estandar=body.horas_estandar,
        estado=body.estado,
        usuario_id=current_user["id"],
    )
    return ServicioOut.from_row(repo.get_servicio(servicio_id))


# --- Historial

@router.get("/historial", response_model=list[HistorialEntryOut])
def historial(current_user: CurrentUser, repo: RepoDep, tipo_registro: str, entity_id: int) -> list[HistorialEntryOut]:
    return [HistorialEntryOut.from_row(row) for row in repo.historial_catalogo(tipo_registro=tipo_registro, entity_id=entity_id)]
