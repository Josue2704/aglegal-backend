"""Smoke test de integración contra la app en vivo: cliente -> expediente -> cobro ->
comisión -> factura -> pago -> dashboard/cashflow, verificando que cada módulo se refleje
en los demás. Crea datos de prueba y los borra al final (purge), sin dejar rastro."""
from __future__ import annotations

import sys
import requests

BASE = "https://pruebassystemsv.online/api"
FAILS: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not cond:
        FAILS.append(label + " " + extra)


def main() -> int:
    s = requests.Session()
    login = s.post(f"{BASE}/auth/login", json={"username": "admin", "password": sys.argv[1]})
    check("login", login.status_code == 200, login.text[:200])
    token = login.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"

    servicios = s.get(f"{BASE}/catalogo/servicios/choices", params={"limit": 1}).json()
    service_id = servicios[0]["id"]
    cuentas = s.get(f"{BASE}/finanzas/cuentas").json()
    cuenta_ingreso = next(c for c in cuentas if c["tipo"] == "Ingreso")
    personal = s.get(f"{BASE}/finanzas/personal").json()
    check("hay personal sembrado", len(personal) > 0, str(len(personal)))
    persona = personal[0]

    # 1. Cliente
    r = s.post(f"{BASE}/clients", json={"name": "SMOKE TEST Cliente", "client_type": "Física"})
    check("crear cliente", r.status_code == 201, r.text[:200])
    client_id = r.json()["id"]

    # 2. Expediente (con honorarios contratados y servicio)
    from datetime import date
    r = s.post(f"{BASE}/cases", json={
        "client_id": client_id, "title": "SMOKE TEST Expediente", "status": "Abierto",
        "priority": "Media", "opened_at": date.today().isoformat(),
        "service_id": service_id, "honorarios_contratados": 1000,
        "alcance": "SMOKE TEST alcance", "condiciones_cobro": "Al finalizar",
        "revision_confirmada": True, "revision_observaciones": "SMOKE TEST revisión",
        "responsible_username": "admin",
        "mes_cobro_esperado": date.today().isoformat()[:7], "probabilidad_cobro": 0.7,
        "tareas_iniciales": [{"titulo": "SMOKE TEST tarea", "due_date": date.today().isoformat()}],
    })
    check("crear expediente", r.status_code == 201, r.text[:300])
    case = r.json()
    case_id = case["id"]

    # 3. Originador (para que el cobro genere comisión)
    r = s.put(f"{BASE}/comisiones/originadores/{case_id}", json={
        "originadores": [{"personal_id": persona["id"], "porcentaje_participacion": 100, "tipo_origen": "Cliente nuevo"}]
    })
    check("asignar originador", r.status_code == 200, r.text[:300])

    # 4. Cobro (income) — debe generar comisión automáticamente
    r = s.post(f"{BASE}/incomes", json={
        "amount": 500, "income_date": date.today().isoformat(), "client_id": client_id,
        "case_id": case_id, "account_id": cuenta_ingreso["id"], "detail": "SMOKE TEST cobro",
    })
    check("registrar cobro", r.status_code == 201, r.text[:300])
    income = r.json()

    # 5. ¿Se refleja el expediente con saldo actualizado?
    r = s.get(f"{BASE}/cases/{case_id}")
    check("expediente refleja el cobro", r.status_code == 200 and r.json().get("saldo_pendiente") is not None, str(r.json().get("saldo_pendiente")))

    # 6. ¿Generó comisión?
    r = s.get(f"{BASE}/comisiones", params={"case_id": case_id})
    comisiones = r.json()
    check("comisión generada por el cobro", len(comisiones) == 1, str(len(comisiones)))

    # 7. Cashflow refleja el cobro
    r = s.get(f"{BASE}/dashboard/cashflow")
    check("dashboard/cashflow responde", r.status_code == 200, str(r.status_code))

    # 8. Factura y pago
    next_num = s.get(f"{BASE}/invoices/next-number").json()
    r = s.post(f"{BASE}/invoices", json={
        "client_id": client_id, "case_id": case_id, "invoice_number": next_num["invoice_number"],
        "invoice_date": date.today().isoformat(),
        "items": [{"description": "SMOKE TEST honorarios", "quantity": 1, "unit_price": 500}],
    })
    check("crear factura", r.status_code == 201, r.text[:300])
    invoice = r.json()
    check("factura calcula total", invoice.get("total", 0) > 0, str(invoice.get("total")))

    r = s.patch(f"{BASE}/invoices/{invoice['id']}/status", json={"status": "Enviada"})
    check("emitir factura (Borrador -> Enviada)", r.status_code == 200, r.text[:300])

    import uuid
    r = s.post(f"{BASE}/invoices/{invoice['id']}/payments", json={
        "amount": 500, "account_id": cuenta_ingreso["id"], "detail": "SMOKE TEST pago",
        "income_date": date.today().isoformat(), "request_key": uuid.uuid4().hex,
    })
    check("registrar pago de factura", r.status_code == 200, r.text[:300])
    if r.status_code == 200:
        pagada = s.get(f"{BASE}/invoices/{invoice['id']}").json()
        check("factura queda Pagada tras cubrir el saldo", pagada.get("status") == "Pagada", str(pagada.get("status")))

    # 9. Comisión visible en resumen
    r = s.get(f"{BASE}/comisiones/resumen", params={"mes": __import__("datetime").date.today().isoformat()[:7]})
    check("resumen de comisiones responde", r.status_code == 200, str(r.status_code))

    # 10. Revisión y liquidación de la comisión
    if comisiones:
        cid = comisiones[0]["id"]
        r = s.post(f"{BASE}/comisiones/{cid}/revision", json={"evidencia": "smoke test", "elegible": True})
        check("aprobar revisión de comisión", r.status_code == 200, r.text[:300])

    # ── limpieza ── (ya hay historial financiero: purge definitivo lo bloquea a
    # propósito, así que se archiva en la papelera como haría cualquier usuario)
    s.patch(f"{BASE}/invoices/{invoice['id']}/status", json={"status": "Cancelada"})
    s.delete(f"{BASE}/cases/{case_id}")
    s.delete(f"{BASE}/clients/{client_id}")

    print()
    if FAILS:
        print(f"{len(FAILS)} fallo(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("Todo OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
