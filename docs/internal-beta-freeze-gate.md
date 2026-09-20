# MECORRESPONDE — gate de congelación de beta interna

Este documento evita declarar “lista” una beta que solo está verde en tests pero no coincide con lo desplegado.

## Condiciones para congelar una candidata

La beta interna sintética solo puede congelarse cuando se cumplen simultáneamente:

1. `main` no tiene PR funcional pendiente que cambie lifecycle, seguridad, UI de acción, persistencia o trazabilidad.
2. Database Migrations y MECORRESPONDE CI están verdes sobre el commit candidato.
3. Render muestra **ese SHA exacto** como `LIVE`; no basta con que un commit anterior siga sirviendo.
4. PostgreSQL persistente está disponible y el health de persistencia del servicio es correcto.
5. El cockpit `/api/admin/readiness` devuelve `synthetic_internal_beta_ready=true` y `internal_beta_blockers=[]`.
6. La beta sigue usando exclusivamente datos sintéticos/test.
7. No se han activado indexación pública, proveedor transaccional, almacenamiento documental real ni ningún servicio de pago por el mero hecho de congelar esta versión.

## Qué significa “congelada”

Congelar no significa lanzar. Significa identificar un SHA estable para someterlo a:

- recorrido manual adversarial;
- auditoría externa con IA jurídica especializada según `docs/external-legal-audit-gate.md`;
- revisión jurídica humana española de los elementos sustantivos;
- revisión de bloqueantes antes de datos reales.

Cualquier corrección material posterior genera un nuevo SHA candidato y obliga a repetir las pruebas afectadas y CI completo.

## Paquete mínimo de freeze

Registrar:

- SHA de `main`;
- SHA LIVE en Render;
- fecha de congelación;
- resultado de CI/migraciones;
- resultado del readiness;
- manifiesto de familias;
- inventario de acciones y estados;
- catálogo jurídico y fuentes oficiales;
- lista de bloqueantes de beta real/pública;
- incidencias conocidas aceptadas expresamente.

## Bloqueantes que no impiden la beta interna sintética

Pueden permanecer deliberadamente en rojo para una beta interna con datos ficticios:

- ciclo de vida operativo definitivo de la base para datos reales;
- almacenamiento documental persistente para documentos reales;
- información de privacidad publicada;
- entrega transaccional de email;
- verificación obligatoria de email;
- indexación pública.

Estos puntos sí deben resolverse en la fase que les corresponda. El freeze interno no los “da por solucionados”.

## Regla de despliegue

Si el commit candidato no alcanza `LIVE` o el deploy queda bloqueado/fallido, la beta no se congela aunque GitHub esté verde. La versión anterior puede seguir sirviendo tráfico, pero no representa el código candidato.
