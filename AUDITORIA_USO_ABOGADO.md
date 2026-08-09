# Auditoría de uso — el sistema visto como un abogado de bufete

**Fecha:** 2026-08-08
**Método:** lectura completa de las 18 páginas del frontend y sus routers/repositorio correspondientes en el backend (no es una prueba de clic en navegador — es una revisión de código puesta en el zapato de quien usaría esto todos los días: un abogado o el equipo administrativo de un despacho pequeño/mediano).
**Objetivo:** el sistema ya cubre con solidez la parte comercial, financiera y de catálogo (eso está auditado aparte en `PLAN_CATALOGO_FINANCIERO.md`). Esta revisión busca específicamente los vacíos que solo se notan cuando alguien intenta *vivir* en el sistema como abogado litigante o notario — no como administrador financiero.

No es una lista de bugs. Es una lista de decisiones de producto pendientes, ordenadas por qué tanto le duele a un despacho real no tenerlas.

---

## Lo que ya está fuerte (para no repetir en cada punto de abajo)

Adjuntos con roles (guía/evidencia) por tarea, sesiones y expediente; agenda con mes/semana/día/lista, arrastrar-para-reagendar, detección de choques de horario, sincronización con Google y Outlook Calendar; recordatorios automáticos por correo (24h y 2h antes) vía Resend; facturación con partidas armadas desde sesiones/tareas/costos no facturados, impresión a PDF; búsqueda global (Ctrl+K); multi-divisa (13 monedas); tema claro/oscuro; RBAC granular por módulo. Es una base sólida — lo que sigue son los huecos, no una crítica al conjunto.

---

## 🔴 Alta prioridad — riesgo real para el despacho, no solo incomodidad

### 1. No hay respaldo (backup) automático de nada
Revisé `docker-compose.yml` y `scripts/` — no existe ningún cron ni script de backup, ni de la base de datos ni de los documentos subidos (`data/attachments/`, que viven en disco local del servidor, no en almacenamiento redundante tipo S3). Todo corre en un solo VPS.

**Por qué le duele a un despacho:** un despacho legal no puede permitirse perder un expediente, un contrato firmado o una identificación de cliente. Si el disco falla o alguien borra la carpeta por error, no hay forma de recuperar nada — ni la base de datos ni los archivos.

**Sugerencia:** `pg_dump` diario a un bucket externo (o al menos a otro servidor) + respaldo del directorio `data/attachments/`. Es la mejora de menor esfuerzo con mayor reducción de riesgo de todo este documento.

### 2. Borrar un cliente o un expediente es permanente, sin papelera
`DELETE /clients/{id}` y `DELETE /cases/{id}` ejecutan un borrado real en la base — no hay estado "archivado" ni papelera de reciclaje. Un clic accidental en el ícono de basura (que ya vi en Clientes, Expedientes, Facturas, Nóminas, Sesiones) es irreversible salvo restaurando un backup — que, ver punto 1, no existe.

**Sugerencia:** al menos para clientes y expedientes (los registros con más historia legal detrás), cambiar el borrado por un estado `archivado` que los saca de las vistas activas pero no destruye el registro. Barato de construir, evita el peor escenario.

### 3. No hay verificación de conflicto de interés
Al crear un cliente o un expediente, el campo "Contraparte" (`opposing_party`) es texto libre — no se cruza contra la base de clientes existentes ni contra contrapartes de otros expedientes abiertos.

**Por qué le duele a un despacho:** representar a ambas partes de un mismo asunto (aunque sea sin querer, por desconocimiento del abogado que toma el caso nuevo) es una falta ética grave en cualquier colegio de abogados. Con 205 servicios y varios abogados usando el sistema, es cuestión de tiempo antes de que dos expedientes choquen sin que nadie lo note a tiempo.

**Sugerencia:** al guardar un expediente nuevo, buscar el nombre de la contraparte contra `clients.name` y contra `cases.opposing_party` de expedientes abiertos, y mostrar una alerta (no bloqueante, pero visible) si hay coincidencia.

