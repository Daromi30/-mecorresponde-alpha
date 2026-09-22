# MECORRESPONDE AI HANDOFF

Last updated:
2026-09-22 19:20:00 +02:00

Main SHA:
7a28bdf402f0167b4ada08c17d2996e690d3adf6

Render LIVE SHA:
7a28bdf402f0167b4ada08c17d2996e690d3adf6

Current milestone:
Congelar una candidata de beta interna sintética y cerrar los bloqueantes técnicos gratuitos antes de una beta cerrada con datos reales.

Active owner:
CODEX

Base SHA:
7a28bdf402f0167b4ada08c17d2996e690d3adf6

Branch:
feat/runtime-revision-health

Objective:
Hacer verificable desde el propio runtime qué revisión exacta está sirviendo Render. Exponer de forma segura el SHA completo de `RENDER_GIT_COMMIT` en `/health` y en el log estructurado de arranque, sin convertir su ausencia o formato inválido en un fallo de disponibilidad. La variable es metadata no secreta proporcionada automáticamente por Render; no crear ni modificar configuración o secretos del servicio.

Acceptance criteria:

1. `/health` conserva sus campos y semántica actuales y añade un campo de revisión inequívoco.
2. En Render, el campo devuelve exactamente el SHA completo de 40 caracteres de `RENDER_GIT_COMMIT`.
3. Fuera de Render, si la variable falta, `/health` continúa respondiendo y usa un valor explícito y no engañoso como `unknown`.
4. Un valor presente pero no válido no se publica como SHA fiable; se trata de forma fail-safe y queda cubierto por tests.
5. El arranque registra la misma revisión sin incluir secretos ni volcar el entorno.
6. No cambia readiness, indexación, privacidad, uploads, persistencia ni comportamiento funcional del Motor de Resolución.
7. CI y Database Migrations quedan verdes en el PR; no hacer merge ni desplegar producción desde CODEX.

Tests:

- Tests unitarios de `/health` con SHA válido, variable ausente y valor inválido.
- Test del mensaje de arranque o de la función pura que normaliza la revisión, evitando assertions frágiles sobre logging global.
- Suite completa existente y compilación/comprobaciones del repositorio definidas por CI.

Do not touch:

- No inventar datos legales o empresariales ni completar la información de privacidad.
- No cambiar secretos, variables de Render, proveedores, planes, costes ni `render.yaml`.
- No habilitar uploads reales, almacenamiento documental no persistente, datos reales, email transaccional o indexación pública.
- No modificar la lógica jurídica, familias, lifecycle de casos, migraciones o esquema de base de datos.
- No hacer merge a `main`, no desplegar producción y no trabajar en otra rama.

PR:
Pendiente de crear por CODEX cuando el bloque técnico esté completo y en verde.

CI:
`main` 7a28bdf: Database Migrations y MECORRESPONDE CI correctos tras el merge del PR #207.

Completed in this block:

- PR #207 fusionado en `main` con merge commit `7a28bdf402f0167b4ada08c17d2996e690d3adf6`.
- Auto-deploy de Render `dep-dapbdi67bikc73etdel0` finalizado LIVE sin disparo manual; `main` y LIVE coinciden exactamente.
- `/health` devuelve 200 y 26 familias.
- Logs de arranque: PostgreSQL persistente con 11 fuentes jurídicas existentes; `synthetic_internal_beta_ready=True`; `internal_beta_blockers=none`; arranque completo.
- `/health/storage` mantiene `backend=local`, `persistent=false`, `uploads_allowed=false`.
- `/privacidad` mantiene 503, `Cache-Control: no-store` y `X-Robots-Tag: noindex, nofollow` mientras faltan datos reales y revisión.

Blockers:
Para datos reales siguen bloqueados el ciclo de vida durable de PostgreSQL, el almacenamiento documental persistente y la información de privacidad revisada. Ninguno se debe marcar resuelto por este bloque de observabilidad.

Cost blockers:
Datastore durable y proveedor de almacenamiento persistente definitivos pueden requerir contratación; no activar sin autorización.

External/user decisions needed:
Datos empresariales reales y revisión formal de privacidad; elección y autorización de proveedores o planes con coste.

Next executable task:
CODEX implementa y prueba la exposición fail-safe de la revisión de runtime descrita en este handoff, hace push solo a `feat/runtime-revision-health` y crea el PR para revisión de WORK.
