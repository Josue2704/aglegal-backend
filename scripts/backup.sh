#!/usr/bin/env bash
# Respaldo diario de la base de datos y los documentos subidos (adjuntos).
# Corre vía systemd timer (aglegal-backup.timer) en el servidor de producción.
#
# No hay ningún backup automático hasta esta ronda (AUDITORIA_USO_ABOGADO.md, punto 1):
# un fallo de disco o un borrado accidental perdía todo sin posibilidad de recuperación.
# Esto es la mitigación local — guarda N días de respaldos rotativos en el mismo servidor.
# Sigue siendo un solo punto de falla si el servidor completo se pierde (disco, VPS
# borrado, etc.) — para eso hace falta apuntar BACKUP_REMOTE_DIR a un destino externo
# (otro servidor vía rsync, un bucket S3/rclone, etc.), algo que requiere credenciales
# que esta sesión no tiene. Este script deja el respaldo listo en un directorio único
# y predecible para que ese paso final sea agregar una línea, no rediseñar nada.
set -euo pipefail

APP_DIR="/opt/aglegal"
BACKUP_DIR="${APP_DIR}/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "${BACKUP_DIR}/db" "${BACKUP_DIR}/attachments"

# --- Base de datos ---
# No se hace `source .env` completo: ese archivo lo escribe/lee python-dotenv, que
# tolera valores sin comillas (ej. FIRM_NAME=AG Legal) que bash no puede parsear como
# script y revientan con "syntax error". Se extrae solo la línea que hace falta.
DATABASE_URL="$(grep -m1 '^DATABASE_URL=' "${APP_DIR}/.env" | cut -d= -f2-)"
if [ -z "${DATABASE_URL}" ]; then
  echo "DATABASE_URL no encontrada en ${APP_DIR}/.env" >&2
  exit 1
fi

pg_dump "${DATABASE_URL}" | gzip > "${BACKUP_DIR}/db/aglegal_${STAMP}.sql.gz"

# --- Documentos adjuntos (identificaciones, contratos, evidencia) ---
if [ -d "${APP_DIR}/data/attachments" ]; then
  tar czf "${BACKUP_DIR}/attachments/attachments_${STAMP}.tar.gz" -C "${APP_DIR}/data" attachments
fi

# --- Rotación: conserva solo los últimos N días ---
find "${BACKUP_DIR}/db" -name '*.sql.gz' -mtime +"${RETENTION_DAYS}" -delete
find "${BACKUP_DIR}/attachments" -name '*.tar.gz' -mtime +"${RETENTION_DAYS}" -delete

echo "Backup completado: ${STAMP}"

# Opcional: si BACKUP_REMOTE_DIR está definida (ej. un mount de rclone a almacenamiento
# externo), copiar ahí también. Sin esto configurado, el respaldo se queda local.
if [ -n "${BACKUP_REMOTE_DIR:-}" ]; then
  mkdir -p "${BACKUP_REMOTE_DIR}/db" "${BACKUP_REMOTE_DIR}/attachments"
  cp "${BACKUP_DIR}/db/aglegal_${STAMP}.sql.gz" "${BACKUP_REMOTE_DIR}/db/"
  [ -f "${BACKUP_DIR}/attachments/attachments_${STAMP}.tar.gz" ] && \
    cp "${BACKUP_DIR}/attachments/attachments_${STAMP}.tar.gz" "${BACKUP_REMOTE_DIR}/attachments/"
  echo "Copiado también a destino externo: ${BACKUP_REMOTE_DIR}"
fi
