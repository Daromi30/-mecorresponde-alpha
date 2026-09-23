# MECORRESPONDE AI HANDOFF

Last updated:
2026-09-23

Main SHA:
6df78d646fb5e7fb01c4ee584228e0acf74467af

Render LIVE SHA:
6df78d646fb5e7fb01c4ee584228e0acf74467af

Current milestone:
Beta interna sintética: P1 de cierre parcial corregido y verificado en API LIVE; falta completar el recorrido visual adversarial A–H y la matriz manual antes de congelar un candidato.

Active owner:
WORK

Active task:
Actualizar runbook a todas las familias y continuar la prueba adversarial sintética.

Branch:
docs/internal-beta-runbook-refresh

PR:
#209 fusionado; PR de actualización de runbook pendiente.

CI:
SUCCESS en PR #209 y en el commit de merge `6df78d6`: Database Migrations y MECORRESPONDE CI. Pruebas locales de outcome y runbook: 12 passed. Suite completa en Windows: 666 passed, 1 fallo ya conocido por comprobar bits POSIX `0600` sobre NTFS; la misma suite Linux de CI está verde. `node --check` del script de outcome: PASS.

Completed in this block:

- Causa raíz: `verified_by_user=true` cerraba el caso sin confirmar que todos los compromisos materiales de la respuesta favorable estuvieran cumplidos.
- La API exige `remaining_material_commitments=none` para cerrar. `pending`, `unknown` o ausencia del dato conservan `RESOLVED_PENDING_EXECUTION` y `VERIFY_EXECUTION` abierta.
- La UI permite registrar lo parcial, muestra lo pendiente al volver y ofrece completar la verificación. El timeline distingue verificación parcial de resolución.
- La repetición idéntica de un parcial no duplica outcome, acción, reclamación ni eventos. El cierre posterior ocurre una sola vez.
- La ruta de recuperación comparte metadatos del nuevo contrato; la resolución terminal C05 se revisó y sigue basada en hechos confirmados.
- PR #209 fusionado; Render auto-deploy `dep-dape8h2jnfac73cap6ig` LIVE en el SHA exacto de `main`, sin deploy manual. `/health`: 200, `status=ok`, `families=26`, misma `runtime_revision`.
- Logs: PostgreSQL persistente, 11 fuentes existentes, `synthetic_internal_beta_ready=True`, `internal_beta_blockers=none`, almacenamiento local no persistente y uploads bloqueados, indexación pública no lista.
- Reproducción sintética sobre la API LIVE: cerrar con compromisos pendientes recibió 422; un cumplimiento parcial dejó `RESOLVED_PENDING_EXECUTION` y `VERIFY_EXECUTION` abierta sin duplicados; la devolución simulada posterior cerró una sola vez. Ver `docs/internal-beta-manual-evidence-2026-09-23.md`.
- Runbook actualizado a la matriz del manifiesto, con prueba de regresión que compara los códigos documentados con `supported_family_codes()` y evita regresar a la cifra obsoleta de 14.

Regression coverage:
Pruebas sintéticas de corrección contractual con devolución pendiente/desconocida, cierre monetario y no monetario de 0 €, llamada directa inválida, rollback, idempotencia, refresh/reentrada, auditoría/timeline, recuperación y todas las familias. Local Windows: 666 passed, 1 test POSIX `0600` excluido; suite Linux del PR verde.

Follow-up findings:
El runbook ya no describe 14 familias; la actualización está en la rama de desarrollo indicada. No hay P0/P1 nuevo en la prueba de API desplegada. La interfaz visual y el recorrido manual completo siguen sin verificar. El navegador integrado rechazó abrir el sitio (`ERR_BLOCKED_BY_CLIENT`), por lo que la reproducción desplegada se hizo por HTTPS/API y no debe contarse como validación visual.

Blockers:
No congelar beta hasta integrar la actualización del runbook y completar A–H y la matriz visual de todas las familias. Para datos reales siguen pendientes el ciclo de vida durable de PostgreSQL, el almacenamiento documental persistente y la privacidad real revisada.

Cost blockers:
Datastore durable y proveedor de almacenamiento persistente definitivos pueden requerir contratación; no activar sin autorización.

External/user decisions needed:
Datos empresariales reales y revisión formal de privacidad; elección y autorización de proveedores o planes con coste. Ninguna es necesaria para este arreglo sintético.

Next executable task:
WORK termina la suite local y CI del runbook, integra el PR documental si queda verde y reanuda A–H/matriz con datos sintéticos. Si aparece P0/P1, aislar el defecto para CODEX sin perder el progreso independiente. No pasar a datos reales ni habilitar uploads/indexación pública.
