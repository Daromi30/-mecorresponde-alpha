# MECORRESPONDE AI HANDOFF

Last updated: 2026-09-23

Main SHA: `a02ec013275877255e7135a8869df60a9f6faf27`

Render LIVE SHA: `a02ec013275877255e7135a8869df60a9f6faf27`

Current milestone: beta interna **sintética**, todavía no apta para congelar. PR #212 fue fusionada; los dos P1 de reentrada principales pasaron la repetición visual, pero se descubrieron un P0 de clasificación de respuesta desfavorable y un P1 residual de calidad del expediente. Los recorridos A–H y 26 expedientes visuales no están completos.

Active owner: CODEX

Base SHA: `a02ec013275877255e7135a8869df60a9f6faf27`

Branch: `fix/response-negation-quality-current`

Objective: corregir de forma conservadora el falso positivo de aceptación ante una respuesta que niega la reclamación y eliminar el uso de decisiones históricas como vigentes en la calidad del expediente. Trabajar solo en esta rama y entregar PR para revisión de WORK; no hacer merge ni deploy manual desde este handoff.

Evidence and root causes:

- En LIVE, una respuesta ficticia «Rechazamos su reclamación y no devolveremos los 50 euros solicitados» para un E02-A pasó a `ACCEPTANCE`, `RESOLVED_PENDING_EXECUTION` y «Verificar cumplimiento». También reproducen `ACCEPTANCE` localmente «No aceptamos su reclamación» y «No procedemos a devolver el importe». `backend/app/engine/gateway.py`, `DeterministicAlphaGateway.analyze_response()`, detecta subcadenas afirmativas antes de la negación. Es P0 para beta por resultado favorable falso. El expediente de prueba fue `3e6d097c-5d28-48d1-bc44-f36a6d6d2285`; no hubo envío externo ni dinero real.
- Tras invalidar `current_decision_id` y volver a `INTAKE`, la tarjeta «Calidad del expediente» sigue diciendo «Diagnóstico disponible» y «Reglas evaluadas en la decisión actual: 1», incluso tras refresh. `backend/app/case_quality.py`, `build_dossier_quality()`, utiliza `decision_rows[0]` como fallback histórico. Se reprodujo visualmente en C02, E02-A y E06. Es P1 residual; las tarjetas principales y de siguiente paso sí ocultaron correctamente el diagnóstico viejo tras PR #212.

Acceptance criteria:

1. Negaciones explícitas de aceptación, devolución, reembolso o ejecución nunca clasifican como `ACCEPTANCE`, incluso con otras palabras positivas en la misma frase. Una respuesta desfavorable clara puede ser `DENIAL`; cualquier caso semánticamente incierto debe ir a `UNKNOWN`/revisión humana. No inferir hechos jurídicos ni promesas de ejecución.
2. La respuesta desfavorable no crea estado favorable, hito de verificación de cumplimiento ni cierre automático. Comprobar ciclo de respuesta y resultado, incluida posible respuesta mixta/parcial; preservar la aceptación auténtica y evitar duplicar reclamación inicial o eventos ante reintento.
3. `build_dossier_quality()` solo computa diagnóstico/reglas de la decisión identificada por `current_decision_id` si existe y pertenece al caso. Con ID nulo o inválido, debe reflejar intake/sin decisión vigente, cero reglas actuales y conservar el historial sin etiquetarlo como actual. Revisar los tres escenarios C02, E02-A y E06, con recarga.
4. Añadir regresiones dirigidas de clasificación afirmativa, negativa, mixta y ambigua; cubrir API/estado, tarjeta de calidad y contratos UI pertinentes. Mantener verdes pruebas completas, compilación y CI obligatoria. Documentar límites ambientales Windows sin presentarlos como verde total.
5. Mantener bloqueados uploads reales, almacenamiento local no persistente, privacidad sin datos empresariales reales e indexación pública. Sin migraciones destructivas, costes, secretos ni datos personales reales.

Tests: ampliar los tests del gateway y ciclo de respuesta (buscar `analyze_response`, `ACCEPTANCE`, `DENIAL`, `VERIFY_EXECUTION`), los de `case_quality.py` y reentrada C02/E02-A/E06. Ejecutar batería backend, pruebas UI/JS y compilación aplicable; comprobar CI en el head del PR antes de cualquier integración. Tras un merge ordinario autorizado y auto-deploy, WORK repetirá en LIVE la negación y la tarjeta de calidad con datos ficticios.

Do not touch: reglas ni fuentes jurídicas, importes del Motor, esquemas/migraciones destructivas, secretos, configuración sensible, servicios o planes de pago, datos reales, uploads reales, almacenamiento documental, indexación pública, privacidad fail-closed ni producción manual. No inventar datos empresariales o jurídicos. No hacer merge a `main` ni disparar deploy manual desde esta tarea.

PR/CI/Render: PR #212 `MERGED`. `main` y LIVE coinciden en el SHA indicado. `MECORRESPONDE CI` y `Database Migrations` de `main` finalizaron `SUCCESS`. Render auto-deploy `dep-daq0p0ugekts73cr42tg` terminó `live` por `new_commit`. `/health` devolvió 200, `status=ok`, `families=26` y revisión exacta; logs de arranque mostraron PostgreSQL persistente, `synthetic_internal_beta_ready=True`, `internal_beta_blockers=none` y ningún error en la ventana revisada. `/health/storage`: local no persistente, uploads bloqueados; `/privacidad`: 503/noindex; sitemap: 404; `/demo/`: noindex. Workspace Render confirmado: `My Workspace`.

A–H progress: A PASS sintético previo; B corrección E02-A PASS salvo calidad P1; C espera pre-hito PASS parcial, sin simular vencimiento; D C02/E06 PASS salvo calidad P1; E respuesta ambigua pasa a revisión humana, backoffice pendiente; F FAIL por falso `ACCEPTANCE` P0; G cuenta/reentrada pendiente (creación por UI requiere confirmación puntual); H resolución y solo lectura parcial previa, sin inspección exhaustiva de mutaciones terminales ni `CLOSED_UNSUPPORTED`.

26-family matrix: cobertura automatizada verde de 26 familias; inspección visual de guías de ocho verticales (energía, telecom, compras, viajes, banca, alquiler, seguros, automoción) y recorridos dirigidos de C01/C02/C04/E02-A/E06. No afirmar 26 expedientes manuales ni beta completa.

P2: códigos internos visibles en base jurídica y copy (`ELEC_OVERBILL_REFUND / APPLIES`, `PRICE REDUCTION REQUIRES PROPORTIONAL VALUATION`, `OUT_OF_SCOPE`). Corregir en bloque separado con copy verificable; no improvisar explicaciones legales. Los datos empresariales y de privacidad formal, continuidad/recuperación durable de PostgreSQL y almacenamiento documental persistente requieren decisión o información real antes de beta con usuarios reales.

Detailed visual evidence: `docs/internal-beta-visual-evidence-2026-09-23.md`.

NEXT_EXECUTABLE_TASK: CODEX implementa y prueba en `fix/response-negation-quality-current` los P0/P1 descritos, abre PR y comunica head SHA, CI y límites. WORK revisa PR, integra solo si está verde y fusionable, verifica auto-deploy/LIVE y repite F y calidad visualmente; después continúa E/G/H y la matriz dirigida. No congelar beta con el P0 abierto.

CODEX READY