### 4. Los plazos legales no se distinguen de un simple pendiente
Las tareas (`case_tasks`) tienen `due_date` y se marcan "vencida" en rojo — pero una tarea de "llamar al cliente" se ve exactamente igual que "presentar el recurso antes de que prescriba". No hay campo de severidad ni de tipo de plazo (procesal/administrativo/interno).

**Por qué le duele a un despacho:** perder un plazo procesal (prescripción, término de apelación, etc.) puede significar perder el caso o incurrir en responsabilidad profesional. Es la categoría de error que un sistema de gestión legal debería hacer *imposible* de pasar por alto, y hoy se ve igual que un pendiente cualquiera en una lista plana.

**Sugerencia:** agregar un campo `tipo_plazo` o simplemente `es_critico` (booleano) a `case_tasks`, con una alerta distinta (color, posición fija arriba del todo, quizás notificación aparte) en el Dashboard y en el `NotificationBell` — no mezclado con "expediente sin movimiento hace 15 días".

---

## 🟡 Prioridad media — fricción real del día a día, o dinero dejado sobre la mesa

### 5. Cobro "Por hora" existe en el catálogo, pero no hay registro de horas trabajadas
`servicios.unidad_cobro` incluye "Por hora" como opción, y `horas_estandar` es un valor de referencia — pero no encontré ningún lugar donde un abogado registre las horas reales que le dedicó a un expediente. Sin eso, un servicio cotizado "por hora" no tiene con qué facturarse de verdad; termina dependiendo de que alguien calcule las horas fuera del sistema.

**Sugerencia:** un registro simple de horas por expediente (fecha, abogado, horas, descripción breve) que alimente la partida "no facturada" del generador de facturas — ya existe el patrón para sesiones/tareas/costos, faltaría el mismo patrón para horas.

### 6. El pipeline comercial no tiene valor monetario
`oportunidades` no captura un honorario estimado/cotizado. El Dashboard comercial muestra conteos (Prospectos, Cotizados, Ganados) pero nunca un monto — no hay forma de responder "¿cuánto vale el embudo comercial ahora mismo?" sin salir del sistema.

**Sugerencia:** agregar `honorarios_estimados` a `oportunidades` (opcional, se ajusta al pasar a expediente) y sumarlo en el Dashboard comercial.

### 7. Nóminas no usa el catálogo de Personal que ya existe
`Payroll.tsx` pide `employee_name` como texto libre y `role` de una lista fija — completamente separado del catálogo `personal` (PER-XXX) que ya se construyó en Finanzas para gastos fijos y comisiones. El backend de nóminas busca la cuenta contable por coincidencia de nombre (`ILIKE '%empleado%'`), lo cual es fràgil si alguien escribe el nombre distinto entre un lado y otro (ej. "Andrea" en Nóminas vs "Andrea Escobar" en Personal).

**Sugerencia:** que el formulario de "Nuevo pago" en Nóminas seleccione de la lista de `personal` en vez de texto libre — un solo lugar para saber quién trabaja en el despacho.

### 8. La búsqueda global no cubre todo
El buscador Ctrl+K (`GlobalSearch`) solo busca en clientes, expedientes y sesiones. Facturas, tareas y oportunidades quedan fuera — si un abogado recuerda el número de una factura o el título de una tarea, no aparece nada.

**Sugerencia:** ampliar `dashboard.search()` para incluir esas tres entidades. Es un cambio de bajo esfuerzo con alto impacto en percepción de "el sistema encuentra lo que busco".

### 9. Crear una tarea exige entrar primero a un expediente específico
La página global "Tareas" es de solo lectura/checklist — no tiene botón de "nueva tarea". Para anotar un pendiente hay que abrir el expediente correcto primero. Para alguien que acaba de colgar el teléfono con un cliente y quiere anotar algo rápido, es fricción innecesaria.

**Sugerencia:** agregar "Nueva tarea" en la vista global de Tareas, con selector de expediente (puede reusar el mismo patrón de búsqueda que ya existe en otras partes).

### 10. Los recordatorios por correo solo cubren sesiones
El cron de recordatorios (`/internal/send-reminders`) manda correos 24h y 2h antes solo para sesiones agendadas. Las tareas vencidas, facturas por vencer y expedientes "sin movimiento" solo se ven si alguien entra al Dashboard — no hay ningún empuje (correo, push) hacia afuera.

