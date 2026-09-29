# Frontera temporal de demo pública sintética cerrada

Estado propuesto (2026-09-29): PR técnica, sin desplegar ni abrir `PRIVATE_REAL_BETA`. Base verificada: `3df57053081a0fce119ce15b7ac72db2d41260d5`. Esta frontera limita el **HTTP público** y no cambia el Motor de Resolución, sus 26 familias ni los tests de sus servicios internos.

## Amenaza y decisión

El intake sintético anterior aceptaba `message` libre y varios endpoints de caso aceptaban strings, objetos y referencias sin restricción de demo. Una persona podía introducir involuntariamente datos propios o de terceros que terminaran en `Case.raw_intake`, `Fact.value_json`, `Communication`, `Evidence`, `HumanReview.context_json`, `AuditEvent`, `AIRun` o logs derivados. Un detector de PII no puede distinguir con fiabilidad hechos jurídicos de datos personales; no es la barrera primaria.

La UI pública actual se sustituye temporalmente por cuatro escenarios ficticios de energía, compras, telecom y alquiler. El navegador solo envía un `scenario_id` opaco y estable. El servidor resuelve narración y hechos predefinidos; llama al Motor real para clasificación, diagnóstico y preparación de acción sintética. No hay caja de texto, cuenta, carga de factura ni formulario de respuesta en esa UI. La antigua página de intake se conserva como referencia de desarrollo, pero ningún entrypoint público la sirve y el fallback estático deniega HTML. Esto **no** convierte el Motor ni el futuro intake real en un catálogo rígido.

## Inventario y guard de escritura

`demo_boundary.enforce_demo_boundary` se instala en todos los routers HTTP bajo `/api/cases`: `cases_v2`, `quality`, `wait_resume`, `account_cases` y `case_deletion`. La creación pública exige un JSON de forma exacta `{"scenario_id":"..."}` y un ID existente; `message`, `mode`, `facts` u otros campos se rechazan antes de `create_case`. El caso queda marcado con `demo_scenario_id` en la migración aditiva `0010_closed_demo_scenarios`. Los casos `SYNTHETIC` históricos tienen `demo_scenario_id=NULL` y quedan de solo lectura para nuevos `POST`/`PUT`/`PATCH` públicos; la eliminación autenticada/capability se mantiene para derechos de supresión. Una sesión de reclamante no salta esta regla. El carril `/api/real-beta/cases` conserva su guard de admisión independiente y apagado.

Para un caso de demo se permiten únicamente `POST /diagnose` y `POST /prepare-claim`, ambos **sin cuerpo**. La frontera niega hechos, cargos, documentos/confirmación de extracción, submission/referencias, respuestas normal/evidenciada, resultados/notas, revisión legacy, reanudación y claim de cuenta. La autorización de acceso al caso y las guardas de fase preexistentes permanecen; algunas rutas legacy ya devuelven 403/409 antes de llegar a la nueva auditoría, pero no persisten el contenido. El endpoint de uploads sigue bloqueado además por su política de almacenamiento. Las rutas de admin/backoffice no son la superficie pública y mantienen la identidad y autorización del PR #226.

Cada rechazo que llega al nuevo guard registra solo `SYNTHETIC_INPUT_REJECTED` con patrón de endpoint y reason code, nunca cuerpo, texto, token, referencia ni identificadores personales. Si la auditoría de rechazo falla, la petición no continúa. Respuestas de error son genéricas. Tests de API directa comprueban que un marcador ficticio rechazado no figura en casos, hechos, comunicaciones, evidencias, revisiones, auditoría ni logs capturados.

## Superficies separadas y límites

- Las APIs de cuenta `/api/auth` siguen sirviendo acceso, exportación y eliminación de cuentas anteriores. La UI de demo ya no las solicita. Son una superficie de identidad **separada** del intake/caso sintético; este PR no inventa una política de cierre o borrado de cuentas existentes. Registrar una cuenta directamente por API todavía es posible y puede guardar email: `FOLLOW_UP_FINDING` de producto/privacidad antes de llamar al sitio entero libre de entrada personal.
- Las rutas de administración sintética protegidas siguen aceptando fixtures flexibles para operación interna; no constituyen un escape público anónimo. Los tests del Motor usan un override explícito de dependencia en `backend/tests/conftest.py`, solo cargado por pytest, para conservar fixtures flexibles. No hay header, variable de entorno ni parámetro HTTP de producción para activarlo.
- Las narraciones y fechas fijas son ejemplos, no hechos de una persona. Su razonamiento puede requerir actualización futura de fuentes/reglas, sin autorizar a abrir entrada libre. No se afirma privacidad integral, revisión jurídica final, storage persistente, continuidad DB ni readiness real por esta PR.

`REAL_BETA_LAUNCH_REVIEW_COMPLETE=False`, `real_beta_enabled="false"` y allowlist vacía por defecto permanecen intactos. No se han creado datos reales, cuenta LIVE, revisor LIVE, proveedor ni coste.
