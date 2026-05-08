# Fase 2 — Análisis Empírico y Profiling

**Proyecto:** PRISMA-GTI
**Etapa:** Fase 2 de 5 — cierre
**Estado:** Completada
**Fecha de medición:** 8 de mayo de 2026
**Servidor:** `172.16.0.98` — usuario `ilab` — Ubuntu 26.04 — Python 3.14.4
**Versión:** 1.0

---

## 1. Resumen ejecutivo

La Fase 2 tenía como objetivo **validar empíricamente las hipótesis del diagnóstico estático de Fase 1** antes de iniciar la implementación. Para ello se ejecutó una batería de 8 scripts independientes que midieron, sobre datos reales del proceso de FINAGRO, los cuellos de botella, los tiempos de conexión, los volúmenes de cada fuente, y la ganancia esperada de cada optimización propuesta.

**Las mediciones cambiaron sustancialmente la priorización de la Fase 1.** El cuello de botella inicialmente identificado como crítico (LDAP en bucle) resultó ser marginal en el contexto real de FINAGRO, donde solo 43 cédulas únicas necesitan resolución y el 88,4% de ellas se resuelve con Kactus. El verdadero cuello de botella son **las escrituras intermedias a Excel**, que por sí solas explican aproximadamente la mitad de los 7m 11s de la corrida actual.

El plan de optimización resultante es más simple, más enfocado y de menor riesgo de implementación que el que se proyectaba originalmente. La estimación de mejora pasa de 40-60% (Fase 1) a un rango realista de **55-70% de reducción** en el tiempo total: de 7m 11s a aproximadamente **2-3 minutos** post-refactor.

---

## 2. Metodología

### 2.1 Enfoque

En lugar de ejecutar el notebook completo con `cProfile` (lo cual tardaría 7+ minutos por iteración y produciría datos difíciles de interpretar), se diseñó una **batería de 8 scripts independientes y de solo lectura**, cada uno enfocado en medir un único componente. Esto permitió:

- Iterar rápidamente (la batería completa corre en ~80 segundos).
- Aislar variables (cada script mide una sola cosa).
- Cero riesgo operacional (ninguno escribe a sistemas de producción).
- Evidencia versionable (cada corrida deja un `.md` con timestamp en `diagnostics/resultados/`).

### 2.2 Scripts ejecutados

| # | Script | Componente medido |
|---|---|---|
| 01 | `01_volumetria_fuentes.py` | Filas y características por fuente |
| 02 | `02_tiempo_conexiones.py` | Latencia de conexión SQL + LDAP |
| 03 | `03_tiempo_lectura_csv.py` | Velocidad de `read_csv` y `read_excel` |
| 04 | `04_ldap_unitario.py` | Costo de una búsqueda LDAP aislada |
| 05 | `05_ldap_batch.py` | LDAP por iteración vs persistente vs batch |
| 06 | `06_iterrows_vs_vectorizado.py` | iterrows() anidado vs `.map()` vs `pd.merge` |
| 07 | `07_excel_vs_parquet.py` | Comparativa de formatos para escritura/lectura |
| 08 | `08_perfil_kactus.py` | % de identidades resolubles sin LDAP |

### 2.3 Condiciones de medición

- **Servidor:** dedicado de FINAGRO (`172.16.0.98`).
- **Red:** intranet corporativa.
- **Datos:** fuentes reales en producción (modo solo lectura).
- **Repeticiones:** la batería se ejecutó dos veces el 8 de mayo. Los números reportados son de la segunda corrida (15:46:23). Las dos corridas dieron resultados consistentes (variación < 5% en todas las métricas).

### 2.4 Limitaciones reconocidas

Tres limitaciones que afectan la interpretación de algunos números:

1. **Las búsquedas LDAP del script 04 y 05 usan cédulas ficticias.** El costo de red es representativo, pero los tiempos de búsqueda con cédulas reales (que sí están en AD y retornan datos) podrían variar ligeramente.
2. **Los datos del script 06 son sintéticos.** El speedup matemático de iterrows vs vectorizado es real, pero la proyección del script ("7 bucles equivalen a 6m del total") **sobreestima** porque no considera que los iterrows reales del notebook tienen filtros condicionales que reducen las iteraciones efectivas.
3. **No se midió el costo de las transformaciones** (estandarización de servicios, normalización con `unidecode`, conversiones de fecha) ni los modelos de ML. Estos componentes consumen tiempo no atribuible directamente a los cuellos identificados.

