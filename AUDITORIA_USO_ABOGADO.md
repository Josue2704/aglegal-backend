# Auditoría de uso — el sistema visto como un abogado de bufete

**Fecha del hallazgo:** 2026-08-08 · **Fecha de la corrección:** 2026-08-09
**Método:** lectura completa de las 18 páginas del frontend y sus routers/repositorio correspondientes en el backend (no es una prueba de clic en navegador — es una revisión de código puesta en el zapato de quien usaría esto todos los días: un abogado o el equipo administrativo de un despacho pequeño/mediano).
**Objetivo:** el sistema ya cubre con solidez la parte comercial, financiera y de catálogo (eso está auditado aparte en `PLAN_CATALOGO_FINANCIERO.md`). Esta revisión busca específicamente los vacíos que solo se notan cuando alguien intenta *vivir* en el sistema como abogado litigante o notario — no como administrador financiero.

**Estado:** los 10 puntos de prioridad alta y media (🔴🟡) están **corregidos, desplegados y verificados en producción** — ver el detalle de cada uno abajo, con commits y prueba de que funciona. Los 6 puntos de prioridad baja (🟢) quedaron **deliberadamente fuera de esta ronda** — son iniciativas propias, no un ajuste, y están explicadas al final con la razón concreta de por qué no se intentaron a la carrera.

---

## Lo que ya estaba fuerte (para no repetir en cada punto de abajo)

Adjuntos con roles (guía/evidencia) por tarea, sesiones y expediente; agenda con mes/semana/día/lista, arrastrar-para-reagendar, detección de choques de horario, sincronización con Google y Outlook Calendar; recordatorios automáticos por correo (24h y 2h antes) vía Resend; facturación con partidas armadas desde sesiones/tareas/costos no facturados, impresión a PDF; búsqueda global (Ctrl+K); multi-divisa (13 monedas); tema claro/oscuro; RBAC granular por módulo.

---

## ✅ Corregido — antes 🔴 alta prioridad

### 1. No había respaldo (backup) automático de nada
**Antes:** ni la base de datos ni `data/attachments/` tenían ningún backup — un fallo de disco o un borrado accidental perdía todo sin posibilidad de recuperación.

**Ahora:** `scripts/backup.sh` corre diario a las 3am vía `aglegal-backup.timer` (systemd) — `pg_dump` comprimido de la base + `tar` de adjuntos, con rotación de 14 días. Verificado corriendo manualmente: produjo un dump real (22 KB) y un tar de adjuntos (4.8 MB) en `/opt/aglegal/backups/`.

**Límite honesto que sigue ahí:** es un backup *local*, en el mismo servidor. Protege contra "until borré un registro por error" o "until se corrompió un archivo", pero no contra perder el VPS completo. Para eso, `scripts/backup.sh` ya soporta una variable `BACKUP_REMOTE_DIR` (por ejemplo un mount de rclone a almacenamiento externo) — falta que tú decidas a qué proveedor de backup externo apuntarlo, porque eso requiere una cuenta/credenciales que esta sesión no tiene.

### 2. Borrar un cliente o un expediente era permanente, sin papelera
**Ahora:** el ícono de basura en Clientes y Expedientes ya no borra — archiva (`DELETE /clients/{id}` y `DELETE /cases/{id}` ahora ponen `archived_at`, no ejecutan `DELETE FROM`). Un botón nuevo "Papelera" en ambas pantallas muestra los archivados con "Restaurar" o, solo para administrador, "Borrar permanentemente". Verificado end-to-end: archivar → desaparece de la lista activa → aparece en papelera → restaurar → vuelve a aparecer.

### 3. No había verificación de conflicto de interés
**Ahora:** al escribir el nombre de la "Contraparte" en un expediente nuevo o editado, el sistema cruza en vivo contra `clients.name` y contra `cases.opposing_party` de otros expedientes activos (`GET /cases/conflicto-interes`), y muestra un aviso rojo no bloqueante si hay coincidencia. Verificado: crear un expediente con la contraparte igual al nombre de un cliente real disparó el aviso correctamente.

### 4. Los plazos legales no se distinguían de un pendiente cualquiera
**Ahora:** las tareas tienen un campo `es_critico` (checkbox "Plazo legal crítico" al crear, badge rojo en la lista, toggle en el detalle). El Dashboard tiene una franja roja **separada** de las alertas normales — "N plazos legales críticos — vencidos o por vencer en 3 días" — que no se mezcla con "expediente sin movimiento" ni con tareas comunes. Verificado: una tarea crítica aparece en `dashboard/alerts.critical_tasks` de inmediato.

---

## ✅ Corregido — antes 🟡 prioridad media

### 5. Cobro "Por hora" no tenía registro de horas trabajadas
**Ahora:** nueva pestaña "Horas" en el detalle del expediente — fecha, horas, descripción, si es facturable. Se conecta directo al generador de facturas: las horas no facturadas aparecen como partida seleccionable (igual que sesiones/tareas/costos) y, al facturarlas, quedan marcadas para no volver a aparecer como pendientes. Verificado end-to-end (registrar horas → aparecen en "no facturadas" → se incluyen en una factura → desaparecen de pendientes).

