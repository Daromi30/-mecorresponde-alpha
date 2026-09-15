# MECORRESPONDE — privacidad antes de una beta con datos reales

Este documento no es una política de privacidad ni una declaración de cumplimiento. Es una lista de información que debe cerrarse y revisarse antes de habilitar una beta con datos personales reales.

## Fuentes oficiales revisadas

- AEPD — Derecho de información: https://www.aepd.es/derechos-y-deberes/conoce-tus-derechos/derecho-de-informacion
- AEPD — Información cuando los datos se obtienen directamente del afectado: https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/6-el-deber-de-informacion/FAQ-0217-que-informacion-debe-facilitarse-cuando-los-datos-se-obtengan-directamente-del-afectado
- RGPD, artículo 13 — EUR-Lex: https://eur-lex.europa.eu/eli/reg/2016/679/oj

La AEPD recomienda información por capas: una primera capa resumida en el momento y medio de recogida, y una segunda capa detallada y accesible.

## Datos que MECORRESPONDE no debe inventar

Antes de publicar la información deben quedar identificados y revisados, como mínimo:

1. Identidad y datos de contacto del responsable del tratamiento y, si aplica, representante o DPD.
2. Fines concretos de cada tratamiento: expediente, cuenta, documentación, comunicaciones, seguridad/auditoría, revisión humana y cualquier analítica futura.
3. Base jurídica aplicable a cada finalidad. No debe usarse «consentimiento» por defecto ni asumirse que una única base cubre todos los tratamientos.
4. Plazos o criterios reales de conservación para cuentas, expedientes, documentos, comunicaciones, auditoría y copias de seguridad.
5. Destinatarios o categorías de destinatarios y encargados del tratamiento que realmente se utilicen.
6. Existencia o ausencia de transferencias internacionales y, si existen, las garantías aplicables.
7. Canal real para ejercer derechos de acceso, rectificación, supresión, oposición, limitación y portabilidad, y referencia al derecho a reclamar ante la autoridad de control.
8. Información sobre decisiones automatizadas o perfiles, si el diseño final llega a encajar en esos supuestos. El texto debe describir el sistema real, no atribuirle capacidades o efectos jurídicos que no tenga.
9. Tratamiento de categorías especiales de datos si una vertical o documento puede contenerlas. Debe definirse si se prohíben, minimizan o se tratan y con qué base específica.

## Criterio de activación

`PRIVACY_INFORMATION_PUBLISHED` permanecerá en `False` en el cockpit de readiness hasta que exista una información de privacidad revisada, accesible desde el propio punto de recogida de datos y coherente con los proveedores y políticas de conservación realmente desplegados.

Mientras siga en `False`, MECORRESPONDE puede usarse para desarrollo y pruebas con datos sintéticos, pero el propio sistema no debe declararse listo para una beta completa con datos personales reales.