---

## 3. Hallazgos por componente

### 3.1 Volumetría real del proceso

| Fuente | Filas | Tiempo de carga |
|---|---|---|
| Aranda Discovery (SP) | 26.313 | 631 ms |
| Aranda ITSM — Incidentes (SP) | 7.872 | 97 ms |
| Aranda ITSM — Servicios (SP) | 216 | 39 ms |
| Aranda ITSM — Cambios (SP) | 1.072 | 85 ms |
| Kactus — empleados | 853 | 53 ms |
| GLPI.csv | 11.826 | 74 ms |
| GEUS.xlsx | 2.442 | 150 ms |
| Incidentes.csv | 8.477 | 29 ms |
| Requerimientos.csv | 5.938 | 22 ms |
| Cambios.csv | 215 | 2 ms |
| Tareas.csv | 9.393 | 9 ms |
| IncidentesStefanini.csv | 8.477 | 61 ms |
| RequerimientosStefanini.csv | 5.938 | 44 ms |
| ProblemasStefanini.csv | 31 | 2 ms |
| CambiosStefanini.csv | 215 | 3 ms |
| usuarios.csv + especialistas.csv | 842 | 5 ms |
| **TOTAL** | **90.120 filas** | **~1,3 s** |

**Hallazgo clave:** la carga completa de datos (SQL + LDAP + archivos) se hace en **menos de 2 segundos**. Esto descarta como cuello de botella todo lo relacionado con adquisición de datos.

### 3.2 Latencia de conexiones

| Conexión | Tiempo total (conectar + ping + cerrar) |
|---|---|
| SQL Server — Aranda ITSM | 32,2 ms |
| SQL Server — Aranda Discovery | 33,5 ms |
| SQL Server — Kactus | 30,0 ms |
| LDAP / Active Directory | 60,1 ms |

**Hallazgo:** las conexiones son rápidas y estables. La conexión LDAP cuesta el doble que las SQL pero sigue siendo barata en términos absolutos.

### 3.3 Lectura de archivos

Tiempo total de lectura de los 12 archivos: **401 ms**. Los tres archivos más costosos son:

- GEUS.xlsx — 150 ms (es el único Excel binario real).
- GLPI.csv — 74 ms (4,9 MB).
- IncidentesStefanini.csv — 61 ms (3,9 MB).

**Hallazgo:** la lectura de archivos no es un cuello de botella. La estrategia "leer todo de raw, transformar en memoria" es viable.

### 3.4 LDAP — costo unitario

5 búsquedas individuales con conexión nueva por iteración (replicando el patrón del notebook):

- Promedio: **113,2 ms** por búsqueda.
- Mínimo: 100,8 ms.
- Máximo: 120,3 ms.
- Desviación estándar: 7,3 ms.

**Hallazgo:** cada búsqueda con el patrón actual del notebook cuesta ~113 ms. Para las 43 cédulas únicas reales serían **~5 segundos** en el peor caso. Es un cuello real pero **acotado**.

### 3.5 LDAP — comparativa de estrategias (experimento clave)

Sobre 30 cédulas, 3 estrategias:

| Estrategia | Tiempo | Speedup vs A |
|---|---|---|
| A — Conexión nueva por iteración (patrón notebook) | 3,36 s | 1× |
| B — Conexión persistente | 320,5 ms | **10,5×** |
| C — Búsqueda batch con filtro OR | 71,7 ms | **46,9×** |

**Hallazgo:** la optimización de LDAP es trivial de implementar y tiene speedup de **47×**. Aplicada a las 43 cédulas reales, baja el costo de ~5 segundos a **~100 ms**. Es una mejora confirmada pero **el ahorro absoluto es marginal** en el contexto del proceso completo.

### 3.6 iterrows() anidado vs vectorización

Sobre 5.000 filas con 1.000 de lookup:

| Estrategia | Tiempo |
|---|---|
| A — iterrows() anidado | 51,89 s |
| B — `.map()` con dict precomputado | 6,4 ms |
| C — `pd.merge` | 4,9 ms |

**Speedup matemático: 8.000-10.000×.**

**Interpretación honesta:** este speedup sintético es real pero **no es directamente extrapolable** al notebook. La proyección automática del script ("7 bucles × 51,9s = 6m 3s") sobreestima porque:

