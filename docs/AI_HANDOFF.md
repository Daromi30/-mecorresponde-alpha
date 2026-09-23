# MECORRESPONDE AI HANDOFF

Last updated:
2026-09-23

Main SHA:
8279211c5eec1a02fb8d87d7db64ca2e4996dda8

Render LIVE SHA (public `/health` verification):
8279211c5eec1a02fb8d87d7db64ca2e4996dda8

Current milestone:
Beta interna sintética en ejecución. La CI de `main` está verde y hay evidencia visual end-to-end favorable/parcial/cierre para E04-B y E02-A, pero A–H y la inspección visual dirigida de las 26 familias no están completos. No congelar ni declarar superada la beta.

Active owner:
WORK

Active task:
Revisar/integrar PR de beta reentry visual guard y repetir C02/E02-A visualmente.

Base SHA:
8279211c5eec1a02fb8d87d7db64ca2e4996dda8

Branch:
fix/beta-reentry-visual-guard

Objective:
Los dos P1 de reentrada tienen corrección técnica en PR #212. WORK revisa la integración y repite los recorridos C02/E02-A visualmente; la beta no está completada.

Completed:
La UI usa únicamente `current_decision_id` para presentar el diagnóstico vigente y limpia tarjetas obsoletas en refresh/reentrada. E02-A informativo ofrece «Corregir datos» para el importe debido existente; la API reutiliza `/facts` con validación acotada, invalida la decisión, conserva historial/auditoría y permite reanalizar 100/80 como 20 € reclamables sin nuevo expediente.

Root causes:
`index.html` y `case_next_step.js` tomaban `decisions[0]` como vigente aunque el backend hubiera anulado `current_decision_id`; refresh tampoco ocultaba el diagnóstico anterior. El hecho E02-A era corregible por API, pero la conclusión sin acción no tenía un control visible. La ruta genérica de hechos carecía de un contrato específico de corrección acotada/idempotente.

Regression coverage:
Pruebas de C02/intake/refresh/reentrada; decisión A histórica frente a B vigente, ID nulo e inválido; conclusión E02-A 100/100, corrección 80, nueva decisión de 20 €; mismo case ID, rechazo de campo/tipo/estado/evidencia/ID incoherente y reenvío sin eventos duplicados. Pruebas UI/JS y lifecycle existentes conservadas. Pase backend completo Windows: 672 verdes y 1 fallo ambiental POSIX `0600` sobre NTFS; el pase final de CI Linux se consigna abajo.

Additional same-domain fixes:
El progreso, la tarjeta de reclamación preparada y las tarjetas de respuesta/resultado ya no usan una decisión o acción histórica como vigente si falta la decisión actual. La guía «Qué hago ahora» falla cerrado en fases accionables con `current_decision_id` incoherente.

Follow-up findings:
P2 previo: la base jurídica desplegable aún expone IDs/resultados internos; no se alteraron reglas, fuentes ni contenido jurídico. La corrección visible nueva está acotada al importe debido E02-A de una conclusión informativa sin acción; otros campos/familias requieren diseño propio, no edición arbitraria.

Acceptance criteria:

1. En C02 `MONITOR_CONFORMITY`, tras contestar que reapareció el defecto, la pantalla deja de mostrar el diagnóstico bajo anterior y pregunta por el defecto; lo mismo tras refrescar. El siguiente diagnóstico nuevo solo se muestra después de completar hechos y reanalizar.
2. La vista de siguiente paso y cualquier módulo que lea `decisions[0]` seleccionan por `current_decision_id`; si no existe decisión vigente, no muestran recomendaciones, importes, acciones ni fuentes históricas como actuales. El historial puede consultarse si se etiqueta inequívocamente como histórico.
3. En E02-A sin sobrecobro (100 € facturados, 100 € debidos), existe un control visible y comprensible para corregir un hecho ya registrado. Cambiar el importe debido a 80 € mediante la UI invalida el diagnóstico anterior, vuelve a intake y permite calcular 20 € reclamables sin crear un expediente nuevo.
4. La corrección valida tipos y campos admitidos, no permite alterar casos terminales ni saltar controles de evidencia, conserva trazabilidad y mantiene respuestas fail-closed ante errores. No se habilitan uploads reales ni indexación pública.
5. Pruebas de regresión para reentrada C02, conclusión sin acción E02-A, decisión vigente frente a historial y recarga/navegación; suite y compilación pertinentes verdes. Documentar cualquier escenario no cubierto, sin confundir prueba API con prueba visual.

