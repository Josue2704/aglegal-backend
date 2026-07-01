from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .auth.router import router as auth_router
from .routers import (
    attachments,
    cases,
    categories,
    clients,
    costs,
    dashboard,
    expenses,
    google_cal,
    incomes,
    payroll,
    sessions,
    users,
)

settings = get_settings()

app = FastAPI(
    title="AGLegal API",
    version="1.0.0",
    description="API REST para gestión de bufete de abogados",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.include_router(auth_router)
app.include_router(clients.router)
app.include_router(cases.router)
app.include_router(sessions.router)
app.include_router(incomes.router)
app.include_router(expenses.router)
app.include_router(costs.router)
app.include_router(categories.router)
app.include_router(payroll.router)
app.include_router(users.router)
app.include_router(dashboard.router)
app.include_router(attachments.router)
app.include_router(google_cal.router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
