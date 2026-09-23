# Beta interna sintética — evidencia visual parcial (23-09-2026)

Esta prueba se hizo en un navegador sobre Render LIVE `25f10b4566e1b8d809e3660e69528c0bae6454a0`, no únicamente por API. Todos los hechos, fechas, importes, nombres y referencias introducidos fueron ficticios. No se subieron documentos ni se contactó con terceros. El registro de envío y respuesta fue una simulación dentro del expediente.

## Preflight

- GitHub `main` y Render LIVE coincidían en el SHA completo anterior. El deploy automático `dep-dapm753m8hqs73ag34rg` estaba `live`; Database Migrations y MECORRESPONDE CI estaban verdes para ese SHA.
- `/health`: `status=ok`, `families=26`, `runtime_revision` igual a LIVE.
- El preflight desplegado anterior de almacenamiento, privacidad e indexación sigue documentado en `internal-beta-manual-evidence-2026-09-23.md`. No se infiere de la pantalla una nueva auditoría de esos endpoints o del backoffice.

## Recorrido visual efectuado

En el navegador integrado se abrió la portada: aviso visible de pruebas sintéticas y enlaces a 26 guías, agrupadas por vertical. Se abrió la guía E02-A: título y explicación legibles, CTA «Analizar mi caso», referencia oficial y cautela expresa de no decidir automáticamente. Desde esa CTA se abrió un expediente E02-A ficticio con factura de 150 € y cantidad debida de 100 €. Las preguntas guiadas pidieron fecha y ambos importes; el diagnóstico mostró base alta y 50 € reclamables. Sin embargo, no mostró ningún siguiente paso. Por ello el escenario A no se puede dar por completado en LIVE.

Un relato ad hoc ambiguo sobre una factura de luz entró en `HUMAN_REVIEW` en vez de producir una conclusión automática. Se observó el bloqueo de uploads. La clasificación concreta de ese relato no se considera error sin una revisión de los hechos que el Motor interpretó.

El recorrido completo se hizo con un segundo expediente E04-B ficticio, `4396f1fa-7e1e-47cd-99c9-fe6cde17d40a`:

1. Desde el ejemplo de mantenimiento cobrado tras cambiar de compañía, la UI pidió fecha de fin de suministro (`2026-06-03`), identidad del servicio (`Servicio Ficticio`), contratación original, vinculación al suministro y ausencia de solicitud de conservarlo.
2. Se introdujo un cargo ficticio de 8,99 €, fecha `2026-07-04`, periodo `2026-06-04` a `2026-07-03`, confirmando que sus datos podían verificarse en un documento ficticio en posesión de la persona. La UI mostró diagnóstico `HIGH`, importe reclamable 8,99 € y acción de reclamación. El borrador mostró una fuente oficial verificable.
3. Se registró un envío simulado mediante `web_form`, fecha `2026-09-23`, referencia `PRUEBA_INTERNA_SINTETICA_VISUAL_20260923`; no hubo envío externo.
4. Se registró una respuesta empresarial simulada favorable, con cancelación y devolución prometidas, fecha `2026-09-23`, referencia `RESPUESTA_SINTETICA_20260923`. El caso pasó a «Aceptado · pendiente de cumplir».
5. Se confirmó solo la cancelación: recuperado 0 €, devolución pendiente. La UI conservó «Aceptado · pendiente de cumplir», mostró el compromiso pendiente y añadió un evento parcial. Tras recarga persistieron los datos y el estado.
6. Se confirmó la devolución ficticia de 8,99 € y que no quedaban compromisos materiales. La UI pasó a «Resuelto», mostró el canal e importe, la documentación en solo lectura y la secuencia parcial → resolución una sola vez. Tras recarga el cierre seguía persistido.

Resultado: PASS visual para el lifecycle favorable, cumplimiento parcial, cierre y reentrada anónima de este caso E04-B. No equivale a A–H completo ni a 26 familias recorridas manualmente.

## Cobertura de la matriz y límites

Las pruebas automatizadas `test_beta_acceptance_matrix.py`, `test_guided_question_acceptance.py`, `test_all_family_response_loop.py` y `test_all_claim_provenance.py` recorren las 26 familias registradas para intake/diagnóstico, preguntas guiadas, acción y fuente jurídica, respuesta favorable y resolución; la respuesta parcial no duplica la reclamación inicial. Las rutas de alcance no admitido no están cubiertas manualmente para las 26 familias: existe prueba automatizada específica para cinco familias de compras fuera del ámbito de consumo. Las 26 páginas de guía se verificaron como enlaces visibles en la portada, pero solo E02-A se inspeccionó visualmente en detalle.

Estado del runbook manual: A parcial y bloqueado en LIVE tras diagnóstico E02-A; B, C, D, F y G pendientes; E parcial (se observó `HUMAN_REVIEW` de un relato ambiguo, no el flujo completo tras respuesta); H parcial (cierre y lectura, no todas las mutaciones terminales ni `CLOSED_UNSUPPORTED`). No hay evidencia para afirmar que toda la matriz visual esté superada.

## Hallazgos y corrección preparada

