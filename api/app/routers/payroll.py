from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.payroll import (
    PayrollConfigIn,
    PayrollConfigOut,
    PayrollIn,
    PayrollOut,
    PayrollPreviewIn,
    PayrollPreviewOut,
    PayrollUpdate,
)

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _tramos_a_centavos(tramos) -> list[dict]:
    return [
        {
            "sobre_exceso_de_cents": round(t.sobre_exceso_de * 100),
            "hasta_cents": round(t.hasta * 100) if t.hasta is not None else None,
            "cuota_fija_cents": round(t.cuota_fija * 100),
            "porcentaje_exceso": t.porcentaje_exceso,
        }
        for t in tramos
    ]


@router.get("", response_model=list[PayrollOut])
def list_payroll(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "ver")) -> list[PayrollOut]:
    return [PayrollOut.from_row(row) for row in repo.list_payrolls()]


@router.post("/preview", response_model=PayrollPreviewOut)
def preview_payroll(body: PayrollPreviewIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "crear")) -> PayrollPreviewOut:
    calculo, _config_row = repo.calcular_planilla_preview(
        salario_base_text=str(body.salario_base),
        horas_extra_cantidad=body.horas_extra_cantidad,
        nocturnidad_horas=body.nocturnidad_horas,
        bonificaciones_text=str(body.bonificaciones),
        otros_ingresos_text=str(body.otros_ingresos),
        descuento_faltas_text=str(body.descuento_faltas),
        descuento_prestamos_text=str(body.descuento_prestamos),
        otros_descuentos_text=str(body.otros_descuentos),
        fecha_config=body.fecha,
    )
    return PayrollPreviewOut.from_calculo(calculo)


@router.post("", response_model=PayrollOut, status_code=201)
def create_payroll(body: PayrollIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "crear")) -> PayrollOut:
    payroll_id = repo.create_payroll(
        employee_name=body.employee_name,
        role=body.role,
        period=body.period,
        payment_date=body.payment_date,
        notes=body.notes,
        personal_id=body.personal_id,
        modo=body.modo,
        amount_text=str(body.amount) if body.amount is not None else None,
        salario_base_text=str(body.salario_base) if body.salario_base is not None else "",
        horas_extra_cantidad=body.horas_extra_cantidad,
        nocturnidad_horas=body.nocturnidad_horas,
        bonificaciones_text=str(body.bonificaciones),
        otros_ingresos_text=str(body.otros_ingresos),
        descuento_faltas_text=str(body.descuento_faltas),
        descuento_prestamos_text=str(body.descuento_prestamos),
        otros_descuentos_text=str(body.otros_descuentos),
        created_at=now_iso(),
    )
    return PayrollOut.from_row(repo.get_payroll(payroll_id))


@router.put("/{payroll_id}", response_model=PayrollOut)
def update_payroll(payroll_id: int, body: PayrollUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "editar")) -> PayrollOut:
    repo.update_payroll(
        payroll_id,
        payment_date=body.payment_date,
        notes=body.notes,
        amount_text=str(body.amount),
        username=current_user["username"],
    )
    return PayrollOut.from_row(repo.get_payroll(payroll_id))


@router.get("/{payroll_id}/audit-log")
def get_payroll_audit_log(payroll_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "ver")):
    return [dict(row) for row in repo.list_payroll_audit_log(payroll_id)]


@router.delete("/{payroll_id}", status_code=204)
def delete_payroll(payroll_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "eliminar")):
    repo.delete_payroll(payroll_id)


@router.get("/config/historial", response_model=list[PayrollConfigOut])
def list_payroll_config(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "ver")) -> list[PayrollConfigOut]:
    return [PayrollConfigOut.from_row(row) for row in repo.list_payroll_config_historial()]


@router.get("/config/vigente", response_model=PayrollConfigOut)
def get_payroll_config_vigente(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "ver")) -> PayrollConfigOut:
    return PayrollConfigOut.from_row(repo.get_payroll_config_vigente())


@router.post("/config", response_model=PayrollConfigOut, status_code=201)
def create_payroll_config(body: PayrollConfigIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("nominas", "editar")) -> PayrollConfigOut:
    config_id = repo.create_payroll_config(
        vigente_desde=body.vigente_desde,
        isss_tasa_empleado=body.isss_tasa_empleado,
        isss_tasa_patronal=body.isss_tasa_patronal,
        isss_tope_cotizable_text=str(body.isss_tope_cotizable),
        afp_tasa_empleado=body.afp_tasa_empleado,
        afp_tasa_patronal=body.afp_tasa_patronal,
        afp_tope_cotizable_text=str(body.afp_tope_cotizable),
        tramos_renta=_tramos_a_centavos(body.tramos_renta),
        recargo_hora_extra_pct=body.recargo_hora_extra_pct,
        recargo_nocturnidad_pct=body.recargo_nocturnidad_pct,
        horas_jornada_mensual=body.horas_jornada_mensual,
        notas=body.notas,
        created_at=now_iso(),
    )
    row = next(r for r in repo.list_payroll_config_historial() if r["id"] == config_id)
    return PayrollConfigOut.from_row(row)
