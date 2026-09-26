from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, RepoDep, require_permission
from aglegal.governance import propose, decide
from pydantic import BaseModel
from ..access import require_any
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
    ResumenMensualOut,
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


@router.post("/cuentas", status_code=201)
def create_cuenta(body: CuentaIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> dict:
    return propose(repo,entity='cuenta',entity_id=None,action='crear',payload=body.model_dump(exclude={'motivo'}),reason=body.motivo,actor=current_user['username'])


@router.put("/cuentas/{cuenta_id}")
def update_cuenta(cuenta_id: int, body: CuentaUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> dict:
    return propose(repo,entity='cuenta',entity_id=cuenta_id,action='editar',payload=body.model_dump(exclude={'motivo'}),reason=body.motivo,actor=current_user['username'])


# --- Personal

@router.get('/personal/choices', dependencies=[require_any('expedientes.crear','expedientes.editar','pipeline.editar','comisiones.ver','comisiones.editar')])
def personal_choices(current_user: CurrentUser, repo: RepoDep):
    return [dict(id=r['id'],persona=r['persona']) for r in repo.list_personal(estado='Activo')]


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
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, account_id=body.account_id, created_at=now_iso(),
    )
    return PersonaOut.from_row(repo.get_persona(persona_id))


@router.put("/personal/{persona_id}", response_model=PersonaOut)
def update_persona(persona_id: int, body: PersonaUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> PersonaOut:
    repo.update_persona(
        persona_id, persona=body.persona, cargo=body.cargo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, account_id=body.account_id, estado=body.estado,
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
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, account_id=body.account_id, created_at=now_iso(),
    )
    return GastoFijoOut.from_row(repo.get_gasto_fijo(gasto_id))


@router.put("/gastos-fijos/{gasto_id}", response_model=GastoFijoOut)
def update_gasto_fijo(gasto_id: int, body: GastoFijoUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> GastoFijoOut:
    repo.update_gasto_fijo(
        gasto_id, concepto=body.concepto, tipo=body.tipo,
        monto_mensual_text=str(body.monto_mensual) if body.monto_mensual is not None else "",
        mes_inicio=body.mes_inicio, mes_fin=body.mes_fin, account_id=body.account_id, estado=body.estado,
    )
    return GastoFijoOut.from_row(repo.get_gasto_fijo(gasto_id))


@router.get("/gastos-fijos-comparativo")
def comparativo_gastos_fijos(current_user: CurrentUser, repo: RepoDep, mes: str,
                             _: dict = require_permission("finanzas", "ver")) -> dict:
    """Lo presupuestado contra lo pagado, concepto por concepto."""
    d = repo.comparativo_gastos_fijos(mes=mes)
    return {
        "mes": d["mes"],
        "total_presupuestado": d["total_presupuestado_cents"] / 100,
        "total_pagado": d["total_pagado_cents"] / 100,
        "brecha": d["brecha_cents"] / 100,
        "conceptos": [
            {
                "id": c["id"], "expense_code": c["expense_code"], "concepto": c["concepto"], "tipo": c["tipo"],
                "account_code": c["account_code"], "account_nombre": c["account_nombre"],
                "presupuestado": c["presupuestado_cents"] / 100,
                "pagado": (c["pagado_cents"] / 100) if c["pagado_cents"] is not None else None,
                "brecha": (c["brecha_cents"] / 100) if c["brecha_cents"] is not None else None,
            }
            for c in d["conceptos"]
        ],
        "no_presupuestado": [
            {"account_code": x["account_code"], "account_nombre": x["account_nombre"],
             "pagado": x["pagado_cents"] / 100}
            for x in d["no_presupuestado"]
        ],
    }


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


@router.post("/forecast", status_code=201)
def create_forecast(body: ForecastIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "crear")) -> dict:
    return propose(repo,entity='forecast',entity_id=None,action='crear',payload=body.model_dump(exclude={'motivo'}),reason=body.motivo,actor=current_user['username'])


@router.put("/forecast/{forecast_id}")
def update_forecast(forecast_id: int, body: ForecastUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("finanzas", "editar")) -> dict:
    return propose(repo,entity='forecast',entity_id=forecast_id,action='editar',payload=body.model_dump(exclude={'motivo'}),reason=body.motivo,actor=current_user['username'])


@router.delete("/forecast/{forecast_id}")
def delete_forecast(forecast_id: int, current_user: CurrentUser, repo: RepoDep, motivo: str = '', _: dict = require_permission("finanzas", "eliminar")):
    return propose(repo,entity='forecast',entity_id=forecast_id,action='eliminar',payload={},reason=motivo,actor=current_user['username'])



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
            "semaforo_casos": r["semaforo_casos"],
            "meta_ingresos": r["meta_ingresos_cents"] / 100, "ingresos_reales": r["ingresos_reales_cents"] / 100,
            "cumplimiento_ingresos_pct": r["cumplimiento_ingresos_pct"],
            "semaforo_ingresos": r["semaforo_ingresos"],
            "brecha_ingresos": r["brecha_ingresos_cents"] / 100,
            "costos_directos_reales": r["costos_directos_reales_cents"] / 100,
            "utilidad_directa_meta": r["utilidad_directa_meta_cents"] / 100,
            "utilidad_directa_real": r["utilidad_directa_real_cents"] / 100,
            "cumplimiento_utilidad_pct": r["cumplimiento_utilidad_pct"],
            "semaforo_utilidad": r["semaforo_utilidad"],
            "ticket_real": (r["ticket_real_cents"] / 100) if r["ticket_real_cents"] is not None else None,
        }
        for r in rows
    ]


