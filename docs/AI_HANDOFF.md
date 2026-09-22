# MECORRESPONDE AI HANDOFF

Last updated:
2026-09-22

Main SHA:
5663d8b28a35817355f38b6c55ecd231916a0fa2

Render LIVE SHA:
5663d8b28a35817355f38b6c55ecd231916a0fa2

Current milestone:
Beta interna sintética: resolver el P1 y reanudar el recorrido adversarial antes de congelar un candidato.

Active owner:
WORK

Active task:
Revisar e integrar PR de partial outcome confirmation y reanudar prueba adversarial.

Branch:
fix/partial-outcome-confirmation

PR:
#209 — https://github.com/Daromi30/-mecorresponde-alpha/pull/209

CI:
SUCCESS en PR #209: legal-engine-regression, postgres-persistence, postgres-backup-restore y postgres-migrations (commit técnico `f18f139`).

Completed in this block:

- Causa raíz: `verified_by_user=true` cerraba el caso sin confirmar que todos los compromisos materiales de la respuesta favorable estuvieran cumplidos.
- La API exige `remaining_material_commitments=none` para cerrar. `pending`, `unknown` o ausencia del dato conservan `RESOLVED_PENDING_EXECUTION` y `VERIFY_EXECUTION` abierta.
- La UI permite registrar lo parcial, muestra lo pendiente al volver y ofrece completar la verificación. El timeline distingue verificación parcial de resolución.
- La repetición idéntica de un parcial no duplica outcome, acción, reclamación ni eventos. El cierre posterior ocurre una sola vez.
- La ruta de recuperación comparte metadatos del nuevo contrato; la resolución terminal C05 se revisó y sigue basada en hechos confirmados.

Regression coverage:
Pruebas sintéticas de corrección contractual con devolución pendiente/desconocida, cierre monetario y no monetario de 0 €, llamada directa inválida, rollback, idempotencia, refresh/reentrada, auditoría/timeline, recuperación y todas las familias. Local Windows: 666 passed, 1 test POSIX `0600` excluido; suite Linux del PR verde.

Follow-up findings:
FOLLOW_UP_FINDING — El runbook `docs/internal-beta-runbook.md` aún describe 14 familias mientras el manifiesto y runtime muestran 26. Gravedad operativa baja; reproducible comparando ese documento con `/health`. WORK debe actualizar la matriz antes del freeze. Fuera del contrato de outcomes de este PR.

Blockers:
No congelar beta hasta integrar y repetir el recorrido A–H/matriz afectado. Para datos reales siguen pendientes el ciclo de vida durable de PostgreSQL, el almacenamiento documental persistente y la privacidad real revisada.

Cost blockers:
Datastore durable y proveedor de almacenamiento persistente definitivos pueden requerir contratación; no activar sin autorización.

External/user decisions needed:
Datos empresariales reales y revisión formal de privacidad; elección y autorización de proveedores o planes con coste. Ninguna es necesaria para este arreglo sintético.

Next executable task:
WORK integra si procede, verifica LIVE y reanuda recorrido manual A–H/matriz desde el punto afectado.
