# Runbook de beta interna sintética de MECORRESPONDE

## Alcance

Este runbook sirve para probar manualmente el Motor de Resolución desplegado antes de cualquier beta con datos reales.

**NO usar datos personales, documentos, emails, números de contrato, facturas, referencias, nombres o casos reales.**
Todos los importes, fechas, empresas, referencias y textos introducidos durante estas pruebas deben ser ficticios.

La beta interna sintética valida funcionamiento y recorrido de producto. No elimina los bloqueantes separados para datos reales: ciclo de vida operativo de la base de datos, almacenamiento documental persistente e información de privacidad. Tampoco habilita por sí sola una beta pública ni la indexación SEO.

## Preflight del despliegue

1. Abrir `/health` y comprobar `status=ok`.
2. Abrir `/health/persistence` y comprobar PostgreSQL persistente.
3. Abrir `/health/storage`. Para esta fase es correcto que uploads estén bloqueados mientras no exista almacenamiento documental persistente.
4. Confirmar que la aplicación pública sigue con `noindex`.
5. En el backoffice, comprobar el cockpit de readiness y que no haya bloqueantes `INTERNAL_BETA_BLOCKER` en el entorno desplegado.

Si falla cualquiera de los puntos 1, 2 o 5, detener la prueba y registrar el defecto. No compensarlo manualmente dentro del expediente.

## Regla de prueba

Cada escenario se ejecuta desde un expediente nuevo salvo que el escenario pruebe expresamente reentrada. No se corrigen estados directamente en base de datos. La prueba debe usar las mismas superficies que usaría el producto: preguntas guiadas, diagnóstico, acción, envío, respuesta, outcome y backoffice cuando corresponda.

Registrar para cada escenario:

- fecha/hora de prueba;
- commit LIVE de Render;
- navegador/dispositivo;
- familia detectada;
- estado inicial y final;
- acción corriente;
- resultado esperado/observado;
- captura o texto del error si existe;
- severidad del defecto.

## Escenario A — recorrido completo con resolución

Usar un caso ficticio de facturación eléctrica incorrecta que el Motor pueda clasificar como E02-A.

Comprobar, en orden:

1. intake y preguntas guiadas;
2. diagnóstico con hechos ficticios;
3. importe mostrado coherente con los importes ficticios introducidos;
4. preparación de la acción solo cuando la acción corriente lo permite;
5. registro ficticio de envío;
6. estado `WAITING_RESPONSE`;
7. respuesta empresarial ficticia favorable;
8. estado `RESOLVED_PENDING_EXECUTION`;
9. verificación ficticia del cumplimiento;
10. si la respuesta promete corrección y devolución, registrar primero solo la corrección y la devolución como pendiente: conservar `RESOLVED_PENDING_EXECUTION` y `VERIFY_EXECUTION` abierta, incluso con 0 € recuperados;
11. confirmar después, con datos sintéticos, que no queda ningún compromiso material pendiente y comprobar `RESOLVED`;
12. timeline y dossier conservan las fechas ficticias introducidas como fechas de calendario, separadas de timestamps técnicos;
13. tras refrescar o volver mediante `#case=<uuid>`, el expediente sigue en el mismo estado.

**PASS:** no hay saltos de fase, reclamaciones duplicadas, preguntas antiguas ni acciones abiertas después de la resolución.

## Escenario B — conclusión sin acción pendiente

Crear un caso ficticio cuyos hechos lleven a una conclusión informativa del Motor, por ejemplo una factura ficticia que no tenga sobrecobro.

**PASS:**

- el expediente conserva el diagnóstico;
- la acción informativa aparece completada, no OPEN;
- `current_action_id` no simula trabajo pendiente;
- la interfaz indica que no hay acción adicional con los hechos actuales;
- si se cambia después un hecho ficticio material, el diagnóstico anterior se invalida y el expediente vuelve a intake para reanalizar.

## Escenario C — espera temporal

Usar un caso ficticio que produzca una acción `WAIT_*`.

**PASS:**

- antes del hito, “Comprobar de nuevo” devuelve conflicto sin mutar expediente;
- al alcanzar el hito simulado por el escenario automatizado correspondiente, la reanudación vuelve a ejecutar el Motor;
- si el reanálisis falla, la espera anterior continúa OPEN y el expediente no queda huérfano.

