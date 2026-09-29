# Backoffice: identidad y atribución individual mínima

Estado 2026-09-29: diseño para el siguiente PR, **no implementado** y no habilita expedientes reales. Solo datos sintéticos; coste cero. La beta real permanece `NOT READY` incluso cuando este bloque esté técnicamente terminado.

## Evidencia en código

- `admin_auth.require_admin` acepta `ADMIN_API_TOKEN` compartido (Bearer o `X-Admin-Token`) y devuelve 401/503 según configuración. No identifica a una persona. Desde #224 revalida la elegibilidad de mutaciones de casos `PRIVATE_REAL_BETA`, pero no atribuye al operador.
- `HumanReview.assigned_to` es una cadena suministrada por `POST /api/admin/reviews/{id}/assign`; la auditoría guarda esa cadena, no un actor autenticado. `reviewer_decision` también viene del cliente. `AuditEvent` guarda `case_id`, tipo, JSON y fecha; carece de columna de identidad de actor.
- `GET /api/admin/reviews`, `/cases/{id}` y `/cases/{id}/handoff` muestran información de expediente detrás del token; la UI envía el token en memoria como Bearer, sin sesión individual. Hay acciones de asignación, reclasificación, resolución estructurada y escalado profesional.
- Existe infraestructura de contraseñas PBKDF2, sesiones con hash/revocación y throttling para **cuentas de usuario**. Esas cuentas son auto-registrables; no otorgan rol de revisor y no deben convertirse implícitamente en administradores. El middleware bloquea `Origin` no confiable y `Sec-Fetch-Site: cross-site` para mutaciones; esto no sustituye autenticación/autorización.

## Amenazas que sí debe cerrar el bloque

1. Token compartido filtrado o prestado: cualquier uso aparece como la misma identidad. Debe ser imposible usarlo como actor suficiente para leer o alterar un caso privado real una vez exista ese carril.
2. `assigned_to` arbitrario: un cliente puede escribir el nombre de otro revisor; se necesita ID de actor derivado de la sesión servidor-side y separar asignatario del ejecutor.
3. Lecturas sin rastro: cola, detalle, handoff/exportación pueden exponer hechos y terceros sin constancia de quién los consultó.
4. Sesión robada/no revocada, intento de fuerza bruta y escalada de revisor a administrador. Separar identidades/sesiones de revisores de las cuentas de reclamante y aplicar mínimo privilegio.
5. Auditoría alterable o con secretos/datos del caso: los eventos deben ser atribuibles, acotados y sin duplicar PII. No inferir que una tabla de eventos equivale a inmutabilidad forense absoluta.

## Arquitectura mínima propuesta para CODEX, sujeta a revisión en implementación

- Principal `Reviewer` persistente con ID opaco, identificador de acceso único, credencial con hash, estado activo/revocado y rol mínimo (`reviewer`, `operator`); provisioning solo por bootstrap autorizado, sin auto-registro público ni correo. No reutilizar una sesión de `User` como privilegio administrativo. Una credencial inicial se entrega por canal operativo aún por definir, **no** en código/logs/email actual.
- Sesión de backoffice separada, cookie HttpOnly/Secure en Render/SameSite Strict, token aleatorio cuyo digest se persiste, expiración corta y revocación individual/global al deshabilitar revisor. Login con respuesta no enumerante y throttling; logout y rotación de contraseña revocan sesiones.
- Dependencia de autorización única para todo `/api/admin`: bootstrap token puede administrar únicamente provisioning/operación sintética expresamente definida. Acceso a **expediente privado** exige sesión individual activa y rol apropiado; el token compartido no puede ser bypass. Decidir por endpoint qué lectura o mutación es de caso frente a métrica agregada, y probar rutas de `review_id` y `case_id`.
- Eventos servidor-side con `actor_reviewer_id`, `action`, `case_id` o identificador de consulta de cola, resultado y timestamp: autenticación, acceso a cola, apertura de detalle, descarga/handoff, asignación, reanálisis estructurado, reclasificación, escalado y denegaciones relevantes. Nunca guardar contraseña, token, cabeceras Authorization, raw intake ni todo el payload de expediente. Registrar la lectura **antes o de manera transaccional con** entregar datos privados; si falla el registro, fail-closed para la lectura privada.
- `HumanReview.assigned_to` puede conservarse para compatibilidad visual sintética, pero en casos privados la asignación se debe referir a un revisor existente y la identidad de quien ejecuta la acción se obtiene siempre de sesión. Auditar reasignaciones y revocaciones. No usar el campo de texto como prueba de identidad.
- UI: login/logout de revisor sin token compartido en cada petición de caso privado; estado de sesión visible y error claro al revocar. Evitar guardar material sensible en `localStorage` o URL. Probar protección Origin/Sec-Fetch-Site y ausencia de cache de respuestas sensibles.
- Migración aditiva; ninguna cuenta de cliente gana rol por defecto, ningún evento histórico se rellena con identidades inventadas. El bootstrap administrativo vigente se conserva para transición sintética, pero su alcance a casos privados queda denegado.

## Criterios de aceptación y pruebas sugeridas

Con datos ficticios: dos revisores distintos muestran actor diferente en lecturas/escrituras; revisor deshabilitado pierde acceso inmediato; token compartido solo no ve/muta caso privado simulado; claimant cookie no abre backoffice; `assigned_to` falsificado no cambia actor; rol `reviewer` no puede provisionar ni cambiar privilegios; login throttled, sesión expira y logout/revocación surten efecto; errores no enumeran usuarios; logs/auditoría no contienen credenciales ni intake; los flujos sintéticos y CI PostgreSQL siguen verdes. Prueba con rutas de cola, detalle, handoff y las cuatro acciones de revisión, más migración upgrade/downgrade aditiva. No usar personas ni emails reales.

## Pendiente fuera de este PR

MFA: evaluar durante revisión de riesgos; no declararlo resuelto por tener contraseña o cookie. Operación de altas/bajas, recuperación de credenciales y segundo factor requerirán procedimiento aprobado antes de datos reales. También siguen bloqueados privacidad/identidad empresarial, continuidad y recuperación de base, documentos, revisión jurídica, el texto libre público sintético, email y la activación del interlock privado. No contratar IAM ni proveedor de correo para este bloque.