@router.get("/resumen-mensual", response_model=ResumenMensualOut)
def resumen_mensual(
    current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str,
    _: dict = require_permission("finanzas", "ver"),
) -> ResumenMensualOut:
    """Meta vs. realidad mes a mes — equivalente a la hoja 17 del Archivo Maestro."""
    return ResumenMensualOut.from_calc(repo.resumen_mensual(desde=desde, hasta=hasta))


@router.get("/ticket-promedio")
def ticket_promedio(
    current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str, agrupar_por: str = "servicio",
    _: dict = require_permission("finanzas", "ver"),
) -> dict:
    """KPI-009 — ingreso cobrado promedio por expediente, global y por servicio/categoria/familia."""
    d = repo.ticket_promedio(desde=desde, hasta=hasta, agrupar_por=agrupar_por)
    return {
        "desde": d["desde"], "hasta": d["hasta"], "agrupar_por": d["agrupar_por"],
        "ingresos": d["ingresos_cents"] / 100,
        "casos_cobrados": d["casos_cobrados"],
        "ticket_promedio": (d["ticket_promedio_cents"] / 100) if d["ticket_promedio_cents"] is not None else None,
        "detalle": [
            {
                "codigo": r["codigo"], "nombre": r["nombre"],
                "ingresos": r["ingresos_cents"] / 100, "casos_cobrados": r["casos_cobrados"],
                "ticket_promedio": (r["ticket_promedio_cents"] / 100) if r["ticket_promedio_cents"] is not None else None,
            }
            for r in d["detalle"]
        ],
    }


@router.get("/ingresos-por-origen")
def ingresos_por_origen(
    current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str, agrupar_por: str = "originador",
    _: dict = require_permission("finanzas", "ver"),
) -> list[dict]:
    """KPI-015 — ingresos y utilidad directa por originador del negocio y tipo de origen."""
    return [
        {
            "origen": r["origen"], "tipo_origen": r["tipo_origen"], "casos": r["casos"],
            "ingresos": r["ingresos_cents"] / 100,
            "costos_directos": r["costos_directos_cents"] / 100,
            "utilidad_directa": r["utilidad_directa_cents"] / 100,
            "margen_pct": r["margen_pct"], "expedientes": r["expedientes"],
        }
        for r in repo.ingresos_por_origen(desde=desde, hasta=hasta, agrupar_por=agrupar_por)
    ]


@router.get("/dias-cobro")
def dias_cobro(
    current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str, service_id: int | None = None, client_id: int | None = None,
    _: dict = require_permission("finanzas", "ver"),
) -> dict:
    """KPI-016 — dias promedio entre la facturacion (o el cierre) y el cobro."""
    return repo.dias_promedio_cobro(desde=desde, hasta=hasta,service_id=service_id,client_id=client_id)


