from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Header, HTTPException

from ..config import get_settings
from ..deps import RepoDep
from ..services.email import send_reminder_email, send_task_digest_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/send-reminders")
def send_reminders(
    repo: RepoDep,
    x_cron_key: str = Header(default=""),
) -> dict:
    """
    Called daily by a systemd timer.
    Sends reminder emails for sessions happening tomorrow (24h) and today in 2h window.
    Protected by X-Cron-Key header.
    """
    s = get_settings()
    if not s.cron_key or x_cron_key != s.cron_key:
        raise HTTPException(403, "Forbidden")
    if not s.resend_api_key:
        return {"sent": 0, "skipped": 0, "reason": "no resend key"}

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    today_str = date.today().isoformat()

    # Sessions tomorrow (24h reminder)
    rows_tomorrow = repo.conn.execute(
        """SELECT s.id, s.session_date, s.start_time, s.end_time,
                  s.consult_type, s.notes,
                  cl.name AS client_name, cl.email AS client_email
           FROM sessions s
           LEFT JOIN clients cl ON cl.id = s.client_id
           WHERE s.session_date = %s
             AND s.status NOT IN ('Finalizada','Cancelada')
             AND cl.email IS NOT NULL AND cl.email != ''""",
        (tomorrow,),
    ).fetchall()

    # Sessions today not yet started (2h reminder — only if start_time is set)
    from datetime import datetime
    now_time = datetime.now().strftime("%H:%M")
    two_h_later = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")

    rows_today = repo.conn.execute(
        """SELECT s.id, s.session_date, s.start_time, s.end_time,
                  s.consult_type, s.notes,
                  cl.name AS client_name, cl.email AS client_email
           FROM sessions s
           LEFT JOIN clients cl ON cl.id = s.client_id
           WHERE s.session_date = %s
             AND s.start_time >= %s AND s.start_time <= %s
             AND s.status NOT IN ('Finalizada','Cancelada')
             AND cl.email IS NOT NULL AND cl.email != ''""",
        (today_str, now_time, two_h_later),
    ).fetchall()

    sent = 0
    skipped = 0

    for row in rows_tomorrow:
        try:
            send_reminder_email(
                session_row=dict(row),
                client_email=str(row["client_email"]),
                client_name=str(row["client_name"]),
                firm_name=s.firm_name,
                resend_api_key=s.resend_api_key,
                resend_from=s.resend_from_email,
                hours_ahead=24,
            )
            sent += 1
        except Exception as e:
            log.warning("Reminder 24h failed session %s: %s", row["id"], e)
            skipped += 1

    for row in rows_today:
        try:
            send_reminder_email(
                session_row=dict(row),
                client_email=str(row["client_email"]),
                client_name=str(row["client_name"]),
                firm_name=s.firm_name,
                resend_api_key=s.resend_api_key,
                resend_from=s.resend_from_email,
                hours_ahead=2,
            )
            sent += 1
        except Exception as e:
            log.warning("Reminder 2h failed session %s: %s", row["id"], e)
            skipped += 1

    # Tareas vencidas o con plazo crítico próximo a vencer, agrupadas por abogado
    # responsable — un correo diario por persona en vez de uno por tarea. Antes solo
    # las sesiones con cliente disparaban un recordatorio; los plazos internos (y los
    # críticos, ver es_critico) no empujaban nada hacia afuera del dashboard.
    tasks_sent = 0
    if s.resend_api_key:
        alerts = repo.dashboard_alerts(stale_days=999999)  # solo nos interesan overdue/critical, no stale_cases
        pending_by_user: dict[str, list[dict]] = {}
        seen_ids: set[int] = set()
        for bucket in (alerts["overdue_tasks"], alerts["critical_tasks"]):
            for t in bucket:
                if t["id"] in seen_ids:
                    continue
                seen_ids.add(t["id"])
                full_row = repo.conn.execute(
                    "SELECT responsible_username, es_critico FROM case_tasks WHERE id=%s", (t["id"],)
                ).fetchone()
                username = full_row["responsible_username"] if full_row else None
                if not username:
                    continue
                pending_by_user.setdefault(username, []).append({**t, "es_critico": bool(full_row["es_critico"])})

        for username, tasks in pending_by_user.items():
            user_row = repo.conn.execute(
                "SELECT full_name, email FROM users WHERE username=%s AND active=1", (username,)
            ).fetchone()
            if not user_row or not user_row["email"]:
                continue
            try:
                send_task_digest_email(
                    user_name=user_row["full_name"] or username,
                    user_email=user_row["email"],
                    firm_name=s.firm_name,
                    tasks=tasks,
                    resend_api_key=s.resend_api_key,
                    resend_from=s.resend_from_email,
                )
                tasks_sent += 1
            except Exception as e:
                log.warning("Digest de tareas falló para %s: %s", username, e)

    log.info("Reminders: %d sent, %d skipped, %d task digests", sent, skipped, tasks_sent)
    return {"sent": sent, "skipped": skipped, "task_digests": tasks_sent, "date": today_str}
