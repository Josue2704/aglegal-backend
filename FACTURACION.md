# Facturación por expediente

## Flujo implementado

1. Registrar la tarea en su expediente. Un honorario adicional necesita importe y autorización. Sin adicional, la tarea forma parte del trabajo ya contratado.
2. El extra aparece para facturar cuando la tarea está terminada o se marcó el acuerdo de cobro anticipado. Guardar la tarea no factura ni registra dinero recibido.
3. Abrir «Preparar factura de este expediente», seleccionar los extras y gastos reembolsables pendientes. Los importes acordados se recuperan automáticamente. Los costos internos no son cobros al cliente.
4. Guardar un borrador o emitir la factura. El borrador reserva las partidas; la emisión fija su contenido. Una partida no puede aparecer en dos facturas activas.
5. Entregar el documento mediante impresión/PDF. Emitir no envía correo ni constituye una integración con facturación electrónica fiscal.
6. Al recibir dinero, usar «Registrar pago»: importe, fecha real, cuenta de ingreso y referencia. Se admiten abonos; la factura queda pagada únicamente cuando se cubre el saldo.
7. Si el ingreso ya se registró como anticipo, aplicar el saldo disponible del mismo cliente y expediente. Esto no crea otro ingreso ni otra comisión.

Los pagos distinguen honorarios de reembolsos para mantener el ingreso operativo correcto. El resumen del expediente separa honorarios contratados, extras, importes reservados/facturados y facturas pendientes de pago.

## Correcciones y cancelaciones

Solo los borradores se editan o eliminan. Para corregir una factura emitida, cancelarla y preparar otra. La cancelación libera las partidas y conserva los ingresos y comisiones existentes; el dinero queda disponible para aplicarlo a otra factura compatible. No representa una devolución de dinero.

Los ingresos con historial de aplicación están protegidos contra edición o eliminación. Las operaciones de pago son atómicas e idempotentes, y las reservas están protegidas frente a solicitudes concurrentes.

## Actualización e historial

La migración 45 agrega aplicaciones de pagos y numeración automática, y vincula los ingresos históricos existentes sin inventar cobros faltantes. Las inconsistencias heredadas se muestran como pendientes de revisión; no deben corregirse marcando manualmente una factura como pagada. Revisar el respaldo del ingreso y, si corresponde, cancelar y reemplazar la factura conservando su historial.

La migración se ejecuta mediante el mecanismo habitual de inicialización de base de datos. Las pruebas de integración utilizan un esquema desechable separado de los datos de uso real.
