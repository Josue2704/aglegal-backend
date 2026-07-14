from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Header, HTTPException

from ..config import get_settings
from ..deps import RepoDep
from ..services.email import send_reminder_email

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
             AND s.status NOT IN ('Finalizada')
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
             AND s.status NOT IN ('Finalizada')
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

    log.info("Reminders: %d sent, %d skipped", sent, skipped)
    return {"sent": sent, "skipped": skipped, "date": today_str}
