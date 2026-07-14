from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, date as date_type
from typing import Any

log = logging.getLogger(__name__)

_MONTHS = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}
_DAYS = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo",
}


def _fmt_date(date_str: str) -> str:
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return f"{_DAYS[d.weekday()].capitalize()}, {d.day} de {_MONTHS[d.month]} de {d.year}"


def _fmt_time(t: str | None) -> str:
    if not t:
        return ""
    h, m = int(t[:2]), int(t[3:5])
    period = "a.m." if h < 12 else "p.m."
    return f"{h % 12 or 12}:{m:02d} {period}"


def _extract_email(from_str: str) -> str:
    """Extract plain email from 'Name <email>' or 'email'."""
    m = re.search(r"<([^>]+)>", from_str)
    return m.group(1).strip() if m else from_str.strip()


# ─── ICS builder ─────────────────────────────────────────────────────────────

def _ics_escape(s: str) -> str:
    """Escape special characters for ICS text fields."""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _build_ics(
    *,
    session_id: int,
    session_date: str,
    start_time: str | None,
    end_time: str | None,
    consult_type: str,
    notes: str | None,
    organizer_email: str,
    organizer_name: str,
    attendee_email: str,
    attendee_name: str,
    method: str = "REQUEST",   # REQUEST | CANCEL
    sequence: int = 0,
) -> bytes:
    d = date_type.fromisoformat(session_date[:10])

    if start_time:
        h, m = int(start_time[:2]), int(start_time[3:5])
        dt_start = f"{d.year:04d}{d.month:02d}{d.day:02d}T{h:02d}{m:02d}00"
        if end_time:
            eh, em = int(end_time[:2]), int(end_time[3:5])
            dt_end = f"{d.year:04d}{d.month:02d}{d.day:02d}T{eh:02d}{em:02d}00"
        else:
            # Default 1 hour if no end time
            dt_end = f"{d.year:04d}{d.month:02d}{d.day:02d}T{(h+1):02d}{m:02d}00"
        dt_start_line = f"DTSTART:{dt_start}"
        dt_end_line = f"DTEND:{dt_end}"
    else:
        # All-day event
        dt_start_line = f"DTSTART;VALUE=DATE:{d.year:04d}{d.month:02d}{d.day:02d}"
        dt_end_line = f"DTEND;VALUE=DATE:{d.year:04d}{d.month:02d}{d.day:02d}"

    status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"
    summary = _ics_escape(f"{consult_type} — {organizer_name}")
    desc = _ics_escape((notes or "").strip()) if notes else ""
    uid = f"aglegal-session-{session_id}@aglegal"

    now_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AGLegal//Agenda//ES",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now_stamp}",
        dt_start_line,
        dt_end_line,
        f"SUMMARY:{summary}",
        f"ORGANIZER;CN={_ics_escape(organizer_name)}:mailto:{organizer_email}",
        f"ATTENDEE;RSVP=TRUE;CN={_ics_escape(attendee_name)};PARTSTAT=NEEDS-ACTION;ROLE=REQ-PARTICIPANT:mailto:{attendee_email}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{status}",
    ]
    if desc:
        lines.append(f"DESCRIPTION:{desc}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    return "\r\n".join(lines).encode("utf-8")


# ─── HTML builder ─────────────────────────────────────────────────────────────

def _build_html(
    *,
    client_name: str,
    session_date: str,
    start_time: str | None,
    end_time: str | None,
    consult_type: str,
    notes: str | None,
    firm_name: str,
    mode: str,  # "new" | "update" | "cancel"
) -> str:
    date_fmt = _fmt_date(session_date)
    time_start = _fmt_time(start_time)
    time_end = _fmt_time(end_time)

    time_row = ""
    if time_start:
        time_label = f"{time_start} — {time_end}" if time_end else time_start
        time_row = f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#8fa3b8;font-size:13px;white-space:nowrap;width:1%">Hora</td>
          <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#e8edf2;font-size:14px">{time_label}</td>
        </tr>"""

    notes_row = ""
    if notes and notes.strip() and mode != "cancel":
        notes_row = f"""
        <tr>
          <td style="padding:10px 16px;color:#8fa3b8;font-size:13px;vertical-align:top;white-space:nowrap;width:1%">Notas</td>
          <td style="padding:10px 16px;color:#e8edf2;font-size:14px;line-height:1.6">{notes.strip()}</td>
        </tr>"""

    if mode == "cancel":
        badge_color = "#7f1d1d"
        badge_text = "Cita cancelada"
        subject_verb = "ha sido cancelada"
        footer_note = "Si desea reagendar, comuníquese con nosotros."
        badge_bg = "#ef4444"
    elif mode == "update":
        badge_color = "#b07d2e"
        badge_text = "Cita actualizada"
        subject_verb = "ha sido reprogramada"
        footer_note = "Si necesita cancelar o reprogramar, comuníquese con nosotros."
        badge_bg = "#f59e0b"
    else:
        badge_color = "#1a6b3c"
        badge_text = "Cita confirmada"
        subject_verb = "ha sido agendada exitosamente"
        footer_note = "Si necesita cancelar o reprogramar, comuníquese con nosotros."
        badge_bg = "#22c55e"

    cancel_banner = ""
    if mode == "cancel":
        cancel_banner = f"""
        <tr><td style="background:#7f1d1d;padding:14px 40px;text-align:center">
          <p style="margin:0;color:#fca5a5;font-size:14px;font-weight:600">⚠ Esta cita ha sido cancelada</p>
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{badge_text}</title>
</head>
<body style="margin:0;padding:0;background-color:#0d1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;padding:32px 16px">
  <tr><td align="center">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">

      <!-- HEADER -->
      <tr><td style="background:linear-gradient(135deg,#0f1f35 0%,#162840 100%);border-radius:12px 12px 0 0;padding:36px 40px 32px;text-align:center;border-bottom:2px solid #c9a84c">
        <div style="display:inline-block;background:{badge_bg};border-radius:4px;padding:4px 12px;margin-bottom:18px">
          <span style="color:#fff;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase">{badge_text}</span>
        </div>
        <h1 style="margin:0;color:#e8edf2;font-size:26px;font-weight:300;letter-spacing:-0.5px">{firm_name}</h1>
        <p style="margin:8px 0 0;color:#8fa3b8;font-size:13px;letter-spacing:0.5px">Servicios Legales</p>
      </td></tr>

      {cancel_banner}

      <!-- BODY -->
      <tr><td style="background:#111827;padding:36px 40px">
        <p style="margin:0 0 8px;color:#8fa3b8;font-size:13px;text-transform:uppercase;letter-spacing:1px">Estimado/a</p>
        <h2 style="margin:0 0 24px;color:#e8edf2;font-size:22px;font-weight:400">{client_name}</h2>
        <p style="margin:0 0 28px;color:#a8b8cc;font-size:15px;line-height:1.7">
          Su cita {subject_verb}. A continuación los detalles:
        </p>

        <!-- DETAILS CARD -->
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border-radius:10px;overflow:hidden;border:1px solid #1e2a3a;margin-bottom:32px">
          <tr>
            <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#8fa3b8;font-size:13px;white-space:nowrap;width:1%">Tipo</td>
            <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#c9a84c;font-size:14px;font-weight:600">{consult_type}</td>
          </tr>
          <tr>
            <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#8fa3b8;font-size:13px;white-space:nowrap;width:1%">Fecha</td>
            <td style="padding:10px 16px;border-bottom:1px solid #1e2a3a;color:#e8edf2;font-size:14px">{date_fmt}</td>
          </tr>{time_row}{notes_row}
        </table>

        <p style="margin:0;color:#6b7f94;font-size:13px;line-height:1.6">{footer_note}</p>
      </td></tr>

      <!-- FOOTER -->
      <tr><td style="background:#0a0f1a;border-radius:0 0 12px 12px;padding:24px 40px;text-align:center;border-top:1px solid #1e2a3a">
        <p style="margin:0 0 6px;color:#c9a84c;font-size:13px;font-weight:600;letter-spacing:0.5px">{firm_name}</p>
        <p style="margin:0;color:#4a5a6a;font-size:12px">Este mensaje fue generado automáticamente · Por favor no responda este correo</p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


# ─── Public API ───────────────────────────────────────────────────────────────

def send_session_email(
    *,
    session_row: Any,
    client_email: str,
    client_name: str,
    firm_name: str,
    resend_api_key: str,
    resend_from: str,
    is_update: bool = False,
) -> None:
    """Send session confirmation or update email with ICS calendar invite."""
    try:
        import resend as resend_lib
        resend_lib.api_key = resend_api_key

        mode = "update" if is_update else "new"
        sequence = 1 if is_update else 0

        organizer_email = _extract_email(resend_from)

        html = _build_html(
            client_name=client_name,
            session_date=str(session_row["session_date"]),
            start_time=session_row.get("start_time"),
            end_time=session_row.get("end_time"),
            consult_type=str(session_row["consult_type"]),
            notes=session_row.get("notes"),
            firm_name=firm_name,
            mode=mode,
        )

        ics = _build_ics(
            session_id=int(session_row["id"]),
            session_date=str(session_row["session_date"]),
            start_time=session_row.get("start_time"),
            end_time=session_row.get("end_time"),
            consult_type=str(session_row["consult_type"]),
            notes=session_row.get("notes"),
            organizer_email=organizer_email,
            organizer_name=firm_name,
            attendee_email=client_email,
            attendee_name=client_name,
            method="REQUEST",
            sequence=sequence,
        )

        subject_prefix = "Cita actualizada" if is_update else "Confirmación de cita"

        params: resend_lib.Emails.SendParams = {
            "from": resend_from,
            "to": [client_email],
            "subject": f"{subject_prefix} — {firm_name}",
            "html": html,
            "attachments": [
                {
                    "filename": "cita.ics",
                    "content": list(ics),  # Resend expects list[int] or base64 str
                }
            ],
        }
        resend_lib.Emails.send(params)
        log.info("Email+ICS enviado a %s (session %s, mode=%s)", client_email, session_row["id"], mode)
    except Exception as e:
        log.warning("Error enviando email de sesión: %s", e)


def send_session_cancel_email(
    *,
    session_row: Any,
    client_email: str,
    client_name: str,
    firm_name: str,
    resend_api_key: str,
    resend_from: str,
) -> None:
    """Send cancellation email with ICS METHOD:CANCEL so the event is removed from client's calendar."""
    try:
        import resend as resend_lib
        resend_lib.api_key = resend_api_key

        organizer_email = _extract_email(resend_from)

        html = _build_html(
            client_name=client_name,
            session_date=str(session_row["session_date"]),
            start_time=session_row.get("start_time"),
            end_time=session_row.get("end_time"),
            consult_type=str(session_row["consult_type"]),
            notes=session_row.get("notes"),
            firm_name=firm_name,
            mode="cancel",
        )

        ics = _build_ics(
            session_id=int(session_row["id"]),
            session_date=str(session_row["session_date"]),
            start_time=session_row.get("start_time"),
            end_time=session_row.get("end_time"),
            consult_type=str(session_row["consult_type"]),
            notes=None,
            organizer_email=organizer_email,
            organizer_name=firm_name,
            attendee_email=client_email,
            attendee_name=client_name,
            method="CANCEL",
            sequence=99,  # Higher than any previous sequence → forces removal
        )

        params: resend_lib.Emails.SendParams = {
            "from": resend_from,
            "to": [client_email],
            "subject": f"Cita cancelada — {firm_name}",
            "html": html,
            "attachments": [
                {
                    "filename": "cancelacion.ics",
                    "content": list(ics),
                }
            ],
        }
        resend_lib.Emails.send(params)
        log.info("Email CANCEL enviado a %s (session %s)", client_email, session_row["id"])
    except Exception as e:
        log.warning("Error enviando email cancelación: %s", e)