Tests:
`backend/tests/test_c02_monitor_followup.py`, `backend/tests/test_informational_action_completion.py`, pruebas de UI existentes para `index.html`, `case_next_step.js` y `case_progress.js`; añadir regresiones específicas. Ejecutar la batería backend y compilación/validación estática aplicable. En Windows hay tres límites ambientales conocidos: dos tests PostgreSQL sin base efímera y una aserción POSIX de permisos sobre NTFS; la CI Linux de PR decide el verde de integración. No afirmar que una suite local con esos límites está totalmente verde.

Do not touch:
Reglas jurídicas, fuentes, importes del Motor, esquema/migraciones destructivas, secretos, planes/costes, datos reales, uploads reales, almacenamiento documental, indexación pública, privacidad fail-closed ni configuración de producción. No hacer merge ni deploy manual para este handoff. Datos empresariales y jurídicos reales quedan pendientes; no inventarlos.

PR:
[#212](https://github.com/Daromi30/-mecorresponde-alpha/pull/212) abierto contra `main`; no fusionado. PR #211 `MERGED` en el `main` de arriba.

CI:
Los cuatro checks obligatorios del PR #212 (`legal-engine-regression`, `postgres-backup-restore`, `postgres-persistence`, `postgres-migrations`) finalizaron `SUCCESS` en `68857db`, que incluye implementación, guardas UI y handoff. Consultar los checks del último SHA del PR antes de integrar. El `main` base conserva checks verdes.

A–H progress:
A: PASS visual sintético E02-A, incluyendo corrección parcial, devolución pendiente, cierre y recarga. B: conclusión informativa visible, pero corrección de hecho bloqueada por P1 de UI. C: pendiente visual. D: C02 seguimiento reproduce P1 de decisión obsoleta; E06 pendiente visual. E: revisión humana parcial, sin flujo estructurado completo. F: pendiente visual. G: pendiente visual de cuenta/reentrada. H: resolución y solo lectura verificadas para E02-A/E04-B; mutaciones terminales y `CLOSED_UNSUPPORTED` no recorridos completamente en UI.

26-family matrix:
26 familias registradas y verificadas por cobertura automatizada de manifest, preguntas, diagnóstico, procedencia jurídica, acción, respuesta y resultado; CI verde. Las 26 guías eran visibles desde la portada, pero solo E02-A se inspeccionó visualmente en detalle y C02/E04-B se recorrieron manualmente. No declarar matriz visual completa ni rutas no soportadas comprobadas manualmente para todas.

Open P0:
Ninguno demostrado; la cobertura manual pendiente impide afirmar ausencia absoluta.

Open P1:
Los dos P1 reproducidos tienen corrección técnica en PR #212, todavía pendiente de integración y repetición visual LIVE por WORK. Evidencias originales en `docs/internal-beta-visual-evidence-2026-09-23.md`; no declarar cierre visual desde Codex.

P2/P3:
Base jurídica desplegable todavía expone IDs/resultados internos sin explicación humana; el borrador de acción sí enlaza fuente oficial. Etiqueta «¿Me compensa?» y campos de fecha se corrigieron con PR #211.

Visual QA:
Parcial, no bloqueada por herramienta. El navegador permitió probar LIVE; el estado de sus pestañas no se conserva entre tareas. Render MCP pidió elegir workspace antes de consultar registro de deploy y logs, y no se ha confirmado esa selección. No extrapolar `runtime_revision` y endpoints HTTP a verificación de logs de arranque.

External/user decisions needed:
Para datos reales: información empresarial y privacidad formalmente revisada, recuperación/continuidad operativa durable de PostgreSQL y almacenamiento documental persistente. No inventar valores ni activar servicios de pago. La elección de workspace Render sigue pendiente para consultar directamente deploy/logs.

NEXT_EXECUTABLE_TASK:
WORK revisa PR #212 y, si procede, integra con checks obligatorios verdes; verifica LIVE y repite visualmente C02/E02-A. Después continúa C/E/F/G/H y la matriz visual dirigida. No declarar beta lista mientras haya P1 visual pendiente o huecos A–H.

WORK READY
