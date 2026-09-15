# MECORRESPONDE — durabilidad de base de datos antes de una beta con datos reales

Este documento registra el estado operativo actual y no autoriza por sí solo el uso de datos personales reales.

## Estado verificado de Render

La base de datos actual de MECORRESPONDE es `mecorresponde-alpha-db`, Render Postgres en plan `free`, región Frankfurt. Fue creada el 15 de septiembre de 2026 y Render informa una fecha de expiración del 15 de octubre de 2026.

Fuentes oficiales revisadas:

- Render — Free instances: https://render.com/docs/free
- Render — PostgreSQL backups and recovery: https://render.com/docs/postgresql-backups
- Render — Pricing: https://render.com/pricing

Según la documentación oficial vigente, las bases Render Postgres en plan Free:

- expiran 30 días después de su creación;
- quedan inaccesibles al expirar salvo actualización a un plan de pago durante el periodo de gracia;
- se eliminan después del periodo de gracia si no se actualizan;
- no incluyen copias de seguridad gestionadas ni recuperación point-in-time;
- no están recomendadas por Render para aplicaciones de producción.

## Implicación para MECORRESPONDE

Que el backend use PostgreSQL y que los datos sobrevivan a un despliegue no significa que la infraestructura sea suficientemente durable para una beta con datos reales.

Mientras el datastore tenga una caducidad no resuelta y no exista una ruta de recuperación probada, el cockpit de readiness debe mantener en `False` estas dos capacidades:

- `DATABASE_LIFECYCLE_MANAGED`
- `DATABASE_RECOVERY_AVAILABLE`

No se activará ningún plan de pago ni servicio adicional sin aprobación expresa. Antes de una beta con datos reales habrá que elegir una solución que cubra ambas capacidades y comprobar su coste total.

## Alternativas a evaluar cuando toque desbloquearlo

1. Mantener Render y pasar la base a un plan que no caduque y tenga recuperación adecuada.
2. Mantener temporalmente un datastore económico pero añadir un proceso externo, cifrado y probado de copias y restauración, si jurídicamente y operativamente resulta aceptable.
3. Migrar a otro proveedor de PostgreSQL si ofrece mejor relación coste/durabilidad para la fase beta.

La decisión debe hacerse con precios y condiciones vigentes en ese momento. No se debe elegir proveedor solo para quitar un indicador rojo del cockpit.
