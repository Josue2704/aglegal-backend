# Operación financiera sin controles paralelos

Implementado el 25/09/2026. Esquema local actualizado a versión 47.

## Expedientes y proyección

La apertura manual y la conversión de una oportunidad ganada requieren un servicio activo, un mes esperado de cobro y una probabilidad entre 0% y 100%. El porcentaje se puede modificar al editar el expediente. El mes no puede preceder la apertura. La cartera utiliza ese porcentaje y el saldo neto pendiente.

Los expedientes anteriores sin plan completo se señalan en Finanzas. No se inventó una fecha de cobro para ellos. Mientras se revisan, los que tienen mes pero no porcentaje conservan la estimación anterior por estado.

Se muestran por separado:

- Meta: volumen presupuestado × ticket objetivo.
- Estimación de cierre: cobrado del mes + cartera ponderada para ese mes.
- Proyección comercial: meta + cartera ponderada, como escenario de negocio adicional. No debe interpretarse como efectivo ni sumarse a una meta que ya contiene esos mismos expedientes.

## Comisiones

Se aplica la decisión del usuario: **recuperar primero los costos directos reales y generar comisión después sobre la utilidad cobrada**.

Para cada abono, ordenado por fecha e identificador:

`base incremental = max(0, cobrado acumulado − costos reales) − max(0, cobrado anterior − costos reales)`.

Se excluyen impuestos y fondos de terceros mediante los importes netos operativos existentes. Se mantienen los tramos mensuales 10%/12%/15% y el 5% de venta cruzada. Los costos estimados no sustituyen a los reales.

Ejemplo: costos $200, primer abono $100 → base $0; segundo abono $400 → base $300; tercer abono $500 → base adicional $500. Con un solo originador y dentro del primer tramo, la comisión acumulada sería $80 sobre $800 de utilidad cobrada.

### Revisión y pago

1. Configurar originadores y participación en el expediente.
2. Registrar cobros y costos reales; el sistema calcula los devengos.
3. En Comisiones → Revisión y pago, documentar la evidencia comercial y confirmar elegibilidad. Una renovación automática o un simple seguimiento no justifican venta cruzada.
4. Seleccionar las comisiones aprobadas de una sola persona, incluyendo sus ajustes pendientes.
5. Registrar la fecha del pago realizado, referencia del comprobante y cuenta del egreso. Se crea una liquidación y un único gasto; si se compensan importes hasta cero, se conserva la liquidación sin salida de efectivo.
6. Consultar el historial de liquidaciones, comisiones incluidas, comprobante, gasto y usuario que registró el pago.

El sistema registra un pago realizado; no inicia transferencias bancarias. No permite una fecha de pago futura ni repetir el pago de las mismas comisiones. La misma solicitud reintentada devuelve la liquidación existente.

Los permisos `comisiones.aprobar` y `comisiones.pagar` son independientes de editar originadores. El administrador dispone de ellos; otros roles deben recibirlos expresamente desde Roles.

### Correcciones

Los cambios en abonos, costos y originadores recalculan los devengos afectados. Una aprobación anterior no se transfiere automáticamente al cálculo nuevo.

- Sin pago: se anula el devengo original con un movimiento compensatorio en su período y se calcula el reemplazo.
- Con pago: se conserva la liquidación y el gasto; se genera un ajuste desde el siguiente período, o el período actual si aquel ya pasó. El reemplazo asociado se reconoce en ese período de corrección.
- Antes de pagar nuevamente a esa persona, deben revisarse e incluirse sus ajustes pendientes. Un saldo negativo queda pendiente de compensación; no se registra como un pago positivo.

Los gastos generados por liquidaciones no pueden modificarse ni borrarse desde Gastos. La corrección conserva el comprobante y se realiza mediante ajustes de comisión.

## Indicadores

- Días de cobro: usa aplicaciones vigentes de `invoice_payments`; excluye las liberadas por cancelación. Promedia por aplicación, no por importe. Los cobros sin aplicación pueden usar la fecha real de cierre del expediente. Los anticipos anteriores a la referencia se informan sin medición, no como cero días.
- Conversión: filtros de mes, origen y servicio. El mes identifica la cohorte de cotizaciones; muestra cuántas se han ganado. Los prospectos sin cotizar se agrupan por mes de captación.
- Origen: permite agrupar ingresos y utilidad por originador o por canal de captación. Los expedientes sin canal vinculado se conservan como “Sin canal”.

## Validación

275 pruebas de backend aprobadas. Incluyen recuperación de costos, abonos retroactivos, costos tardíos, revisión, separación de permisos, pago concurrente/idempotente, gasto protegido, compensación y aplicaciones de facturas canceladas. Compilación de frontend completada.

El navegador disponible mostró la pantalla de inicio de sesión; no se certificó una nueva revisión visual de las pantallas autenticadas. Los contratos de API y permisos sí se comprobaron con pruebas HTTP sobre el esquema aislado de pruebas. No se importaron datos históricos ni se modificó el Excel.
