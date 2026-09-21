from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TareaInicialIn(BaseModel):
    titulo: str
    due_date: str | None = None
    notes: str | None = None
    es_critico: bool = False


class CaseIn(BaseModel):
    client_id: int
    title: str
    status: str
    priority: str
    opened_at: str
    notes: str = ""
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
    tareas_iniciales: list[TareaInicialIn] = []


class CaseUpdate(BaseModel):
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str = ""
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
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str | None = None
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
    archived_at: str | None = None

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
    case_responsible_username: str | None = None
    es_critico: bool = False
    origen: str = "manual"
    monto_adicional: float = 0
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> "GlobalCaseTaskOut":
        d = dict(row)
        d["done"] = bool(d.get("done", 0))
        d["es_critico"] = bool(d.get("es_critico", 0))
        d["monto_adicional"] = (d.pop("monto_adicional_cents", 0) or 0) / 100
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
    es_critico: bool = False
    # Lo que se le cobra de mas al cliente (sube los honorarios del expediente).
    monto_adicional: float | None = None
    autorizado_por: str = ""
    fecha_autorizacion: str | None = None
    # Lo que costo hacerla (genera el costo directo del expediente).
    costo_real: float | None = None
    costo_account_id: int | None = None
    costo_es_reembolsable: bool = False


class CaseTaskUpdate(CaseTaskIn):
    completed_at: str | None = None


class CaseTaskDone(BaseModel):
    done: bool
    completed_notes: str | None = None


class CaseTaskNotesUpdate(BaseModel):
    notes: str | None = None
    completed_notes: str | None = None


class CaseTaskCriticoUpdate(BaseModel):
    es_critico: bool


class CaseTaskResponsibleUpdate(BaseModel):
    responsible_username: str | None = None


class CaseTaskOut(BaseModel):
    id: int
    case_id: int
    title: str
    done: bool
    due_date: str | None = None
    notes: str | None = None
    completed_notes: str | None = None
    responsible_username: str | None = None
    es_critico: bool = False
    origen: str = "manual"
    monto_adicional: float = 0
    costo_real: float = 0
    costo_account_id: int | None = None
    costo_es_reembolsable: bool = False
    cost_id: int | None = None
    autorizado_por: str | None = None
    fecha_autorizacion: str | None = None
    completed_at: str | None = None
    completed_by: str | None = None
    invoice_id: int | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseTaskOut:
        d = dict(row)
        d["done"] = bool(d.get("done", 0))
        d["es_critico"] = bool(d.get("es_critico", 0))
        d["costo_es_reembolsable"] = bool(d.get("costo_es_reembolsable", False))
        d["monto_adicional"] = (d.pop("monto_adicional_cents", 0) or 0) / 100
        d["costo_real"] = (d.pop("costo_real_cents", 0) or 0) / 100
        return cls(**{k: v for k, v in d.items() if k in cls.model_fields})


class PlantillaTareaIn(BaseModel):
    titulo: str
    orden: int = 0
    dias_plazo_relativo: int | None = None
    es_critico_default: bool = False
    costo_estimado: float | None = None
    honorario_sugerido: float | None = None


class PlantillaTareaOut(BaseModel):
    id: int
    service_id: int
    titulo: str
    orden: int
    dias_plazo_relativo: int | None = None
    es_critico_default: bool = False
    costo_estimado: float = 0
    honorario_sugerido: float = 0
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> PlantillaTareaOut:
        d = dict(row)
        d["es_critico_default"] = bool(d.get("es_critico_default", 0))
        d["costo_estimado"] = (d.pop("costo_estimado_cents", 0) or 0) / 100
        d["honorario_sugerido"] = (d.pop("honorario_sugerido_cents", 0) or 0) / 100
        return cls(**{k: v for k, v in d.items() if k in cls.model_fields})


class CaseHonorariosLogOut(BaseModel):
    id: int
    case_id: int
    origen_tipo: str
    origen_id: int
    monto: float
    motivo: str
    username: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseHonorariosLogOut:
        d = dict(row)
        d["monto"] = (d.pop("monto_cents", 0) or 0) / 100
        return cls(**d)


class CaseTimeEntryIn(BaseModel):
    work_date: str
    hours: float
    description: str | None = None
    billable: bool = True
    username: str | None = None  # si no se manda, el backend usa el usuario actual


class CaseTimeEntryOut(BaseModel):
    id: int
    case_id: int
    username: str
    work_date: str
    hours: float
    description: str | None = None
    billable: bool = True
    invoice_id: int | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> "CaseTimeEntryOut":
        d = dict(row)
        d["billable"] = bool(d.get("billable", 1))
        d["hours"] = float(d["hours"])
        return cls(**d)


class ConflictoInteresOut(BaseModel):
    clientes: list[dict]
    casos: list[dict]