@router.get("/aging-cartera")
def aging_cartera(
    current_user: CurrentUser, repo: RepoDep, fecha_corte: str | None = None,
    _: dict = require_permission("finanzas", "ver"),
) -> dict:
    """Antiguedad del saldo por cobrar, por tramos de atraso."""
    d = repo.aging_cartera(fecha_corte=fecha_corte)
    return {
        "fecha_corte": d["fecha_corte"],
        "total_pendiente": d["total_pendiente_cents"] / 100,
        "tramos": [{"tramo": t["tramo"], "saldo": t["saldo_cents"] / 100, "casos": t["casos"]} for t in d["tramos"]],
        "casos": [
            {
                "case_id": c["case_id"], "title": c["title"], "client_name": c["client_name"],
                "estado_cobro": c["estado_cobro"], "mes_cobro_esperado": c["mes_cobro_esperado"],
                "saldo_pendiente": c["saldo_pendiente_cents"] / 100,
                "dias_atraso": c["dias_atraso"], "tramo": c["tramo"],
            }
            for c in d["casos"]
        ],
    }


@router.get("/utilidad-operativa-real")
def utilidad_operativa_real(current_user: CurrentUser, repo: RepoDep, mes: str, _: dict = require_permission("finanzas", "ver")) -> dict:
    r = repo.utilidad_operativa_real(mes=mes)
    return {
        "mes": r["mes"],
        "ingresos_reales": r["ingresos_reales_cents"] / 100,
        "costos_directos_reales": r["costos_directos_reales_cents"] / 100,
        "utilidad_directa_real": r["utilidad_directa_real_cents"] / 100,
        "gastos_fijos": r["gastos_fijos_cents"] / 100,
        "comisiones": r["comisiones_cents"] / 100,
        "gastos_operativos_reales": r["gastos_operativos_reales_cents"] / 100,
        "brecha_gastos": r["brecha_gastos_cents"] / 100,
        "utilidad_operativa_real": r["utilidad_operativa_real_cents"] / 100,
        "utilidad_operativa_caja": r["utilidad_operativa_caja_cents"] / 100,
        "margen_operativo_real_pct": r["margen_operativo_real_pct"],
    }


@router.get("/centros-costo")
def centros_costo(current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str,
                  _: dict = require_permission("finanzas", "ver")) -> dict:
    """En qué centro de costo se fue el dinero del período — gastos operativos y costos
    directos juntos, que es como se lee un estado de resultados por área."""
    d = repo.gastos_por_centro_costo(desde=desde, hasta=hasta)
    return {
        "desde": d["desde"], "hasta": d["hasta"], "total": d["total_cents"] / 100,
        "centros": [
            {
                "centro_costo": c["centro_costo"],
                "total": c["total_cents"] / 100,
                "gastos_operativos": c["gastos_operativos_cents"] / 100,
                "costos_directos": c["costos_directos_cents"] / 100,
                "porcentaje": c["porcentaje"],
                "cuentas": [
                    {"account_code": x["account_code"], "cuenta": x["cuenta"], "total": x["total_cents"] / 100}
                    for x in c["cuentas"]
                ],
            }
            for c in d["centros"]
        ],
    }


class FinancialDecision(BaseModel):
    approve: bool
    evidence: str


@router.get('/propuestas', dependencies=[require_permission('finanzas','ver')])
def financial_proposals(current_user: CurrentUser, repo: RepoDep):
    labels={}
    for field,table,code in [('category_id','categorias','category_code'),('family_id','familias','family_code')]:
        for row in repo.conn.execute(f'SELECT id,nombre,{code} AS code FROM {table}').fetchall():
            labels[f"{field}:{row['id']}"]=f"{row['code']} · {row['nombre']}"
    return [dict(r,reference_labels=labels) for r in repo.conn.execute('SELECT * FROM financial_requests ORDER BY id DESC').fetchall()]


@router.post('/propuestas/{request_id}/decision')
def financial_decision(request_id: int, body: FinancialDecision, current_user: AdminRequired, repo: RepoDep):
    return decide(repo,request_id,approve=body.approve,evidence=body.evidence,actor=current_user['username'])


@router.get('/explorador', dependencies=[require_permission('finanzas','ver')])
def financial_explorer(current_user: CurrentUser, repo: RepoDep, desde: str, hasta: str,
    category_id: int | None = None, subcategory_id: int | None = None, service_id: int | None = None,
    family_id: int | None = None, client_id: int | None = None, origen_negocio: str | None = None):
    from aglegal.indicators import explorer
    return explorer(repo,desde=desde,hasta=hasta,category_id=category_id,subcategory_id=subcategory_id,
        service_id=service_id,family_id=family_id,client_id=client_id,origen_negocio=origen_negocio)