- Los datos sintéticos tienen **100% de coincidencia** entre `df_principal` y `df_lookup`, así que el inner loop recorre todo el lookup en cada fila.
- En el notebook real, cada bucle tiene filtros condicionales (`if pd.isna(...)`, `if .isdigit()`, etc.) que **reducen drásticamente las iteraciones efectivas**.

**Estimación realista del costo total de los 7 iterrows en el notebook:** entre **30 segundos y 2 minutos** sumando los siete. La vectorización los reduce a **milisegundos** en total.

### 3.7 Excel vs Parquet vs CSV

Sobre un DataFrame de 60.000 filas × 15 columnas (similar a `indicators1.xlsx`):

| Operación | Excel | CSV | Parquet | Excel→Parquet |
|---|---|---|---|---|
| Escritura | 11,56 s | 223 ms | 62 ms | **185× más rápido** |
| Lectura | 7,27 s | 224 ms | 18 ms | **404× más rápido** |
| Tamaño en disco | 5,5 MB | 10,5 MB | 2,6 MB | **54% menos** |

**Hallazgo crítico:** este es el **cuello de botella dominante** del proceso. El notebook actual hace ~25 escrituras a Excel. Si la mayoría son intermedias (cacheo entre etapas) y se migran a Parquet, se eliminan aproximadamente **3-4 minutos del tiempo total**.

### 3.8 Perfil de Kactus — cobertura de identidades

| Métrica | Valor |
|---|---|
| Cédulas únicas en Discovery | 43 |
| Resolubles desde Kactus | 38 (88,4%) |
| Requieren consulta LDAP | 5 (11,6%) |

**Hallazgo:** la estrategia óptima del módulo `identity/resolver.py` es **"Kactus primero, LDAP solo para residuales"**. Con esto:

- 38 cédulas se resuelven con `dict.get()` — costo: **microsegundos**.
- 5 cédulas se resuelven con un único batch LDAP — costo: **<100 ms**.
- Total: el componente LDAP del proceso pasa de un máximo teórico de 5 segundos a aproximadamente **200 ms en total**.

---

## 4. Re-priorización de cuellos de botella

Comparando la priorización de Fase 1 (basada en análisis estático) contra la evidencia empírica de Fase 2:

| # | Cuello | Prioridad Fase 1 | Tiempo medido / estimado | Prioridad Fase 2 |
|---|---|---|---|---|
| 1 | Escrituras Excel intermedias | 🟠 Media | **~3-4 min (50% del total)** | 🔴 **Alta** |
| 2 | iterrows() anidados | 🔴 Alta | **~30s-2min (10-25%)** | 🟠 Media-Alta |
| 3 | Transformaciones + ML | No clasificado | ~1-2 min (estimado por residual) | 🟡 Media |
| 4 | LDAP en bucle | 🔴 Alta | **<5 s (<2%)** | 🟢 Baja (fix trivial) |
| 5 | SP sin parametrización | 🟠 Media | ~600 ms (<1%) | ✅ **Descartado** |
| 6 | Lectura de archivos | No clasificado | ~400 ms (<1%) | ✅ Descartado |

**Inversión de prioridades respecto a Fase 1:**

