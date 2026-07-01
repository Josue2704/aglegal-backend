# PROYECTOAGLEGAL (Demo)

Prototipo de escritorio (uso interno) para mostrar a clientes cómo se vería el sistema.

## Stack
- Python + PySide6 (Qt)
- SQLite (archivo local)

## Cómo correr
1) (Opcional) Crear entorno:
- `python -m venv .venv`
- `./.venv/Scripts/Activate.ps1`

2) Instalar dependencias:
- `pip install -r requirements.txt`

3) Ejecutar:
- `python main.py`

## Login (demo)
- Usuario: `admin`
- Contraseña: `admin`

Al primer arranque se crea `data/aglegal.db` y se siembra ese usuario.

## Demo incluida
- Clientes: CRUD + búsqueda
- Sesiones: CRUD + adjuntar documentos
- Gastos vs Ingresos: registrar ambos, ver balance y adjuntar facturas

## Nota de evolución
El acceso a datos está aislado en `aglegal/` (repositorios + DB). Esto deja el camino abierto para:
- Migrar a Postgres en el futuro
- Montar una API (p.ej. FastAPI) reutilizando repositorios/servicios

