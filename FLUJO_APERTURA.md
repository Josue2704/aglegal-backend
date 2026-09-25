# Captación, apertura y ejecución

## Uso

1. Registrar la oportunidad con origen comercial elegido expresamente, contacto, servicio y seguimiento. Los registros sin responsable, siguiente acción o fecha aparecen señalados en Pipeline.
2. Al aceptar el trabajo, pulsar Ganado. Seleccionar una ficha existente o registrar el cliente, revisar coincidencias y posibles conflictos, y confirmar honorarios pactados, alcance y condiciones de cobro. Un honorario cero debe ser una decisión explícita, no un estimado vacío.
3. Revisar las tareas precargadas del servicio. Se pueden excluir, agregar o editar tareas y ajustar sus fechas y responsables. Si no hay plantilla, se propone una primera revisión documental. Debe quedar al menos una tarea con fecha; hereda el responsable del expediente cuando no se asigna otro.
4. Confirmar la apertura. Cliente, expediente, tareas, atribución y vínculos se guardan juntos. Reintentar Ganado sobre una oportunidad ya convertida devuelve el mismo expediente, también ante solicitudes simultáneas.
5. Se abre la pestaña de tareas. El historial conserva el acuerdo y el seguimiento anterior. Abrir no crea una factura ni un ingreso: se utiliza el flujo de [facturación](FACTURACION.md) cuando corresponda.

La apertura manual utiliza el mismo editor de tareas y exige acuerdo, revisión, servicio, honorarios explícitos y responsable activo. Cambiar el servicio limpia la selección de su plantilla anterior; cambiar la fecha de apertura desplaza las fechas todavía automáticas, conservando las editadas.

## Seguimiento e historial

Las oportunidades registran alta, cambios de seguimiento y transiciones con fecha y autor. Al cotizar se conserva una fotografía de la estimación y servicio; no se genera un documento formal de propuesta ni se envía correo. La aceptación se documenta en el alcance y revisión de apertura; no se añadió firma electrónica.

Todas las rutas de cierre de tareas requieren resultado. Reabrir reinicia el estado actual pero conserva fecha, autor y resultado anteriores en el historial. Las rutas de edición de notas, criticidad y cierre aplican el permiso tareas.editar. Las tareas sin responsable y las críticas sin fecha se señalan dentro del expediente.

La conversión exige pipeline.editar, expedientes.crear y tareas.crear; para crear una ficha nueva también clientes.crear. El directorio de asignación solo devuelve nombres y usuarios activos, sin requerir acceso a administración de usuarios.

Se puede seleccionar el originador por identificador. Si se deja la atribución según el origen comercial y no existe coincidencia única, el historial del expediente señala la asignación pendiente. La atribución múltiple sigue gestionándose en el expediente.

## Integridad y actualización

La migración 46 agrega el registro único de conversión por oportunidad y los eventos de trabajo. Conserva los enlaces existentes y no reconstruye retrospectivamente decisiones o resultados que antes no se registraban. Los expedientes convertidos se archivan, evitando eliminar el vínculo comercial.

La transacción de apertura aplaza los commits internos y revierte todos los registros nuevos si falla cualquier paso. Un bloqueo compartido protege conversiones, alta de clientes y generación de referencias de expedientes. Las pruebas cubren fallos tardíos, concurrencia, vinculación de clientes, permisos y cierre/reapertura; se ejecutan en el esquema desechable aglegal_test.
