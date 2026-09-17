# MECORRESPONDE — durabilidad de base de datos antes de una beta con datos reales

Este documento registra el estado operativo actual y no autoriza por sí solo el uso de datos personales reales.

## Estado verificado de Render

La base de datos actual de MECORRESPONDE es `mecorresponde-alpha-db`, Render Postgres en plan `free`, región Frankfurt. Fue creada el 15 de septiembre de 2026 y Render informa una fecha de expiración del 15 de octubre de 2026.

Fuentes oficiales revisadas:

- Render — Free instances: https://render.com/docs/free
- Render — PostgreSQL backups and recovery: https://render.com/docs/postgresql-backups
- Render — Pricing: https://render.com/pricing

Según la documentación oficial revisada para esta configuración, las bases Render Postgres en plan Free:

- expiran 30 días después de su creación;
- quedan inaccesibles al expirar salvo actualización a un plan de pago durante el periodo de gracia;
- se eliminan después del periodo de gracia si no se actualizan;
- no incluyen copias de seguridad gestionadas ni recuperación point-in-time;
- no están recomendadas por Render para aplicaciones de producción.

## Estado de recuperación probado por MECORRESPONDE

El repositorio ya dispone de tooling propio para crear un `pg_dump` en formato custom, verificar integridad y catálogo, y restaurar el archivo. La integración CI ejecuta además un ensayo real contra PostgreSQL: crea un dump, levanta una base aislada desechable, restaura el backup y comprueba un dato centinela.

Por tanto, el cockpit puede mantener:

- `DATABASE_RECOVERY_AVAILABLE = True`

Esto significa que la **ruta técnica de copia y restauración está probada**. No significa que exista todavía una política operativa de backups de producción, una programación automática, retención definida o recuperación point-in-time.

## Bloqueo que continúa antes de usar datos reales

Que el backend use PostgreSQL, que los datos sobrevivan a despliegues y que el procedimiento de restore esté probado no hace que la infraestructura actual sea suficientemente durable para una beta con datos reales.

La base gratuita sigue teniendo una caducidad conocida y no existe todavía un ciclo de vida operativo resuelto. Por eso debe continuar:

- `DATABASE_LIFECYCLE_MANAGED = False`

Antes de una beta con datos reales habrá que resolver la continuidad del datastore y definir cómo se ejecutarán, almacenarán, protegerán y comprobarán las copias operativas. El readiness mantiene este punto como `BETA_BLOCKER`.

No se activará ningún plan de pago ni servicio adicional sin aprobación expresa.

## Alternativas a evaluar cuando toque desbloquearlo

1. Mantener Render y pasar la base a una modalidad que no caduque y cuya recuperación cubra las necesidades de la beta.
2. Mantener temporalmente un datastore económico y operar un proceso externo, cifrado y probado de copias y restauración, si resulta adecuado jurídica y operativamente.
3. Migrar a otro proveedor de PostgreSQL si ofrece mejor relación coste/durabilidad para esa fase.

La decisión se tomará con precios y condiciones vigentes en ese momento. No se debe elegir proveedor solo para quitar un indicador rojo del cockpit.
