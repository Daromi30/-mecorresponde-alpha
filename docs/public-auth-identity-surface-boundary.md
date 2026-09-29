# Frontera pública de identidad durante la demo sintética

Estado: análisis de WORK posterior a #228 (2026-09-29). **No implementado, no autoriza beta real ni modifica cuentas existentes.** El cierre de la entrada libre de `/api/cases` no abarca `/api/auth`.

## Hallazgo verificable y decisión de producto propuesta

`POST /api/auth/register` acepta email y contraseña y crea `User` más sesión aunque `/` y `/demo/` ya no ofrezcan cuentas. Es una vía pública directa de nueva captura de datos que la demo ficticia no necesita. Propuesta: desactivar nuevas altas públicas mediante un interlock de aplicación cerrado por defecto y no solo ocultando la UI. Una apertura futura necesitaría decisión y revisión explícitas del carril real. No borrar ni migrar cuentas históricas.

La frase “el sitio no puede recibir datos personales” sería falsa mientras se mantengan rutas de identidad accesibles y cuentas previas. Preservar el acceso de esas cuentas para consultar, exportar y borrar sus datos implica seguir procesando sus credenciales; es una excepción delimitada, no una demo anónima absolutamente libre de PII. WORK debe aprobar expresamente esta excepción antes de entregar ingeniería.

## Inventario de rutas y tratamiento propuesto

| Ruta | Estado observado | Frontera propuesta |
| --- | --- | --- |
| `POST /register` | Alta pública de `User` y sesión; email persistido | Denegar nuevas altas antes de crear `User`, sesión o auditoría con payload. No depender de frontend ni de un simple env var. |
| `POST /login`, `POST /logout`, `GET /me` | Login directo y mantenimiento de sesión de cuentas existentes | Conservar para cuentas históricas, sin habilitar alta; respuesta no enumerante para email desconocido y revisión del throttling de intentos desconocidos. |
| Verificación de email | Solicitud autenticada y confirmación por token; envío actualmente no operativo | Mantener indisponible el envío mientras el proveedor no sea operativo; no usar esta ruta como registro alternativo. Tokens históricos válidos requieren política explícita antes de un cambio. |
| Reset de contraseña | Solicitud por email actualmente 503 antes del throttle; confirmación por token | Mantener fail-closed para envío; preservar mecanismo de confirmación de tokens existentes. Si se habilita email más adelante, revisar por separado enumeración, persistencia y derechos de cuentas previas. |
| Cambio de contraseña y sesiones | Requieren cuenta autenticada | Conservar para seguridad de cuentas existentes, sin crear una vía de alta pública. |
| `GET /cases`, `GET /export`, `DELETE /account` | Requieren sesión; borrado pide contraseña | Preservar acceso/exportación/supresión de cuentas históricas. No revocar masivamente sesiones ni eliminar cuentas como parte del cierre. |

El throttle actual usa SHA-256 del email normalizado como clave persistente. No guarda el email en claro, pero las solicitudes de login de emails inexistentes pueden crear una fila digest. Revisar si esa persistencia es necesaria para desconocidos y cómo conservar la protección contra fuerza bruta sin convertir el cierre en una vía de enumeración. No afirmar que un hash de email equivale a ausencia de dato personal.

## Criterios para el bloque técnico separado

1. API directa de registro, no solo UI, rechaza antes de persistir email, `User`, sesión o caso; comportamiento genérico y sin texto recibido en logs/auditoría. Ningún header, query, variable suelta o endpoint público debe activar el bypass.
2. Una cuenta histórica de prueba sintética puede seguir haciendo login, gestionar sesiones, acceder a sus casos, exportar y borrar su cuenta. Sin destrucción ni reclasificación de cuentas/casos existentes.
3. Email inexistente y credenciales incorrectas mantienen respuesta segura/no enumerante; el diseño documenta y prueba el throttle, incluido el destino de los digests de emails desconocidos.
4. Verificación y reset permanecen no operativos para envío hasta decisión expresa; confirmación de tokens ya emitidos no se rompe sin plan de transición. No se activa email real.
5. `PRIVATE_REAL_BETA` sigue OFF, las 26 familias del Motor intactas, uploads y privacidad fail-closed, indexación apagada. Sin migración destructiva, secretos, datos reales ni coste.
6. Suite de API directa, regresión de identidad/cuentas históricas, CI PostgreSQL y smoke LIVE con identidades exclusivamente ficticias antes de cualquier merge ordinario.

NEXT OWNER: **WORK** decide la excepción limitada de login para cuentas existentes y cierra los criterios de no persistencia/enumeración. Después, una implementación aislada puede pasar a CODEX en rama nueva desde el `main` vigente. No mezclar con #228.