La prueba manual no debe inventar ni adelantar fechas legales para forzar el hito.

## Escenario D — seguimiento externo

Probar al menos:

- C02 `MONITOR_CONFORMITY`;
- E06 `CHECK_BILL_AGAINST_REAL_READING`.

**PASS:** la UI ofrece la pregunta de seguimiento adecuada y una respuesta nueva produce un nuevo snapshot; no obliga a crear un caso desde cero.

## Escenario E — respuesta no reconocida y revisión humana

Desde una reclamación ficticia ya enviada, registrar una respuesta empresarial sintética que el analizador no pueda resolver de forma segura.

**PASS:**

- el Motor no inventa una conclusión;
- el caso entra en `HUMAN_REVIEW`;
- no puede completarse desde la ruta de propietario del caso;
- el backoffice muestra hechos, comunicaciones, outcome si existe y contexto normalizado;
- una revisión estructurada siempre reanaliza con reglas del Motor;
- una nota libre no puede sustituir el reanálisis estructurado.

## Escenario F — respuesta desfavorable sin bucle de reclamación inicial

Usar una respuesta ficticia que mantenga una controversia después de una reclamación enviada.

**PASS:**

- el Motor no vuelve a generar una segunda reclamación inicial idéntica;
- el caso deriva a la revisión/escalado que corresponda;
- si se requiere handoff profesional, el dossier queda preparado sin seleccionar automáticamente organismo, plazo, vía jurídica ni probabilidad de éxito.

## Escenario G — cuenta, reentrada y ownership

Con un email completamente ficticio de prueba:

1. crear expediente anónimo;
2. crear cuenta;
3. reclamar/guardar el expediente;
4. cerrar sesión;
5. volver a entrar;
6. recuperar el expediente desde la cuenta.

**PASS:**

- el token anónimo deja de otorgar acceso después de reclamar el expediente;
- solo el propietario autenticado puede recuperarlo;
- estado, decisión y acción se conservan;
- exportación contiene solo datos de esa cuenta;
- sesiones revocadas dejan de servir.

No probar recuperación de contraseña o verificación de email como “operativas” mientras no exista proveedor transaccional verificado.

## Escenario H — cierre terminal

Probar un expediente `RESOLVED` y, cuando exista un fixture histórico, `CLOSED_UNSUPPORTED`.

**PASS:**

- facts, charges, diagnosis, preparación y confirmación documental no reabren el caso;
- no se pueden añadir documentos nuevos;
- la documentación se muestra en solo lectura;
- timeline, dossier, handoff y exportación siguen siendo consultables.

## Matriz de familias

Además de los escenarios anteriores, recorrer el intake y el diagnóstico de todas las familias de `backend/app/family_manifest.py`. Contrastar la lista con el manifiesto y el recuento de `/health` antes de empezar; si difieren, detenerse y actualizar la matriz. Lista vigente:

- A01;
- B01, B02, B03;
- C01, C02, C03, C04, C05;
- E01, E02-A, E02-B, E03, E04-A, E04-B, E05, E06, E07;
- R01;
- S01, S02;
- T01, T02;
- V01, V02, V03.

La prueba manual no sustituye la matriz automática de CI. Su objetivo es detectar problemas de comprensión, navegación, reentrada y controles visibles que una prueba de API no percibe.

## Severidad de defectos

**P0 — bloquear beta interna:** pérdida/mezcla de expedientes, acceso cruzado, conclusión jurídica sin evidencia, corrupción de estado, imposibilidad general de completar el recorrido.

**P1 — corregir antes de ampliar testers:** dead-end, acción incorrecta, fase contradictoria, dato confirmado que se pierde, reentrada que obliga a empezar de cero, control visible que el backend siempre rechaza.

**P2 — corregir en la iteración:** copy confuso, orden visual, fricción o información secundaria que no bloquea el recorrido.

## Criterio de salida

La beta interna sintética puede considerarse superada cuando:

- preflight desplegado está verde;
- ningún escenario A–H tiene P0/P1 abierto;
- la matriz de todas las familias registradas no presenta dead-ends visibles;
- refresh, login/reentry y timeline preservan el lifecycle;
- no se han utilizado datos reales.

Pasar a una beta cerrada con datos reales sigue prohibido mientras el cockpit mantenga bloqueantes `BETA_BLOCKER`.
