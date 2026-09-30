# Protocolo durable de reconciliación documental

Estado: implementación provider-neutral para revisión independiente. **No habilita uploads ni declara storage READY.** Base `main=ca26211b30660dca36a3ec2f3aec996dbe733db1`. Solo pruebas con bytes ficticios; no proveedor, credenciales, worker ni cambios LIVE.

## Tabla y estados

La migración aditiva y reversible `0011_document_storage_reconciliation.py` usa revision Alembic `0011_document_storage_ops` (dentro del límite de 32 caracteres) y crea `document_storage_operations`. Cada fila conserva únicamente ID, tipo `PUT`/`DELETE`, clave técnica content-addressed, SHA-256, backend, estado, indicador `cleanup_allowed`, contador/retry, marcas de tiempo, tipo de error sanitizado y snapshots opcionales de IDs de caso/documento **sin FK**. No contiene bytes, nombre de archivo, texto, extracción, email ni secretos. Las filas históricas `Document` no se modifican y no se generan tombstones retrospectivos.

| Estado | Significado | Transiciones automáticas válidas |
| --- | --- | --- |
| `PENDING` | Intención PUT confirmada en SQL antes de mutar storage | `CLEANUP`, `RETRY`, `BLOCKED`, `COMPLETE` |
| `CLEANUP` | Tombstone DELETE o objeto PUT huérfano por limpiar | `RETRY`, `BLOCKED`, `COMPLETE` |
| `RETRY` | Error transitorio, con `next_attempt_at` exponencial (máx. 1 h) | `CLEANUP`, `RETRY`, `BLOCKED`, `COMPLETE` |
| `BLOCKED` | Conflicto o integridad rota; revisión manual, sin delete automático | ninguna |
| `COMPLETE` | Ausencia confirmada o referencia válida preservada | ninguna |

Las transiciones no listadas fallan cerrado. El contador aumenta por intento real; estados terminales no se reclaman de nuevo. `document_storage_operation_status()` devuelve conteos internos de pending/cleanup/retry/blocked/completed recientes sin claves. No se expone endpoint público.

## PUT e incertidumbre de red

`save_upload` bloquea la clave y confirma una intención `PENDING` **antes** del PUT. Un probe inicial separa objeto preexistente válido de objeto ausente. Solo tras observar ausencia se confirma `cleanup_allowed=true` antes de llamar al backend; así, un crash o un ACK perdido del PUT deja evidencia durable de que pudo haberse creado un objeto. El backend mantiene PUT condicional, inmutabilidad y SHA del bloque anterior. Si el objeto era preexistente, `cleanup_allowed=false` prohíbe borrarlo por el fracaso de esa solicitud.

Documento, extracción, Fact/Evidence, audit mínimo y transición de la operación a `COMPLETE` se confirman en **una misma transacción SQL**. Si se pierde el ACK de ese commit, la fila y el Document confirmado son visibles juntos: el reconciliador conserva el objeto. Si no hay Document confirmado, el reconciliador **no reconstruye** el expediente a partir del objeto: `MISSING` completa; `PRESENT_AND_VALID` se limpia solo si `cleanup_allowed`; `PRESENT_CONFLICTING` bloquea; `UNKNOWN` reintenta. La compensación inmediata tras error es un intento de la misma máquina durable, no la única garantía. Un PUT preexistente válido sin Document nuevo se conserva.

## DELETE y crash recovery

Borrado de caso/cuenta adquiere el lock SQL de caso antes de tomar el snapshot de documentos. Por cada clave crea tombstone `CLEANUP` sin FK en la misma transacción que elimina lógicamente Document/Case/account. **Commit SQL ocurre antes de cualquier delete físico.** Tras el commit se intenta limpieza inline, limitada; si falla, la respuesta indica `storage_cleanup_pending=true` y el tombstone sobrevive para invocación posterior. `documents_deleted` cuenta filas SQL eliminadas, no promete borrado físico. Sin documentos, la semántica anterior continúa y `storage_cleanup_pending=false`.

Antes de cada delete, el reconciliador adquiere lock por clave, reclama fila (`FOR UPDATE SKIP LOCKED` en PostgreSQL) y consulta otra vez referencias `Document` confirmadas. Si existe referencia y objeto válido, conserva; si falta o está corrupto, bloquea por integridad. Si no hay referencia: `MISSING` es éxito idempotente; `PRESENT_AND_VALID` se elimina y se confirma ausencia con otro probe; resultado incierto reintenta. Un batch limitado procesa otras operaciones aunque una quede en `RETRY` o `BLOCKED`. Tras crash en mitad de varios deletes, cada tombstone vuelve a ser procesable; los objetos ya ausentes completan sin error. Logs contienen solo ID/tipo/estado/backend/intento/clase de error sanitizada, nunca clave o contenido.

## Concurrencia y límites

Upload y reconciliación de una misma clave comparten advisory lock de sesión PostgreSQL; SQLite usa mutex de proceso solo para desarrollo/tests. El row lock PostgreSQL evita doble claim; el advisory lock se libera también ante excepción y al caer la conexión. No hay cola, cron ni servicio adicional: el motor es invocable de forma explícita y la estrategia de scheduling/monitorización se decidirá con proveedor real. El probe provider-neutral devuelve `MISSING`, `PRESENT_AND_VALID`, `PRESENT_CONFLICTING` o `UNKNOWN`; nunca se interpreta una respuesta desconocida como permiso para borrar. La verificación de ausencia posterior al delete evita marcar como completado un ACK ambiguo.

Permanece pendiente: selección/prueba de proveedor y semántica real de consistencia, fijar la identidad operativa de bucket/endpoint/prefijo durante operaciones pendientes (o migrarlas con protocolo explícito), DPA y residencia, bucket policy, cifrado/rotación, malware/AV, versionado y borrado de versiones, lifecycle/retención legal, backup documental independiente, scheduling/alertas del reconciliador, privacidad y revisión profesional. El protocolo no convierte object storage y SQL en una transacción distribuida; convierte fallos recuperables en estado durable y observable bajo una configuración de backend estable. `PRIVATE_REAL_BETA` OFF; uploads Render/local OFF; **REAL BETA READINESS: NOT READY**.
