from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.finanzas import (
    CarteraPonderadaOut,
    CuentaIn,
    CuentaOut,
    CuentaUpdate,
    ForecastIn,
    ForecastOut,
    ForecastUpdate,
    GastoFijoIn,
    GastoFijoOut,
    GastoFijoUpdate,
    PersonaIn,
    PersonaOut,
    PersonaUpdate,
    ProyeccionCierreMesOut,
    PuntoEquilibrioOut,
    SupuestosIn,
    SupuestosOut,
    SupuestosUpdate,
)

router = APIRouter(prefix="/finanzas", tags=["finanzas"])


# --- Plan de cuentas

@router.get("/cuentas", response_model=list[CuentaOut])
def list_cuentas(
    current_user: CurrentUser, repo: RepoDep, tipo: str | None = None, estado: str | None = None,
    _: dict = require_permission("finanzas", "ver"),
) -> list[CuentaOut]:
    return [CuentaOut.from_row(row) for row in repo.list_plan_cuentas(tipo=tipo, estado=estado)]


@router.post("/cuentas", response_model=CuentaOut, status_code=201)
def create_cuenta(body: CuentaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> CuentaOut:
    cuenta_id = repo.create_cuenta(
        account_code=body.account_code, tipo=body.tipo, grupo=body.grupo, subgrupo=body.subgrupo,
        nombre=body.nombre, naturaleza=body.naturaleza, category_id=body.category_id, family_id=body.family_id,
        centro_costo=body.centro_costo, afecta_utilidad=body.afecta_utilidad, regla_de_uso=body.regla_de_uso,
        created_at=now_iso(),
    )
    return CuentaOut.from_row(repo.get_cuenta(cuenta_id))


@router.put("/cuentas/{cuenta_id}", response_model=CuentaOut)
def update_cuenta(cuenta_id: int, body: CuentaUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> CuentaOut:
    repo.update_cuenta(
        cuenta_id, grupo=body.grupo, subgrupo=body.subgrupo, nombre=body.nombre, naturaleza=body.naturaleza,
        category_id=body.category_id, family_id=body.family_id, centro_costo=body.centro_costo,
        afecta_utilidad=body.afecta_utilidad, regla_de_uso=body.regla_de_uso, estado=body.estado,
    )
    return CuentaOut.from_row(repo.get_cuenta(cuenta_id))


# --- Personal

@router.get("/personal", response_model=list[PersonaOut])
def list_personal(
    current_user: CurrentUser, repo: RepoDep, estado: str | None = None, _: dict = require_permission("finanzas", "ver")
) -> list[PersonaOut]:
    return [PersonaOut.from_row(row) for row in repo.list_personal(estado=estado)]


@router.post("/personal", response_model=PersonaOut, status_code=201)
def create_persona(body: PersonaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> PersonaOut:
    persona_id = repo.create_persona(
        persona=body.persona, cargo=body.cargo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, created_at=now_iso(),
    )
    return PersonaOut.from_row(repo.get_persona(persona_id))


@router.put("/personal/{persona_id}", response_model=PersonaOut)
def update_persona(persona_id: int, body: PersonaUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> PersonaOut:
    repo.update_persona(
        persona_id, persona=body.persona, cargo=body.cargo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, estado=body.estado,
    )
    return PersonaOut.from_row(repo.get_persona(persona_id))


# --- Gastos fijos

@router.get("/gastos-fijos", response_model=list[GastoFijoOut])
def list_gastos_fijos(
    current_user: CurrentUser, repo: RepoDep, estado: str | None = None, tipo: str | None = None,
    _: dict = require_permission("finanzas", "ver"),
) -> list[GastoFijoOut]:
    return [GastoFijoOut.from_row(row) for row in repo.list_gastos_fijos(estado=estado, tipo=tipo)]


@router.post("/gastos-fijos", response_model=GastoFijoOut, status_code=201)
def create_gasto_fijo(body: GastoFijoIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> GastoFijoOut:
    gasto_id = repo.create_gasto_fijo(
        concepto=body.concepto, tipo=body.tipo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, created_at=now_iso(),
    )
    return GastoFijoOut.from_row(repo.get_gasto_fijo(gasto_id))


@router.put("/gastos-fijos/{gasto_id}", response_model=GastoFijoOut)
def update_gasto_fijo(gasto_id: int, body: GastoFijoUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> GastoFijoOut:
    repo.update_gasto_fijo(
        gasto_id, concepto=body.concepto, tipo=body.tipo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, estado=body.estado,
    )
    return GastoFijoOut.from_row(repo.get_gasto_fijo(gasto_id))


# --- Supuestos financieros

@router.get("/supuestos", response_model=list[SupuestosOut])
def list_supuestos(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "ver")) -> list[SupuestosOut]:
    return [SupuestosOut.from_row(row) for row in repo.list_supuestos()]


@router.post("/supuestos", response_model=SupuestosOut, status_code=201)
def create_supuestos(body: SupuestosIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> SupuestosOut:
    sup_id = repo.create_supuestos(
        periodo=body.periodo, costo_variable_pct=body.costo_variable_pct,
        margen_operativo_meta_pct=body.margen_operativo_meta_pct, margen_seguridad_pct=body.margen_seguridad_pct,
        created_at=now_iso(),
    )
    row = next(r for r in repo.list_supuestos() if int(r["id"]) == sup_id)
    return SupuestosOut.from_row(row)


@router.put("/supuestos/{supuestos_id}", response_model=SupuestosOut)
def update_supuestos(supuestos_id: int, body: SupuestosUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> SupuestosOut:
    repo.update_supuestos(
        supuestos_id, costo_variable_pct=body.costo_variable_pct,
        margen_operativo_meta_pct=body.margen_operativo_meta_pct, margen_seguridad_pct=body.margen_seguridad_pct,
    )
    row = next(r for r in repo.list_supuestos() if int(r["id"]) == supuestos_id)
    return SupuestosOut.from_row(row)


# --- Punto de equilibrio

@router.get("/punto-equilibrio", response_model=PuntoEquilibrioOut)
def punto_equilibrio(current_user: CurrentUser, repo: RepoDep, mes: str, _: dict = require_permission("finanzas", "ver")) -> PuntoEquilibrioOut:
    return PuntoEquilibrioOut.from_calc(repo.calcular_punto_equilibrio(mes=mes))


# --- Presupuesto por familia (forecast)

@router.get("/forecast", response_model=list[ForecastOut])
def list_forecast(
    current_user: CurrentUser, repo: RepoDep, mes: str | None = None, family_id: int | None = None,
    _: dict = require_permission("finanzas", "ver"),
) -> list[ForecastOut]:
    return [ForecastOut.from_row(row) for row in repo.list_forecast(mes=mes, family_id=family_id)]


@router.post("/forecast", response_model=ForecastOut, status_code=201)
def create_forecast(body: ForecastIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> ForecastOut:
    forecast_id = repo.create_forecast(
        family_id=body.family_id, mes=body.mes,
        volumen_meta_text=str(body.volumen_meta) if body.volumen_meta is not None else "",
        ticket_objetivo_text=str(body.ticket_objetivo) if body.ticket_objetivo is not None else "",
        margen_directo_objetivo_pct=body.margen_directo_objetivo_pct,
        created_at=now_iso(),
    )
    return ForecastOut.from_row(repo.get_forecast(forecast_id))


@router.put("/forecast/{forecast_id}", response_model=ForecastOut)
def update_forecast(forecast_id: int, body: ForecastUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> ForecastOut:
    repo.update_forecast(
        forecast_id,
        volumen_meta_text=str(body.volumen_meta) if body.volumen_meta is not None else "",
        ticket_objetivo_text=str(body.ticket_objetivo) if body.ticket_objetivo is not None else "",
        margen_directo_objetivo_pct=body.margen_directo_objetivo_pct,
    )
    return ForecastOut.from_row(repo.get_forecast(forecast_id))


@router.delete("/forecast/{forecast_id}", status_code=204)
def delete_forecast(forecast_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "eliminar")):
    repo.delete_forecast(forecast_id)


# --- Cartera ponderada y proyección de cierre de mes

@router.get("/cartera-ponderada", response_model=CarteraPonderadaOut)
def cartera_ponderada(
    current_user: CurrentUser, repo: RepoDep, mes: str | None = None, _: dict = require_permission("finanzas", "ver")
) -> CarteraPonderadaOut:
    return CarteraPonderadaOut.from_calc(repo.cartera_pendiente_ponderada(mes=mes))


@router.get("/proyeccion-cierre-mes", response_model=ProyeccionCierreMesOut)
def proyeccion_cierre_mes(
    current_user: CurrentUser, repo: RepoDep, mes: str, _: dict = require_permission("finanzas", "ver")
) -> ProyeccionCierreMesOut:
    return ProyeccionCierreMesOut.from_calc(repo.proyeccion_cierre_mes(mes=mes))


# --- Cumplimiento por familia (Fase 9)

@router.get("/cumplimiento-familia")
def cumplimiento_familia(current_user: CurrentUser, repo: RepoDep, mes: str, _: dict = require_permission("finanzas", "ver")) -> list[dict]:
    rows = repo.cumplimiento_por_familia(mes=mes)
    return [
        {
            "family_id": r["family_id"], "family_code": r["family_code"], "family_nombre": r["family_nombre"],
            "meta_casos": r["meta_casos"], "casos_reales": r["casos_reales"], "cumplimiento_casos_pct": r["cumplimiento_casos_pct"],
            "meta_ingresos": r["meta_ingresos_cents"] / 100, "ingresos_reales": r["ingresos_reales_cents"] / 100,
            "cumplimiento_ingresos_pct": r["cumplimiento_ingresos_pct"],
        }
        for r in rows
    ]
