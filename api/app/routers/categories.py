from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep
from ..schemas.category import (
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    ServiceProductIn,
    ServiceProductOut,
    ServiceProductUpdate,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(current_user: CurrentUser, repo: RepoDep, kind: str = "income") -> list[CategoryOut]:
    return [CategoryOut.from_row(row) for row in repo.list_categories(kind=kind)]


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, current_user: CurrentUser, repo: RepoDep) -> CategoryOut:
    cat_id = repo.create_category(kind=body.kind, name=body.name, created_at=now_iso())
    row = repo.conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    return CategoryOut.from_row(row)


@router.put("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, body: CategoryUpdate, current_user: CurrentUser, repo: RepoDep) -> CategoryOut:
    repo.update_category(category_id, name=body.name)
    row = repo.conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    return CategoryOut.from_row(row)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_category(category_id)


# --- Service Products ---

@router.get("/service-products", response_model=list[ServiceProductOut])
def list_service_products(
    current_user: CurrentUser,
    repo: RepoDep,
    category_id: int | None = None,
    active_only: bool = False,
) -> list[ServiceProductOut]:
    return [ServiceProductOut.from_row(row) for row in repo.list_service_products(category_id=category_id, active_only=active_only)]


@router.get("/service-products/choices")
def service_product_choices(
    current_user: CurrentUser,
    repo: RepoDep,
    category_id: int | None = None,
) -> list[dict]:
    return [{"id": pid, "name": name} for pid, name in repo.service_product_choices(category_id=category_id)]


@router.post("/service-products", response_model=ServiceProductOut, status_code=201)
def create_service_product(body: ServiceProductIn, current_user: CurrentUser, repo: RepoDep) -> ServiceProductOut:
    price_text = str(body.base_price) if body.base_price is not None else ""
    pid = repo.create_service_product(
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        base_price_text=price_text,
        active=body.active,
        created_at=now_iso(),
    )
    rows = repo.list_service_products()
    row = next((r for r in rows if r["id"] == pid), None)
    return ServiceProductOut.from_row(row)


@router.put("/service-products/{product_id}", response_model=ServiceProductOut)
def update_service_product(
    product_id: int,
    body: ServiceProductUpdate,
    current_user: CurrentUser,
    repo: RepoDep,
) -> ServiceProductOut:
    price_text = str(body.base_price) if body.base_price is not None else ""
    repo.update_service_product(
        product_id,
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        base_price_text=price_text,
        active=body.active,
    )
    rows = repo.list_service_products()
    row = next((r for r in rows if r["id"] == product_id), None)
    return ServiceProductOut.from_row(row)


@router.delete("/service-products/{product_id}", status_code=204)
def delete_service_product(product_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_service_product(product_id)
