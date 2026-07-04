from __future__ import annotations

import logging
from datetime import datetime
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


def _build_html(
    *,
    client_name: str,
    session_date: str,
    start_time: str | None,
    end_time: str | None,
    consult_type: str,
    notes: str | None,
    firm_name: str,
    is_update: bool,
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
    if notes and notes.strip():
        notes_row = f"""
        <tr>
          <td style="padding:10px 16px;color:#8fa3b8;font-size:13px;vertical-align:top;white-space:nowrap;width:1%">Notas</td>
          <td style="padding:10px 16px;color:#e8edf2;font-size:14px;line-height:1.6">{notes.strip()}</td>
        </tr>"""

    action_verb = "reprogramada" if is_update else "confirmada"
    subject_verb = "ha sido actualizada" if is_update else "ha sido agendada"
    badge_color = "#b07d2e" if is_update else "#1a6b3c"
    badge_text = "Cita actualizada" if is_update else "Cita confirmada"

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
        <div style="display:inline-block;background:#c9a84c;border-radius:4px;padding:4px 12px;margin-bottom:18px">
          <span style="color:#0d1117;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase">{badge_text}</span>
        </div>
        <h1 style="margin:0;color:#e8edf2;font-size:26px;font-weight:300;letter-spacing:-0.5px">{firm_name}</h1>
        <p style="margin:8px 0 0;color:#8fa3b8;font-size:13px;letter-spacing:0.5px">Servicios Legales</p>
      </td></tr>

      <!-- BODY -->
      <tr><td style="background:#111827;padding:36px 40px">
        <p style="margin:0 0 8px;color:#8fa3b8;font-size:13px;text-transform:uppercase;letter-spacing:1px">Estimado/a</p>
        <h2 style="margin:0 0 24px;color:#e8edf2;font-size:22px;font-weight:400">{client_name}</h2>
        <p style="margin:0 0 28px;color:#a8b8cc;font-size:15px;line-height:1.7">
          Su cita {subject_verb} exitosamente. A continuación encontrará los detalles:
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

        <p style="margin:0;color:#6b7f94;font-size:13px;line-height:1.6">
          Si necesita cancelar o reprogramar su cita, comuníquese con nosotros a la brevedad posible.
        </p>
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
    try:
        import resend as resend_lib
        resend_lib.api_key = resend_api_key

        subject_prefix = "Cita actualizada" if is_update else "Confirmación de cita"
        subject = f"{subject_prefix} — {firm_name}"

        html = _build_html(
            client_name=client_name,
            session_date=str(session_row["session_date"]),
            start_time=session_row.get("start_time"),
            end_time=session_row.get("end_time"),
            consult_type=str(session_row["consult_type"]),
            notes=session_row.get("notes"),
            firm_name=firm_name,
            is_update=is_update,
        )

        params: resend_lib.Emails.SendParams = {
            "from": resend_from,
            "to": [client_email],
            "subject": subject,
            "html": html,
        }
        resend_lib.Emails.send(params)
        log.info("Email enviado a %s (session %s)", client_email, session_row["id"])
    except Exception as e:
        log.warning("Error enviando email de sesión: %s", e)
