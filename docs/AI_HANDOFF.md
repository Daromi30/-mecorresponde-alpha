# MECORRESPONDE AI HANDOFF

Last updated:
2026-09-22 21:25 +02:00

Main SHA:
5663d8b28a35817355f38b6c55ecd231916a0fa2

Render LIVE SHA:
5663d8b28a35817355f38b6c55ecd231916a0fa2

Current milestone:
Beta interna sintética: recorrido manual adversarial y corrección de incidencias de lifecycle antes de congelar un candidato.

Active owner:
CODEX

Base SHA:
5663d8b28a35817355f38b6c55ecd231916a0fa2

Branch:
fix/partial-outcome-confirmation

Objective:
Corregir el cierre prematuro de un expediente cuando una respuesta favorable contiene varios compromisos y solo se ha comprobado parte de ellos. La prueba manual sintética encontró una respuesta que prometía corregir el precio y devolver la diferencia: al registrar únicamente la corrección contractual, importe recuperado 0 € y una nota expresa de que la devolución no estaba acreditada, el expediente pasó de `RESOLVED_PENDING_EXECUTION` a `RESOLVED`. Ver `docs/internal-beta-manual-evidence-2026-09-22.md`.

Acceptance criteria:

1. El flujo permite registrar cumplimiento parcial sin declarar resuelto el expediente; mantiene `RESOLVED_PENDING_EXECUTION` y la acción `VERIFY_EXECUTION` abierta mientras quede una obligación material pendiente.
2. El usuario puede identificar explícitamente si queda por cumplir alguna parte de la respuesta favorable, incluida una devolución prometida. Un valor afirmativo o desconocido no cierra el caso. No se infiere cumplimiento desde texto libre ni se inventa una obligación por palabras clave.
3. El cierre solo ocurre tras confirmación explícita de que todos los compromisos materiales aplicables se han cumplido, con evidencia coherente para cada tipo de resultado. Un importe recuperado de 0 € sigue siendo válido para una resolución exclusivamente no monetaria realmente completa.
4. La API impone el gate, no solo la interfaz. Un intento de cierre parcial no deja acción, outcome, auditoría o timeline contradictorios; repetirlo no duplica la reclamación inicial ni los eventos.
5. Tras un cumplimiento parcial, la UI explica qué falta y ofrece continuar la verificación. Tras cierre completo, reentrada y refresh conservan `RESOLVED` y la documentación queda en solo lectura.
6. El arreglo se limita al contrato de verificación de cumplimiento, UI y pruebas necesarias. No cambia reglas jurídicas, clasificación de respuestas ni plazos.
7. CI y Database Migrations verdes en el PR. CODEX hace push a esta rama y prepara PR para WORK; no fusiona ni despliega.

Tests:

- Regresión end to end de respuesta que promete corrección y devolución, con corrección comprobada pero devolución pendiente o desconocida.
- API: cumplimiento parcial conserva `VERIFY_EXECUTION` abierta y no marca `RESOLVED`; cierre completo sí lo hace.
- Resolución solo no monetaria y resolución monetaria completa siguen funcionando.
- Reentrada/refresh, timeline y ausencia de duplicados después de cumplimiento parcial y completo.
- Suite existente y checks de CI del repositorio.

Do not touch:

- No usar datos, emails, documentos ni referencias reales; usar solo fixtures sintéticos.
- No inventar derecho, plazos, proveedores ni información empresarial o de privacidad.
- No habilitar uploads, indexación pública, servicios de pago o nuevos secretos.
- No modificar PostgreSQL, migraciones destructivas, familias o el Motor jurídico fuera del contrato de outcome.
- No editar otra rama, fusionar a `main` ni desplegar producción desde CODEX.

PR:
#208 fusionado. Nuevo PR de esta rama pendiente de implementación.

CI:
Sobre `main` 5663d8b: Database Migrations y MECORRESPONDE CI SUCCESS.

Completed in this block:

- PR #208 fusionado; auto-deploy Render `dep-dapd5efavr4c73drujl0` LIVE en 1m10s sin deploy manual.
- `/health` 200: `status=ok`, `families=26`, `runtime_revision=5663d8b28a35817355f38b6c55ecd231916a0fa2`.
- Log de arranque: misma revisión, PostgreSQL persistente con 11 fuentes existentes, `synthetic_internal_beta_ready=True`, `internal_beta_blockers=none`.
- `/health/storage`: backend local no persistente, uploads bloqueados. POST sintético de upload: 503 sin archivo.
- `/privacidad`: 503, no-store, noindex. Portada noindex y sitemap 404; log `public_indexing: ready=False`.
- Prueba manual sintética iniciada: caso ambiguo y caso anterior a vigencia sectorial escalan a revisión humana; un caso posterior avanzó por diagnóstico, acción, respuesta favorable, verificación y reentrada. Se detectó una incidencia P1 de cierre parcial.

Blockers:
No congelar todavía la beta interna: incidencia P1 de cierre parcial abierta y recorrido A–H/matriz de 26 familias incompletos. Para datos reales siguen bloqueados ciclo de vida durable de PostgreSQL, almacenamiento documental persistente e información de privacidad revisada.

Cost blockers:
Datastore durable y proveedor de almacenamiento persistente definitivos pueden requerir contratación; no activar sin autorización.

External/user decisions needed:
Datos empresariales reales y revisión formal de privacidad; elección y autorización de proveedores o planes con coste. Ninguna es necesaria para este arreglo sintético.

Next executable task:
CODEX corrige y prueba el cierre parcial descrito arriba. WORK revisa el PR, integra si queda verde y vuelve a ejecutar el recorrido manual afectado antes de seguir la matriz adversarial.
