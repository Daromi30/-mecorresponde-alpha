# Beta interna sintética — verificación desplegada tras PR #209 (23-09-2026)

Solo se utilizaron hechos, importes, referencia y comunicaciones ficticios. No hubo upload, envío a terceros ni uso de datos reales. Este smoke se ejecutó por la API pública desplegada, no en un navegador; por tanto no acredita la experiencia visual ni completa por sí solo los escenarios A–H.

## Despliegue y preflight

- PR #209 fusionado: `main=6df78d646fb5e7fb01c4ee584228e0acf74467af`.
- Render auto-deploy `dep-dape8h2jnfac73cap6ig`, trigger `new_commit`, estado final `live`, mismo SHA. No se lanzó deploy manual.
- `/health`: HTTP 200, `status=ok`, `families=26`, `runtime_revision` igual al SHA de `main` y LIVE.
- CI del commit de merge: Database Migrations y MECORRESPONDE CI `success`.
- Arranque: misma `runtime_revision`, `database_backend=postgresql persistent=True existing_legal_sources=11`, `synthetic_internal_beta_ready=True`, `internal_beta_blockers=none`.
- `/health/persistence`: PostgreSQL persistente; `/health/storage`: backend local, no persistente, `uploads_allowed=false`.
- `/privacidad`: HTTP 503, `Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow`. `/sitemap.xml`: 404. Arranque: `public_indexing: ready=False`.

## Reproducción desplegada del defecto corregido

Expediente sintético `76ff3bbc-6b4f-4530-8e9b-68c6aad63ecc`, familia E04-B. Se registraron fin de suministro ficticio, servicio adicional ficticio y un cargo ficticio de 8,99 €. Tras diagnóstico, preparación y registro de envío simulado con referencia `PRUEBA_INTERNA_SINTETICA_20260923`, una respuesta simulada aceptó cancelar el servicio y devolver 8,99 €. El expediente pasó a `RESOLVED_PENDING_EXECUTION`.

1. Intento directo de API de cerrar con `verified_by_user=true` y `remaining_material_commitments=pending`: HTTP 422, sin cierre.
2. Se guardó la cancelación como cumplimiento parcial, importe recuperado 0 € y devolución pendiente: HTTP 200; caso `RESOLVED_PENDING_EXECUTION`, acción `VERIFY_EXECUTION` `OPEN`, un evento `EXECUTION_PARTIALLY_VERIFIED`, ningún `RESOLUTION_VERIFIED`.
3. Repetir idéntico parcial dejó un solo evento parcial y ningún evento de resolución.
4. Se simuló la devolución completa de 8,99 € y se confirmó `remaining_material_commitments=none`: HTTP 200; caso `RESOLVED`, sin acción corriente, `VERIFY_EXECUTION` `COMPLETED`, un evento parcial y exactamente un evento `RESOLUTION_VERIFIED`.

Resultado: PASS del gate y ciclo de vida de cumplimiento parcial en API LIVE. La UI/reentrada visual, A–H completos y la inspección manual de todas las familias siguen pendientes; no se declara superada la beta interna sintética.

## Regresión local del runbook

La prueba específica de runbook y outcomes pasó (12 tests). La suite completa Windows terminó con 666 aprobados y un fallo conocido de portabilidad: el test del manifiesto de backup exige bits POSIX `0600`, mientras NTFS reporta `0666`; no es un fallo observado en CI Linux, que está verde para el commit LIVE. El navegador integrado rechazó abrir el servicio con `ERR_BLOCKED_BY_CLIENT`, por lo que no se atribuye a esta evidencia ninguna inspección visual.