- El cuello LDAP, que parecía crítico, se reveló marginal por dos razones: (a) solo hay 43 cédulas únicas, (b) Kactus cubre el 88,4% de ellas.
- Las escrituras Excel intermedias, que en Fase 1 se clasificaron como prioridad media, son en realidad el cuello dominante.
- La carga incremental sobre los SPs (mejora propuesta en Fase 1 cuello #4) **se descarta** porque las consultas SQL ya son muy rápidas.

---

## 5. Decisiones de diseño que se desprenden

Las mediciones empíricas justifican las siguientes decisiones para la implementación (Fase 3):

### 5.1 Estrategia de almacenamiento intermedio

**Decisión:** todos los archivos intermedios entre etapas se almacenan en **Parquet**, no en Excel ni CSV. Solo los 3 archivos finales que consume Power BI (`indicators1.xlsx`, `provisionalASMS.xlsx`, `tareas1.xlsx`) se escriben en `.xlsx`.

**Justificación:** el script 07 mostró que Parquet es 185× más rápido en escritura y 404× en lectura. Esta decisión sola explica la mayor parte del ahorro de tiempo proyectado.

**Implementación:** módulos `writers/parquet.py` (intermedios) y `writers/excel.py` (finales) con interfaces separadas.

### 5.2 Estrategia de resolución de identidades

**Decisión:** orden de prioridad para resolver una cédula:

1. Lookup en `kactus_index` (diccionario en memoria).
2. Si no está en Kactus: consulta a LDAP en batch (con todas las residuales en un solo round-trip).
3. Si LDAP no devuelve: aplicar `manual_overrides` desde YAML.
4. Si nada funciona: marcar como no resuelto, log WARNING, continuar.

**Justificación:** el script 08 mostró que el 88,4% de las cédulas se resuelven en Kactus (lookup O(1)). El script 05 mostró que el batch LDAP es 47× más rápido que el patrón actual. La combinación reduce el costo total de identidades de ~5s (peor caso del notebook) a ~200ms.

**Implementación:** módulo `identity/resolver.py` con esta cadena explícita.

### 5.3 Vectorización obligatoria

**Decisión:** **prohibido** usar `iterrows()` en el código de PRISMA. Cualquier transformación que necesite cruzar dos DataFrames debe usar `.map()` con diccionario precomputado, `pd.merge`, o equivalente vectorizado.

**Justificación:** el script 06 mostró diferencias de 4 órdenes de magnitud en el peor caso. Aún descontando la sobreestimación por datos sintéticos, la diferencia real es de 100× a 500×.

**Implementación:** los 7 bucles del notebook se reemplazan por operaciones vectorizadas en los módulos `identity/` y `transformers/`. Lint en CI rechaza commits con `iterrows()` (excepción explícita con comentario justificativo).

### 5.4 Carga incremental — descartada

**Decisión:** **no implementar** carga incremental sobre los SPs en esta versión.

**Justificación:** los scripts 01 y 02 mostraron que cargar el histórico completo de cada SP toma menos de 1 segundo. La complejidad de implementar y mantener una carga incremental no se justifica con un ahorro de fracciones de segundo. Si en el futuro los SPs se vuelven más lentos, se reconsidera.

### 5.5 Configuración del cliente LDAP

**Decisión:** una sola conexión LDAP persistente por corrida, con búsqueda batch usando filtro OR `(|(employeeID=X)(employeeID=Y)...)` paginado en chunks de 200.

**Justificación:** el script 05 confirmó 47× de speedup. El tamaño de chunk (200) se eligió como punto medio entre límites de filtro LDAP (típicamente 1024 caracteres) y eficiencia de round-trip.

**Implementación:** módulo `loaders/ldap_client.py` y cache en `identity/ldap_cache.py`.

### 5.6 Eliminación de archivos intermedios de depuración

**Decisión:** eliminar las ~20 escrituras de archivos de inspección que existen en el notebook (`provisional.xlsx`, `glpi2.xlsx`, etc.).

**Justificación:** son artefactos del desarrollo del notebook, no producen valor en producción. Su eliminación libera 2-4 minutos por corrida.

**Implementación:** modo `--debug` opcional que escribe Parquet en `data/interim/` para inspección, pero **no se ejecuta por defecto**.

---

## 6. Estimación de tiempos post-refactor

Construida sumando componentes medidos y estimando los no medidos:

| Componente | Tiempo notebook actual | Tiempo PRISMA estimado | Mejora |
|---|---|---|---|
| Carga SQL (3 BDs) | ~600 ms | ~600 ms | igual |
| Carga LDAP | ~5 s | ~200 ms | -96% |
| Carga archivos | ~400 ms | ~400 ms | igual |
| Resolución de identidades (iterrows) | 30s - 2min | < 1 s | -99% |
| Estandarización + transformaciones | ~1-2 min | ~30 s | -50% a -75% |
| Escrituras intermedias | ~3-4 min | < 1 s (Parquet, opcional) | -99% |
| Escrituras finales | ~30 s | ~30 s | igual |
| Modelos ML | ~30-60 s | ~30-60 s | igual |
| **Total estimado** | **7m 11s (medido)** | **2m - 3m 30s** | **-55% a -70%** |

> El rango refleja la incertidumbre sobre componentes no medidos (transformaciones, modelos ML) y sobre el speedup real de la vectorización en datos no sintéticos.

---

## 7. Riesgos para la Fase 3

Tres riesgos identificados que afectan la implementación:

**Riesgo 1 — Diferencias funcionales sutiles entre notebook y PRISMA.**
La migración del notebook a operaciones vectorizadas puede introducir diferencias en el manejo de NaN, orden de filas, tipos de datos, etc. Estas diferencias pueden romper aguas abajo el dashboard de Power BI.

*Mitigación:* el script `scripts/compare_outputs.py` debe comparar la salida de PRISMA contra la del notebook fila por fila. PRISMA no se promueve a producción hasta que la comparación sea idéntica.

**Riesgo 2 — Las URLs públicas de Google Sheets pueden caerse.**
Los modelos predictivos consumen dos URLs externas que están fuera del control de FINAGRO. Si alguien las despublica o cambia el formato, el pipeline falla.

*Mitigación:* el módulo `pipelines/ml_models.py` debe tener manejo robusto de errores y poder ejecutarse en modo "skip ML" si las URLs no responden.

**Riesgo 3 — Cambios de Stefanini en los CSVs.**
Fabián mencionó en su confirmación inicial que Stefanini puede solicitar campos adicionales. Cualquier cambio de esquema rompe los `loaders` específicos.

*Mitigación:* los `loaders` deben validar el esquema esperado contra el real al cargar, y emitir un error claro si hay discrepancias. Los esquemas se mantienen como constantes en cada loader y se versionan con el repo.

---

## 8. Estado de los entregables

| Entregable de Fase 2 | Estado |
|---|---|
| Diseño y construcción de la batería de diagnósticos | ✅ Completo (`diagnostics/` con 8 scripts + orquestador) |
| Ejecución empírica contra datos reales | ✅ Completo (2 corridas el 8 de mayo) |
| Evidencia versionable de cada medición | ✅ Completo (`diagnostics/resultados/*.md`) |
| Documento de cierre con re-priorización | ✅ Este documento |
| Decisiones de diseño justificadas para Fase 3 | ✅ Sección 5 de este documento |

---

## 9. Próximos pasos — entrada a Fase 3

Con los hallazgos consolidados y las decisiones de diseño tomadas, la Fase 3 (refactor a CLI modular) puede arrancar de inmediato. El orden de implementación recomendado es:

1. **`core/`** — config, logger, secrets, exceptions. Base sobre la que se monta todo lo demás.
2. **YAMLs de configuración** — extracción mecánica del catálogo de servicios (~80 reglas) y excepciones de usuarios (~40 overrides) desde el código del notebook.
3. **`loaders/`** — empezando por `ldap_client.py` (con la optimización validada), luego los SQL, luego los CSV.
4. **`identity/resolver.py`** — la lógica más compleja del proyecto, ya con estrategia clara de la sección 5.2.
5. **`transformers/`** — funciones puras, fáciles de testear.
6. **`pipelines/`** — orquestación de loaders + transformers + writers.
7. **`writers/`** — Excel para finales, Parquet para intermedios.
8. **`cli.py`** — comandos que exponen los pipelines.
9. **Tests** — unitarios e integración, en paralelo con cada módulo.
10. **`scripts/compare_outputs.py`** — el test de aceptación crítico.

---

## 10. Anexos

### 10.1 Archivos de evidencia

Cada corrida genera markdown en `diagnostics/resultados/` con timestamp. La evidencia de la corrida del 8 de mayo:

```
diagnostics/resultados/01_volumetria_20260508_154624.md
diagnostics/resultados/02_conexiones_20260508_154625.md
diagnostics/resultados/03_lectura_archivos_20260508_154625.md
diagnostics/resultados/04_ldap_unitario_20260508_154626.md
diagnostics/resultados/05_ldap_batch_20260508_154630.md
diagnostics/resultados/06_iterrows_vs_vectorizado_20260508_154722.md
diagnostics/resultados/07_excel_vs_parquet_20260508_154743.md
diagnostics/resultados/08_perfil_kactus_20260508_154744.md
```

### 10.2 Reproducibilidad

Cualquier persona del equipo puede reproducir las mediciones con:

```bash
cd ~/PRISMA/prisma-gti
source .venv/bin/activate
python diagnostics/run_all.py
```

Tiempo total de ejecución: aproximadamente 80 segundos.

### 10.3 Glosario

- **iterrows()** — método de pandas que itera filas de un DataFrame. Lento por crear un objeto Series por fila.
- **Vectorización** — operar sobre una columna entera de pandas en una sola llamada en lugar de iterar fila por fila.
- **Parquet** — formato de archivo binario columnar, óptimo para datasets tabulares grandes.
- **LDAP batch** — agrupar múltiples búsquedas LDAP en una sola consulta usando filtro OR.
- **Speedup** — razón entre tiempo antes y tiempo después de una optimización.

---

*Documento de cierre formal de la Fase 2 del proyecto PRISMA-GTI. Habilita el inicio de la Fase 3 (implementación).*