- P2 corregido en la rama de este documento: «¿Me compensa?» mostraba `YES_IF_LOW_COST` en el diagnóstico LIVE. Se añadieron etiquetas legibles para todos los códigos existentes y un fallback conservador para los desconocidos.
- P2 corregido en la rama de este documento: el formulario de cargos mostraba tres controles de fecha sin etiquetas visibles. Ahora distingue fecha del cargo, inicio y fin del periodo; se conservan los nombres y semántica de la API.
- P1 corregido en la rama de este documento, pendiente de CI y despliegue: las guías enlazan a `/demo/`, que servía el HTML estático sin el cargador de módulos seguros. El Motor diagnosticó E02-A correctamente, pero no apareció la acción «Qué hago ahora» ni el botón para preparar la reclamación. La raíz `/` sí cargaba esos módulos, ocultando el defecto en la primera prueba E04-B. `/demo/` y `/demo/index.html` se sirven ahora con el mismo cargador y la primera capa de privacidad fail-closed, conservando `noindex`.
- P2 pendiente: «Ver base jurídica aplicada» muestra identificadores y resultados internos (`ELEC_ADDON_END_WITH_SUPPLY / APPLIES`) en vez de explicación de cara al usuario. El borrador sí muestra una fuente oficial, pero la sección de diagnóstico necesita copy contextual revisado antes de usarla como explicación jurídica pública.
- P0: ninguno nuevo demostrado en esta prueba parcial. Tampoco se declara su ausencia en los escenarios sin ejecutar.

La tanda dirigida tras los dos primeros cambios: 26 tests aprobados. Tras el arreglo P1, la tanda de navegación, privacidad, cargador y matriz de familias: 33 aprobados. La suite amplia local previa dio 668 aprobados y tres fallos ambientales: dos tests de integración PostgreSQL ejecutados con `sqlite:///:memory:` por falta de base efímera local, y la aserción POSIX `0600` sobre NTFS. No se sustituyen por una afirmación de suite local totalmente verde; CI Linux del PR debe decidir la integración.

## Siguiente bloque ejecutable

Pasar esta corrección por CI y verificar la interfaz tras auto-deploy si se integra. Después ejecutar los escenarios manuales restantes A–H con datos sintéticos, empezando por E02-A, cuenta ficticia/reentrada y seguimiento externo, y recorrer la matriz visual de las 26 familias para descartar dead-ends visibles. Mantener prohibidos datos reales, uploads, indexación pública y cualquier decisión jurídica o empresarial inventada.

## Continuación después de PR #211

PR #211 se fusionó en `main` como `8279211c5eec1a02fb8d87d7db64ca2e4996dda8`. `MECORRESPONDE CI` y `Database Migrations` concluyeron correctamente en ese SHA. En la comprobación pública posterior, `/health` devolvió `status=ok`, `families=26` y `runtime_revision` idéntico a `main`. `/health/persistence` indicó PostgreSQL persistente; `/health/storage`, almacenamiento local no persistente y uploads bloqueados. `/privacidad` continuó en 503 fail-closed y `noindex`; el sitemap no se publicó. La URL `/demo/` cargó la interfaz enriquecida y conservó `noindex`. El registro del deploy y los logs de Render no se volvieron a inspeccionar directamente porque la integración MCP exigió elegir una cuenta de trabajo y esa elección aún no se ha confirmado. No extrapolar la salud HTTP a una auditoría de logs.

En navegador real sobre ese LIVE, se repitió el escenario A entrando desde la guía E02-A. El expediente ficticio `9403f6ed-1d88-4e22-be1a-fafd4652aa0b` pasó de 150 € facturados/100 € debidos a un diagnóstico alto de 50 € reclamables; la acción se pudo preparar y mostró fuente oficial. Se registraron **solo dentro del producto** un envío y respuesta favorables simulados, una corrección parcial con devolución de 50 € pendiente y, tras una recarga que conservó ese pendiente, una devolución ficticia de 50 € y cierre. Una segunda recarga conservó resolución, historial y solo lectura. No se contactó con empresa ni organismo alguno.

Para el escenario B, el expediente ficticio E02-A `2200f950-b729-415e-8ae6-5f110e2670d3` con 100 € facturados y 100 € debidos mostró diagnóstico bajo, 0 € reclamables y «Análisis concluido · no hay una acción adicional». No obstante, la pantalla promete reanálisis si aparece un hecho verificable y no ofrece una forma visible de corregir los hechos existentes después de esa conclusión. La API sí acepta la corrección y anula la decisión anterior (`test_informational_action_completion.py`), pero esto **no equivale** a un recorrido de usuario completado. Clasificación provisional: P1 de reentrada/corrección, pendiente de arreglo y prueba visual.

Para D se probó C02 con el expediente ficticio `f22ff7ac-9880-4abe-9ad9-cfe4a3f320b4`: una lavadora reparada que inicialmente funcionaba produjo `MONITOR_CONFORMITY` y la pregunta visible de seguimiento. Al responder que la falta reapareció, la API devolvió el caso a `INTAKE`, sin decisión ni acción actuales y con la siguiente pregunta sobre el defecto; el comportamiento de backend coincide con `test_c02_monitor_followup.py`. Pero la UI siguió mostrando el diagnóstico bajo antiguo y su razonamiento contrario al nuevo hecho, incluso después de recargar. `refresh()` en `backend/app/static/index.html` dibuja `decisions[0]` sin comprobar `current_decision_id`; `case_next_step.js` también toma la primera decisión histórica. Clasificación: P1 por conclusión obsoleta mostrada como vigente. E06 y el resto de D no se han completado visualmente.

Estado tras esta continuación: A visual PASS con datos sintéticos; B y D parciales con P1 abiertos; E04-B favorable/parcial/cierre PASS en su ruta ya descrita; C, E completo, F y G siguen pendientes; H probado para resolución y recarga, pero no exhaustivamente para todas las mutaciones terminales ni `CLOSED_UNSUPPORTED`. No se ha completado inspección manual visual de las 26 familias. Las pruebas automáticas de las 26 familias y la CI no eliminan estos dos P1 de interfaz.
