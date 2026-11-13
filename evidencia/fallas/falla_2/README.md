# Falla 2 — Helper de imagen adversarial con coordenadas inválidas

**Archivos:** `src/reclamos/escenario/artefactos.py` (`generar_imagen_no_constancia`), `tests/test_flujos.py::test_adv_imagen_que_no_es_constancia`.

## Síntoma
```
tests/test_flujos.py:97: ValueError: x1 must be greater than or equal to x0
```
La prueba adversarial A1 (imagen que no es una constancia) fallaba **antes** de llegar al agente.

## Hipótesis inicial
Incompatibilidad de versión de Pillow (13.0.0) con `ImageDraw.rectangle`.

## Diagnóstico
`rectangle([x0, y0, x1, y1])` valida el orden de coordenadas. El helper usaba `randint(0,300)` y `randint(100,400)` **independientes** para `x0` y `x1`,
por lo que a veces `x1 < x0`. Con otra semilla pasaría: fallo intermitente según la semilla, no por versión.

## Causa raíz
Bug del propio generador de datos de prueba (coordenadas aleatorias sin ordenar), no de la librería.

## Solución
Elegir `x0, y0` y sumar un ancho/alto positivo: `[x0, y0, x0 + randint(20,150), y0 + randint(20,150)]`.

## Aprendizaje
Los generadores de datos aleatorios también necesitan validez por construcción; si falla una prueba adversarial, revisar primero el *fixture* antes que el sistema bajo prueba.
