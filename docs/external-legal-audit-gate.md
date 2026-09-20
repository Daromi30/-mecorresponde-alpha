# MECORRESPONDE — gate de auditoría jurídica externa antes de datos reales

Este documento define cuándo y cómo someter el Motor de Resolución a una revisión externa adicional. No sustituye una revisión jurídica profesional ni convierte la salida de un modelo de IA en una certificación de conformidad.

## Momento de activación

La primera auditoría externa debe ejecutarse cuando:

- la beta interna sintética esté congelada y sin bloqueantes internos;
- las familias, estados, acciones, reentrada, respuesta, escalado y resolución estén cubiertos por CI;
- el catálogo jurídico y sus fuentes estén versionados;
- todavía no se hayan abierto casos con datos personales reales.

No conviene esperar al lanzamiento público: las conclusiones de la auditoría deben poder cambiar arquitectura, contratos de seguridad o flujos sin afectar a usuarios reales.

## Dos capas de revisión

### 1. Revisión adversarial con IA jurídica especializada

Puede usarse Astra for Law u otra herramienta jurídica especializada disponible en ese momento, previa comprobación de:

- jurisdicciones y fuentes realmente cubiertas;
- actualidad del índice jurídico;
- políticas de confidencialidad, retención y uso de datos;
- posibilidad de trabajar exclusivamente con repositorio, documentación y casos sintéticos.

La IA externa debe buscar defectos, no emitir un sello de aprobación. Como mínimo debe revisar:

- afirmaciones jurídicas no respaldadas por fuente verificable;
- contradicciones entre evaluadores, catálogo jurídico, UI y textos de reclamación;
- plazos, organismos, cuantías o remedios inventados o inferidos sin soporte;
- rutas que puedan saltarse revisión humana;
- estados o acciones sin salida;
- pérdida de procedencia o trazabilidad;
- puntos donde una respuesta de empresa pueda alterar indebidamente hechos confirmados;
- falsos positivos de resolución o cierre;
- riesgos de que una vertical futura quede acoplada a electricidad;
- supuestos donde el sistema debería fallar cerrado y no lo haga;
- objeciones fuertes contra las conclusiones del Motor.

Si la herramienta no dispone de cobertura fiable de derecho español/UE, su revisión jurídica sustantiva se tratará como orientativa. Puede seguir siendo útil para arquitectura, consistencia, seguridad y metodología.

### 2. Revisión jurídica humana en España

Antes de aceptar datos reales o prestar un servicio jurídico al público, una persona profesional competente debe revisar, como mínimo:

- el catálogo de reglas y fuentes aplicables a España;
- los textos que el producto presenta como conclusiones jurídicas relevantes;
- los remedios y acciones generados;
- cualquier plazo legal que se llegue a mostrar;
- el diseño de escalado a revisión profesional;
- los límites entre orientación automatizada, gestión asistida y abogacía.

La revisión humana no se sustituye por acuerdo entre dos modelos de IA.

## Paquete de auditoría

La versión congelada debe acompañarse de:

- SHA exacto de `main` desplegado;
- manifiesto de familias;
- catálogo jurídico versionado y fuentes oficiales;
- inventario de tipos de acción;
- máquina de estados y guardas de fase;
- tests de aceptación de las familias;
- tests de respuesta, outcome, escalado y reentrada;
- contratos de evidencia/procedencia;
- readiness de beta;
- lista explícita de bloqueantes de datos reales;
- casos sintéticos representativos y adversariales.

No deben enviarse datos personales reales a la herramienta de auditoría.

## Criterio de salida

La auditoría no se considera superada porque la herramienta diga “correcto” o dé una puntuación alta. Cada hallazgo debe clasificarse como:

- defecto confirmado → corregir y añadir regresión;
- riesgo plausible → investigar y decidir;
- observación de producto → valorar sin convertirla automáticamente en requisito;
- afirmación jurídica externa → verificar contra fuente oficial antes de incorporarla;
- falso positivo → documentar por qué no requiere cambio.

Después de cualquier cambio material se repite el subconjunto de pruebas afectado y CI completo. La versión candidata a beta real debe quedar identificada por commit exacto.

## Prompt

El prompt definitivo se generará contra la versión congelada del producto para que incluya su arquitectura y contratos reales. Debe pedir explícitamente una revisión adversarial, exigir fuentes verificables, separar hechos de hipótesis, prohibir inventar legislación/plazos/organismos y solicitar los mejores argumentos en contra de cada conclusión relevante.
