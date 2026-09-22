# Beta interna sintética — evidencia manual parcial (22-09-2026)

Esta prueba usó exclusivamente hechos, importes, referencias y comunicaciones ficticios. No se subieron archivos ni se contactó a ninguna empresa. No constituye el recorrido A–H completo ni una revisión jurídica de las fuentes citadas por el producto.

## Preflight desplegado

- `main` y Render LIVE: `5663d8b28a35817355f38b6c55ecd231916a0fa2`.
- Database Migrations y MECORRESPONDE CI: SUCCESS en ese SHA.
- `/health`: HTTP 200, `status=ok`, `families=26`, `runtime_revision` igual al SHA LIVE.
- `/health/persistence`: PostgreSQL persistente. Log de arranque: 11 fuentes jurídicas existentes.
- Log de arranque: `synthetic_internal_beta_ready=True`, `internal_beta_blockers=none`.
- `/health/storage`: `backend=local`, `persistent=false`, `uploads_allowed=false`. Un POST vacío de prueba a la ruta de documentos recibió 503 antes de crear archivo.
- `/privacidad`: HTTP 503, `Cache-Control: no-store` y `X-Robots-Tag: noindex, nofollow`.
- Portada: `X-Robots-Tag: noindex, nofollow`; `/sitemap.xml`: 404; log `public_indexing: ready=False`.

## Recorrido manual observado

1. Un relato libre ambiguo sobre una factura ficticia acabó en `HUMAN_REVIEW`, sin importe ni conclusión jurídica automática. Tras recargar el enlace del expediente conservó el estado.
2. El ejemplo de tarifa distinta, con factura ficticia del 01-04-2026, llegó al diagnóstico y la interfaz lo detuvo para revisión profesional por la cuestión temporal que mostró. Esta prueba no valida de forma independiente esa interpretación jurídica.
3. El mismo ejemplo, con factura ficticia del 01-08-2026, contrato particular de mercado libre, oferta ficticia de 0,15 €/kWh y factura ficticia de 0,20 €/kWh, produjo diagnóstico y acción preparada. El producto no calculó una devolución sin consumos y facturas verificables: mostró 0,00 €.
4. Se registró un envío **ficticio**, con referencia `PRUEBA_INTERNA_SINTETICA_20260922`; el caso pasó a espera de respuesta.
5. Se introdujo esta respuesta **ficticia**: «Aceptamos la reclamación, corregiremos el precio aplicado en las facturas y devolveremos la diferencia cobrada». El caso pasó a `RESOLVED_PENDING_EXECUTION`.
6. En la verificación se indicó «Restitución/corrección contractual», importe recuperado 0 € y texto: «la tarifa contractual quedó corregida; no se ha acreditado devolución de dinero». Al pulsar «Sí, ya se ha cumplido», el caso pasó a `RESOLVED`. Tras recargar conservó `Resuelto` y mostró documentación en solo lectura.

## Incidencia P1: cierre con cumplimiento parcial

La respuesta ficticia tenía dos compromisos materiales: corregir el precio y devolver la diferencia. El formulario permitió cerrar el caso cuando solo se declaró comprobada la corrección y la devolución quedó expresamente sin acreditar. El backend exige canal y descripción para un resultado no monetario de 0 €, pero no pregunta de forma separada si hay compromisos pendientes. El test automatizado existente cubre una resolución no monetaria de 0 €; no cubre esta combinación de compromiso monetario pendiente y corrección parcial.

Resultado esperado: poder registrar la corrección parcial y mantener `RESOLVED_PENDING_EXECUTION` con `VERIFY_EXECUTION` abierta hasta comprobar la devolución o confirmar explícitamente que no queda obligación material aplicable. No debe cerrarse mediante inferencia de texto libre.

No se declara superado el escenario A del runbook: este recorrido fue E01 y el escenario A exige E02-A, además de pruebas adicionales. Tampoco se declaran superados B–H ni la matriz de familias. El runbook aún habla de 14 familias mientras el manifiesto y el servicio muestran 26; WORK debe actualizar esa matriz antes del freeze.