**Bug real encontrado de paso, ya corregido:** al construir esta conexión se descubrió que facturar una sesión o una tarea **nunca las marcaba como facturadas** — `create_invoice`/`update_invoice` guardaban la referencia en la factura pero nunca actualizaban `sessions.invoice_id` / `case_tasks.invoice_id`. Eso significa que, antes de esta corrección, la misma sesión o tarea se podía facturar dos veces sin que el sistema lo notara. Ya corregido para las tres (sesiones, tareas, horas).

### 6. El pipeline comercial no tenía valor monetario
**Ahora:** campo "Honorarios estimados" al crear/editar una oportunidad, visible en la tarjeta del tablero y sumado en un KPI "Valor del embudo" (Prospectos + Cotizados) tanto en Pipeline como en el Dashboard comercial.

### 7. Nóminas no usaba el catálogo de Personal
**Ahora:** "Nuevo pago" en Nóminas selecciona de la lista de `personal` (mismo catálogo que usan gastos fijos y comisiones) en vez de texto libre — el nombre y el rol se completan solos. Queda una opción "Otro (no está en el catálogo)" para el caso real de alguien que todavía no se ha dado de alta ahí.

### 8. La búsqueda global no cubría todo
**Ahora:** Ctrl+K también encuentra facturas (por número o cliente), tareas (por título) y oportunidades (por prospecto/cliente), además de clientes/expedientes/sesiones que ya tenía.

### 9. Crear una tarea exigía entrar primero a un expediente
**Ahora:** la vista global de Tareas tiene un botón "Nueva tarea" con selector de expediente — ya no hace falta navegar al expediente correcto primero para anotar un pendiente.

### 10. Los recordatorios por correo solo cubrían sesiones
**Ahora:** el mismo cron diario (`/internal/send-reminders`) manda además un correo por abogado con sus tareas vencidas o con plazo crítico próximo a vencer (agrupadas, un solo correo por persona por día, plazos críticos listados primero). Requiere que el usuario tenga correo cargado — se agregó el campo `email` a Usuarios para esto.

---

## Deliberadamente fuera de esta ronda (🟢 antes prioridad baja, sigue siendo prioridad baja)

Estos seis puntos no se tocaron — no porque no importen, sino porque cada uno es una iniciativa con su propio alcance, no un ajuste que quepa junto a los diez de arriba sin apurar el trabajo:

- **11. Documentos sin versión ni firma electrónica** — agrupar visualmente adjuntos por nombre base es barato; integrar firma electrónica de verdad depende de elegir un proveedor (DocuSign, Firmafy, etc.), una decisión de negocio, no técnica.
- **12. Sin portal de cliente** — implica una capa de autenticación y permisos completamente nueva (login de cliente, qué puede ver, qué no).
- **13. Sin autenticación de dos factores (2FA)** — necesita decidir el mecanismo (app TOTP vs. código por correo) antes de construirlo.
- **14. Listas sin paginación** — no urge con el volumen actual; tocaría varios endpoints a la vez y hoy no hay síntoma real de lentitud.
- **16. Sin soporte offline / PWA** — arquitectura de cache y service worker distinta a como está construido el resto del sistema.
- **15. CSV** — en realidad esto ya estaba más resuelto de lo que decía la auditoría original: Flujo de Caja ya tenía exportar CSV en sus 3 pestañas (error de la revisión inicial). Se agregó CSV a Expedientes, Facturas y Comisiones en esta misma ronda, que sí faltaban.

Si en algún momento quieres avanzar en alguno de estos cinco restantes, cada uno merece su propia conversación de alcance — no algo para meter de pasada.

---

## Deuda técnica ya conocida (heredada de sesiones anteriores, sin cambios)

- Tablas legado `categories`/`service_products` siguen en el esquema sin usarse (retiradas del código, no de la base).
- Columna `cases.service_area` sigue en el esquema (nullable, sin uso).
- "Días de cobro" (promedio apertura→cobro efectivo) no implementado — pendiente de definir qué cuenta como "cobrado" cuando hay pagos parciales.
- Cifras por defecto sin dato real del cliente: probabilidad de cobro por `estado_cobro`, reparto de gastos fijos entre familias.

---

## Cómo se verificó

Migración v31 (aditiva, sin pérdida de datos: `users.email`, `clients.archived_at`, `cases.archived_at`, `case_tasks.es_critico`, `oportunidades.honorarios_estimados_cents`, `payrolls.personal_id`, tabla `case_time_entries`) corrida en producción — `schema_version` 30→31 confirmado. Recorrido completo por HTTP contra producción como si fuera un abogado real: cliente → expediente → tarea crítica → registro de horas → factura con esas horas → archivar/restaurar cliente y expediente → oportunidad con honorarios estimados → nómina vía catálogo de Personal → búsqueda global → usuario con correo — 25 verificaciones, todas en verde. Todos los datos de prueba se limpiaron de producción al terminar (conteos confirmados de vuelta a la línea base). `npx tsc --noEmit` y `npm run build` limpios. Timer de backup instalado, habilitado y probado con una corrida manual real.

**Commits:** backend `d336b29` + `757beab` (fix del script de backup). Frontend `0d7747d`.

**Sin verificación visual en navegador** — misma limitación que el resto de esta sesión (sin `puppeteer-core` disponible); toda la validación fue estática (lectura de código) + funcional (HTTP contra producción).
