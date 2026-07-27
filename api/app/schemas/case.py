from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CaseIn(BaseModel):
    client_id: int
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    notes: str = ""
    service_product_id: int | None = None
    internal_ref: str = ""
    official_ref: str = ""
    opposing_party: str = ""
    court_entity: str = ""
    responsible_username: str = ""
    service_id: int | None = None
    honorarios_contratados: float | None = None
    costos_directos_estimados: float | None = None
    mes_cobro_esperado: str | None = None
    estado_cobro: str = "En ejecución"
    fecha_cierre_estimada: str | None = None
    proxima_accion: str = ""


class CaseUpdate(BaseModel):
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str = ""
    service_product_id: int | None = None
    internal_ref: str = ""
    official_ref: str = ""
    opposing_party: str = ""
    court_entity: str = ""
    responsible_username: str = ""
    service_id: int | None = None
    honorarios_contratados: float | None = None
    costos_directos_estimados: float | None = None
    mes_cobro_esperado: str | None = None
    estado_cobro: str = "En ejecución"
    fecha_cierre_estimada: str | None = None
    fecha_cierre_real: str | None = None
    proxima_accion: str = ""


class CaseOut(BaseModel):
    id: int
    client_id: int
    client_name: str | None = None
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str | None = None
    service_product_id: int | None = None
    product_name: str | None = None
    internal_ref: str | None = None
    official_ref: str | None = None
    opposing_party: str | None = None
    court_entity: str | None = None
    responsible_username: str | None = None
    created_at: str
    service_id: int | None = None
    service_code: str | None = None
    service_nombre: str | None = None
    subcategory_id: int | None = None
    subcategory_code: str | None = None
    subcategory_nombre: str | None = None
    category_id: int | None = None
    category_code: str | None = None
    category_nombre: str | None = None
    family_id: int | None = None
    family_code: str | None = None
    family_nombre: str | None = None
    honorarios_contratados: float = 0
    costos_directos_estimados: float = 0
    costos_directos_reales: float = 0
    saldo_pendiente: float = 0
    mes_cobro_esperado: str | None = None
    estado_cobro: str = "En ejecución"
    fecha_cierre_estimada: str | None = None
    fecha_cierre_real: str | None = None
    dias_duracion: int | None = None
    proxima_accion: str | None = None
    opportunity_id: int | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseOut:
        d = dict(row)
        d["honorarios_contratados"] = (d.pop("honorarios_contratados_cents", 0) or 0) / 100
        d["costos_directos_estimados"] = (d.pop("costos_directos_estimados_cents", 0) or 0) / 100
        d["costos_directos_reales"] = (d.pop("costos_directos_reales_cents", 0) or 0) / 100
        d["saldo_pendiente"] = (d.pop("saldo_pendiente_cents", 0) or 0) / 100
        return cls(**d)


class TiempoAtencionOut(BaseModel):
    service_code: str | None
    service_nombre: str | None
    category_code: str | None
    category_nombre: str | None
    total_casos: int
    casos_cerrados: int
    dias_promedio: float | None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> TiempoAtencionOut:
        d = dict(row)
        d["dias_promedio"] = float(d["dias_promedio"]) if d.get("dias_promedio") is not None else None
        return cls(**d)


class GlobalCaseTaskOut(BaseModel):
    id: int
    case_id: int
    case_title: str
    case_status: str
    client_name: str | None = None
    client_id: int
    title: str
    done: bool
    due_date: str | None = None
    notes: str | None = None
    completed_notes: str | None = None
    responsible_username: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> "GlobalCaseTaskOut":
        d = dict(row)
        d["done"] = bool(d.get("done", 0))
        return cls(**d)


class CaseAttachmentOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    original_name: str
    stored_path: str
    created_at: str
    session_date: str | None = None
    session_type: str | None = None
    task_title: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CaseTaskIn(BaseModel):
    title: str
    due_date: str | None = None
    notes: str | None = None
    responsible_username: str = ""


class CaseTaskDone(BaseModel):
    done: bool
    completed_notes: str | None = None


class CaseTaskNotesUpdate(BaseModel):
    notes: str | None = None
    completed_notes: str | None = None


class CaseTaskOut(BaseModel):
    id: int
    case_id: int
    title: str
    done: bool
    due_date: str | None = None
    notes: str | None = None
    completed_notes: str | None = None
    responsible_username: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseTaskOut:
        d = dict(row)
        d["done"] = bool(d.get("done", 0))
        return cls(**d)
