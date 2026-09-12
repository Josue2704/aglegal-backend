# AG Legal — Backend

Sistema de gestión para un despacho de abogados en El Salvador: clientes, expedientes,
pipeline comercial, flujo de caja, facturación, comisiones, gobierno del catálogo maestro
y nómina. En producción desde 2026, con datos reales del despacho.

Este repo es el backend. El frontend (React + TypeScript + Vite) vive en un repositorio
aparte: `aglegal-frontend`.

## Stack
- **API**: FastAPI (`api/app/`) — routers por dominio en `api/app/routers/`, schemas
  Pydantic en `api/app/schemas/`.
- **Acceso a datos**: SQL directo sobre PostgreSQL, sin ORM — todo vive en `aglegal/db.py`
  (conexión, migraciones) y `aglegal/repositories.py` (una clase `Repository` con toda la
  lógica de negocio y las consultas).
- **Autenticación**: JWT + permisos por rol (`aglegal/security.py`, tabla `roles`/`permisos`).
- **Migraciones**: propias, no Alembic — `_migrate()` en `aglegal/db.py` corre en cada
  arranque/request y aplica los `ALTER`/`CREATE` pendientes según `schema_version`
  (ver el número más alto en ese archivo para saber en qué versión está el esquema).

## Módulos principales
Clientes · Expedientes (+ tareas, sesiones, control de horas) · Pipeline comercial ·
Flujo de caja (ingresos/gastos/costos, con IVA, reembolsable y fondos de terceros) ·
Facturas · Catálogo maestro (categorías/servicios/familias) · Finanzas (plan de cuentas,
personal, gastos fijos, presupuesto) · Comisiones (multi-originador, por tramos) ·
Gobierno del catálogo (flujo de aprobación de cambios) · Nómina (motor de cálculo:
ISSS, AFP, renta, horas extra, nocturnidad, prestaciones de ley) · Dashboard · Usuarios
y roles · Integraciones (Google Calendar, Outlook, Resend).

## Cómo correr en local
1. Postgres corriendo en local con una base `aglegal` (ver `.env` para las credenciales
   de desarrollo — `DATABASE_URL`).
2. Entorno virtual + dependencias:
   ```bash
   python -m venv .venv && .venv/Scripts/activate  # o source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Arrancar la API (las migraciones corren solas al primer request):
   ```bash
   python -m uvicorn api.app.main:app --reload --port 8000
   ```
4. El frontend (repo aparte) apunta a `http://localhost:8000` vía proxy de Vite en `/api`.

## Tests
```bash
pip install -r requirements-dev.txt
pytest
```
Corren contra un schema de Postgres desechable (`aglegal_test`), aislado de `public` —
ver `conftest.py`.

## Despliegue
Manual por SSH, sin CI/CD. El procedimiento completo (con credenciales y comandos
exactos) vive en `DEPLOY.md` y `CREDENTIALS.md` — ambos en `.gitignore`, nunca se suben
al repositorio.