**Sugerencia:** extender el mismo mecanismo de correo a tareas con `due_date` próximo, priorizando primero cualquier tarea marcada como plazo crítico (ver punto 4).

### 11. Los documentos no tienen control de versiones ni firma
`attachments` guarda archivo + nombre + fecha — si alguien sube "Contrato_v2.pdf" encima de "Contrato.pdf", son dos archivos sueltos, no una versión de la misma pieza. No hay integración de firma electrónica (aunque sea solo un enlace externo a un proveedor como DocuSign/Firmafy).

**Sugerencia:** no es urgente construir un sistema de versionado completo, pero al menos agrupar visualmente adjuntos con el mismo nombre base, y considerar un campo "documento firmado (sí/no)" para contratos.

---

## 🟢 Prioridad baja — mejoras de producto a futuro, no urgencias

### 12. Sin portal de cliente
Todo es de uso interno — un cliente no puede ver el estado de su expediente, sus facturas o subir un documento sin llamar o escribir. Cada vez más despachos ofrecen esto como diferenciador. No es trivial (implica una capa de autenticación y permisos completamente nueva), por eso queda en prioridad baja, pero vale la pena tenerlo en el radar a mediano plazo.

### 13. Sin autenticación de dos factores (2FA)
El login es usuario/contraseña simple. Dado que el sistema guarda identificaciones, contratos y datos financieros de clientes, un segundo factor (TOTP o correo) sería razonable para cuentas de administrador al menos.

### 14. Listas sin paginación
Clientes, Expedientes, Facturas, Tareas globales — todas traen la lista completa y filtran en el navegador. Con el volumen actual (pocos clientes reales) no se nota, pero no vi límite/`offset` en ninguno de esos endpoints. Si el despacho crece a cientos de expedientes, esas pantallas empezarán a sentirse lentas. No urge resolverlo hoy, sí vale la pena tenerlo anotado antes de que sea un problema real.

### 15. Exportar a CSV solo existe en Clientes
Flujo de Caja, Expedientes, Facturas y Comisiones no tienen botón de exportar — útil para un contador externo o para respaldos manuales del propio usuario mientras no exista el backup automático del punto 1.

### 16. Sin soporte offline / PWA
Si un abogado está en tribunales con mal señal, el sistema no funciona en absoluto (ni siquiera para consultar algo ya cargado antes). No es prioritario, pero es una limitación real del contexto en que trabaja un litigante.

### 17. La página de Configuración ya admite que faltan cosas
El propio `Settings.tsx` tiene una tarjeta "Próximamente: Zona horaria · Formato de fecha · Notificaciones por correo · Backup automático" — confirma que backup (punto 1) y notificaciones más allá de sesiones (punto 10) ya estaban identificados como pendientes por quien construyó la pantalla, solo que nunca se priorizaron.

---

## Deuda técnica ya conocida (heredada de sesiones anteriores, no nueva)

Estos ya están documentados en `PLAN_CATALOGO_FINANCIERO.md` — se listan aquí solo para que este documento sea la referencia única de "qué falta":
- Tablas legado `categories`/`service_products` siguen en el esquema sin usarse (retiradas del código, no de la base).
- Columna `cases.service_area` sigue en el esquema (nullable, sin uso).
- "Días de cobro" (promedio apertura→cobro efectivo) no implementado — pendiente de definir qué cuenta como "cobrado" cuando hay pagos parciales.
- Cifras por defecto sin dato real del cliente: probabilidad de cobro por `estado_cobro`, reparto de gastos fijos entre familias.

---

## Resumen para decidir qué atacar primero

Si solo se pudiera hacer una cosa esta semana: **el backup automático (punto 1)**. Es lo único de esta lista donde no hacer nada puede significar perder todo el sistema de un día para otro, y es también lo más barato de resolver.

Si se pudiera hacer una segunda cosa: **la verificación de conflicto de interés (punto 3)** o **distinguir plazos legales críticos (punto 4)** — son los dos puntos donde un descuido del sistema se traduce directamente en un problema ético o profesional para el despacho, no solo en una mala experiencia de uso.
