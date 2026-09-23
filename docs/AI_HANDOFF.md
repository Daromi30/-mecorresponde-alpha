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
CODEX

Base SHA:
8279211c5eec1a02fb8d87d7db64ca2e4996dda8

Branch:
fix/beta-reentry-visual-guard

Objective:
Corregir dos P1 de reentrada en la UI de expedientes: (1) nunca presentar un diagnóstico histórico como vigente cuando `current_decision_id` es nulo o apunta a otra decisión; (2) permitir al usuario corregir de forma segura un hecho material existente desde la conclusión informativa sin acción, de modo que el backend invalide la decisión y vuelva a intake. Conservar historial sin convertirlo en recomendación activa.

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
Ninguna todavía para esta rama. PR #211 `MERGED` en el `main` de arriba.

CI:
`MECORRESPONDE CI` y `Database Migrations` `SUCCESS` sobre `8279211c5eec1a02fb8d87d7db64ca2e4996dda8`. La rama del relevo aún no contiene corrección técnica ni CI propia.

A–H progress:
A: PASS visual sintético E02-A, incluyendo corrección parcial, devolución pendiente, cierre y recarga. B: conclusión informativa visible, pero corrección de hecho bloqueada por P1 de UI. C: pendiente visual. D: C02 seguimiento reproduce P1 de decisión obsoleta; E06 pendiente visual. E: revisión humana parcial, sin flujo estructurado completo. F: pendiente visual. G: pendiente visual de cuenta/reentrada. H: resolución y solo lectura verificadas para E02-A/E04-B; mutaciones terminales y `CLOSED_UNSUPPORTED` no recorridos completamente en UI.

26-family matrix:
26 familias registradas y verificadas por cobertura automatizada de manifest, preguntas, diagnóstico, procedencia jurídica, acción, respuesta y resultado; CI verde. Las 26 guías eran visibles desde la portada, pero solo E02-A se inspeccionó visualmente en detalle y C02/E04-B se recorrieron manualmente. No declarar matriz visual completa ni rutas no soportadas comprobadas manualmente para todas.

Open P0:
Ninguno demostrado; la cobertura manual pendiente impide afirmar ausencia absoluta.

Open P1:
Diagnóstico histórico C02 mostrado como vigente tras cambiar hecho y volver a intake. Reentrada sin control visible para corregir hecho material desde conclusión sin acción E02-A. Reproducciones y evidencias en `docs/internal-beta-visual-evidence-2026-09-23.md`.

P2/P3:
Base jurídica desplegable todavía expone IDs/resultados internos sin explicación humana; el borrador de acción sí enlaza fuente oficial. Etiqueta «¿Me compensa?» y campos de fecha se corrigieron con PR #211.

Visual QA:
Parcial, no bloqueada por herramienta. El navegador permitió probar LIVE; el estado de sus pestañas no se conserva entre tareas. Render MCP pidió elegir workspace antes de consultar registro de deploy y logs, y no se ha confirmado esa selección. No extrapolar `runtime_revision` y endpoints HTTP a verificación de logs de arranque.

External/user decisions needed:
Para datos reales: información empresarial y privacidad formalmente revisada, recuperación/continuidad operativa durable de PostgreSQL y almacenamiento documental persistente. No inventar valores ni activar servicios de pago. La elección de workspace Render sigue pendiente para consultar directamente deploy/logs.

NEXT_EXECUTABLE_TASK:
CODEX implementa y prueba los dos P1 de reentrada de este handoff en la rama indicada. WORK puede avanzar en paralelo el runbook sintético independiente (C, E, F, G, H y matriz visual dirigida) sin tocar esa rama ni declarar beta lista. Tras PR con CI obligatorio verde y revisión sin cambios inesperados, la autorización ordinaria de integración permite merge y auto-deploy, nunca deploy manual; después comparar SHA exacto `main`/LIVE y repetir C02/E02-A en pantalla. No entregar beta interna mientras haya P1 o huecos A–H.

CODEX READY
