# Traspaso — Auditoría contra el Archivo Maestro y simplificación del sistema

**Fecha:** 2026-09-19 · **Rama:** `auditoria-especificacion` en ambos repos (sin fusionar a `master`, sin push)
- Backend: `C:\Users\josue\Documents\PROYECTOAGLEGAL` — commit `5cd6d3d`
- Frontend: `C:\Users\josue\Documents\PROYECTOAGLEGALFRONT` — commit `1d5af1b`

Para retomar en otra herramienta: leer este archivo, luego `PLAN_CATALOGO_FINANCIERO.md` y `AUDITORIA_USO_ABOGADO.md` (contexto previo).

## 1. Auditoría (contra `AG Legal Archivo Maestro2026.xlsx`, hojas 00 y 13 como especificación)

**Cumple:** los datos cargados coinciden con el Excel (16 categorías, 79 subcategorías, 205 servicios, 36 cuentas, personal, gastos fijos, metas jul–dic). La fórmula de comisión reproduce los 4 ejemplos de `12_Reglas_Comision` ($60/$196/$355/$580).

**Corregido (críticos):**
1. Editar un cobro no recalculaba la comisión → ahora se revierte con ajuste trazable y se recalcula.
2. Borrar un cobro borraba su comisión en cascada → queda revertida en el historial (migración v38).
3. Cobros previos a configurar originadores nunca generaban comisión → se reconocen al guardar originadores; "Ganado" con origen Andrea la asigna como originadora y copia los honorarios estimados.
4. Una comisión revertida seguía contando para el tramo del mes → ya no.
5. Dashboard sumaba montos brutos (con IVA y fondos de terceros) → neto operativo en todos los agregados.
6. Cumplimiento por familia usaba la categoría del servicio → usa la familia de la cuenta de ingreso (04_Plan_Cuentas, col. H).
7. Un cobro podía exceder el saldo del expediente → se rechaza salvo marcarlo como ajuste (`incomes.es_ajuste`).
8. Purgar cliente/expediente borraba historial financiero → bloqueado si hay cobros, costos, comisiones o facturas.
9. Marcar factura como "Pagada" fallaba (faltaba cuenta contable obligatoria) → toma la cuenta por categoría y genera la comisión.

**Corregido (recorrido como abogada):** DUI/documento único por cliente; mes de cobro anterior a la apertura también al editar; el correo de aviso de cita consultaba la base desde un hilo con la conexión ya cerrada.

**Pendiente — hallazgos 🟠 no atacados todavía:**
- Aprobar solicitudes del catálogo sin llenar la revisión de duplicidad (GOB-003); aprobador es texto libre, no el usuario autenticado.
- Código de subcategoría: acepta 2–4 letras (debe ser 3), no valida ≠ categoría ni unicidad global.
- Servicios de categoría/subcategoría inactiva siguen seleccionables; el backend acepta expediente con servicio inactivo.
- Código de servicio no obligatorio en ingresos jurídicos/costos directos.
- Utilidad operativa usa el presupuesto de gastos fijos, no egresos reales; `afecta_utilidad` no se usa.
- Probabilidad de cobro es constante por estado, no un campo editable.

**Pendiente — faltantes 🟡:** descripción de categoría; `client_code`; `movement_code` (MOV-2026-0001) y estado de movimiento; origen/tipo de origen propios del expediente; formato `EXP-2026-0001` (hoy `EXP-MM-AAAA-0001`); KPIs: resumen mensual de la hoja 17, aging, días de cobro (KPI-016), matriz frecuencia vs margen, ingresos/utilidad por origen; búsqueda de servicios por etiquetas.

**Decisiones que necesita el despacho:**
- ¿Pasar el expediente a "Cobrado" automáticamente cuando el saldo llega a $0?
- ¿El backend debe bloquear citas traslapadas (hoy solo avisa la pantalla)?
- Rol Abogado: no puede cancelar citas; sí ve/edita nóminas de todo el personal y puede crear cuentas contables. Rol Asistente no ve usuarios (selector de responsable vacío).
- Cobro de factura: cuenta por categoría (compraventa NOT-EST cae en ING-NOT-001/FAM-01, el presupuesto la pone en ING-RAI-001/FAM-03); la factura no desglosa IVA.
- Solicitud de servicio nuevo exige "código propuesto" aunque el sistema lo genera (GOB-004).
- Inconsistencias del propio Excel: meta FAM-03 julio $1,300 (hoja 08) vs $1,500 (hoja 15); 205 servicios con tarifa $0 y "Por definir"; subcategorías EST y CNS repetidas; semáforo 90% (KPI-001) vs 85% (KPI-003); tipo de origen con 3 valores pero reglas para 2; histórico mar–jul con códigos que no existen en el catálogo.

## 2. Consistencia de vistas y flujos (frontend)

- Tareas: un solo formulario y fila (`src/components/tasks.tsx`) en la página Tareas y en el expediente.
- Citas: un solo diálogo (`src/components/SessionDialog.tsx`) en la Agenda y en el expediente.
- Enlaces profundos: `/cases?case_id=ID[&tab=tasks]`, `/cases?new=1&client_id=ID`, `/clients?search=`, `/tasks?case=ID`, `/sessions?new=1&client_id=ID`, `/cashflow?cobro=1&case_id=ID`.
- Cliente inline al crear expediente (`src/components/QuickClientForm.tsx`), título sugerido, el expediente se abre al guardar, "¿Qué sigue?" tras crear cliente, botón global "+ Nuevo", panel del expediente con saldo al día y acciones (Editar, Agendar, Tareas, Registrar cobro).
- Backend nuevo: `GET /cases/{id}`; `case_title` en citas.
- **No verificado en navegador** (requiere iniciar sesión). Verificado: `npx tsc --noEmit` y `npm run build` limpios.

## 3. Cómo verificar

```bash
cd C:\Users\josue\Documents\PROYECTOAGLEGAL
python -m pytest -q
```
148 pruebas en verde (incluye `tests/test_auditoria_especificacion.py`). Las pruebas corren en el schema aislado `aglegal_test`; no tocan los datos reales.

```bash
cd C:\Users\josue\Documents\PROYECTOAGLEGALFRONT
npx tsc --noEmit && npm run build
```

La migración v38 ya está aplicada en la base local.

## 4. Avisos

- **Correo real:** el `.env` tiene una clave de Resend activa. Crear citas desde pruebas o desde la app envía correos reales a los clientes; en pruebas desactivarla (`resend_api_key = ""`).
- **Cambios ajenos sin commit en el backend:** `requirements-dev.txt`, `tests/test_api_modulos.py`, el Excel y el PDF de propuesta — no se incluyeron en la rama.
- La búsqueda de duplicados del catálogo (`pg_trgm`) falla solo en el schema de pruebas (la extensión vive en `public`); en la base real funciona.
