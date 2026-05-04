# Fase 1 — Diagnóstico e Inventario

**Proyecto:** PRISMA-GTI
**Etapa:** Fase 1 de 5
**Estado:** Completada
**Versión:** 1.1 — actualizada con hallazgos de inspección de archivos finales

---

## 1. Resumen ejecutivo

El proceso actual consiste en **dos notebooks Jupyter ejecutados manualmente y en secuencia**: primero `ProyectoFinal3.ipynb` (246 bloques de código) y después `Indicadores2026.ipynb` (47 bloques adicionales), sumando aproximadamente **2.500 líneas de código sin modularizar**.

**Tiempo real medido (reportado por Fabián):** 7 minutos 11 segundos en total (`ProyectoFinal3`: 6m53s + `Indicadores2026`: 18s).

Se identificaron **5 cuellos de botella algorítmicos críticos** y aproximadamente **15 issues secundarios**. Los cuellos de botella comparten un mismo patrón: bucles anidados con `iterrows()` sobre DataFrames de tamaño moderado-grande, lo que produce complejidad temporal **O(N·M)** cuando una operación vectorizada equivalente sería **O(N+M)**.

**Recalibración del beneficio esperado:** la motivación inicial del refactor fue la percepción de "muchas horas" de duración. Con el dato real de 7 minutos, el beneficio principal **no es velocidad pura sino automatización, seguridad y mantenibilidad**:

- Eliminación de credenciales hardcoded en código.
- Automatización del proceso (hoy es ejecución celda por celda).
- Trazabilidad mediante logging estructurado.
- Mantenibilidad mediante modularización y configuración externa.
- Ganancia de rendimiento esperada: 40–60% (de 7m11s a aproximadamente 2-4 minutos).
- Escalabilidad: el `O(N·M)` actual va a doler progresivamente cuando los datos crezcan año tras año.

> **Hallazgo de seguridad relevante:** se encontraron **credenciales en texto plano** (3 cadenas de conexión SQL Server + 1 cuenta de servicio LDAP). Esto debe corregirse en la Fase 3 con prioridad alta, independientemente del refactor de rendimiento.

---

## 2. Inventario del proceso

### 2.1 Métricas básicas

| Métrica | Valor |
|---|---|
| Bloques de código (notebook 1) | 246 |
| Bloques de código (notebook 2) | 47 |
| Líneas de código aproximadas | ~2.500 |
| Tiempo total de ejecución | 7m 11s |
| DataFrames intermedios identificados | 25+ |
| Archivos `.xlsx` intermedios escritos | ~25 |
| Funciones definidas | 11 |
| Bucles `iterrows()` anidados | 7 |

### 2.2 Fuentes de datos de entrada

El proceso consume datos de **cinco tipos de fuentes distintas**:

**Bases de datos SQL Server** (servidor `172.16.20.70`):
- `ArandaDB8` — ejecuta `SP_CHANGES1`, `SP_SERVICECALL1`, `SP_INCIDENTESGTI1` y consulta tabla `USUARIOS`.
- `DiscovSQL` — ejecuta `SP_CASOS_DISCOVERYGTI_V1`.
- `kactus` — consulta de empleados (nombre completo, cédula, username).

**LDAP / Active Directory** (`ldap://172.16.0.5:389`, dominio `FINAGRO.LOC`):
- Búsqueda por `employeeID` (cédula) → retorna `sAMAccountName`.
- Búsqueda por `sAMAccountName` → retorna `displayName`.

**Archivos planos locales:**
- `usuarios.csv`, `especialistas.csv` — diccionarios precargados.
- `GLPI.csv` (separador `;`).
- `Incidentes.csv`, `Requerimientos.csv`, `Cambios.csv`, `Tareas.csv` (Aranda ASMS, notebook 1).
- `IncidentesStefanini.csv`, `RequerimientosStefanini.csv`, `ProblemasStefanini.csv`, `CambiosStefanini.csv` (notebook 2).
- `GEUS.xlsx`.
- `indicators_abiertos.xlsx` (intermedio, generado por el propio proceso).

**Hojas de cálculo publicadas en Google Sheets:**
- 2 URLs públicas con datos `indicadoresPeriodo` e `indicadoresPeriodo2026` para el modelo polinómico.

### 2.3 Salidas finales (consumidas por Power BI — confirmado por Fabián)

| Archivo | Filas | Columnas | Cobertura temporal | Notas |
|---|---|---|---|---|
| `indicators1.xlsx` | 62.946 | 15 | 2014 → presente | Dataset histórico consolidado de los 5 orígenes. |
| `provisionalASMS.xlsx` | 14.630 | 25 | 2025-03 → presente | Solo Aranda ASMS, con 10 columnas adicionales (prioridad, grupo_especialista, estado, razon, ubicacion, ANS atención, etc.). |
| `tareas1.xlsx` | 1.186 | 17 | 2026-02 → presente | Solo tareas Aranda 2026. |
| `TIC-FOR-010 BITACORA PLATAFORMA TECNOLOGICA.xlsx` | varias hojas | varias | 2009 → presente | **No se genera en los notebooks.** Mantenido manualmente; consumido directamente por Power BI. **Fuera del alcance del refactor.** |

**Distribución por origen de `indicators1.xlsx`:**
- Discovery: 26.313 casos
- Aranda ASMS: 15.614 casos
- GLPI: 11.791 casos
- Aranda: 8.029 casos
- GEUS: 1.199 casos

### 2.4 Archivos intermedios (a eliminar en el refactor)

Escritos pero no consumidos por sistemas externos:
`provisional.xlsx` (4 escrituras), `provisionalOriginal.xlsx`, `Discovery2.xlsx`, `arandaDes.xlsx`, `glpi2.xlsx` (2 escrituras), `glpi5.xlsx`, `glpi6.xlsx`, `pruebasglpi.xlsx`, `geus1.xlsx` (2 escrituras), `indicadores.xlsx` (2 escrituras), `indicadores1provisional.xlsx`, `indicadores1.xlsx`, `indicadores4.xlsx`, `tareas1.xlsx` (2 escrituras), `servicios1.csv`, `ServiciosASMS.csv`, `indicadoresPeriodo2026.xlsx`, `indicadoresPeriodo.xlsx`.

> Estas escrituras son artefactos del desarrollo del notebook (inspección manual celda por celda). En PRISMA deben eliminarse o quedar tras un flag `--debug`.

### 2.5 Dependencias

Librerías Python usadas: `pandas`, `numpy`, `matplotlib`, `seaborn`, `sklearn`, `statsmodels`, `pyodbc`, `ldap3`, `unidecode`, `re`. Todas son estándares y compatibles con un entorno reproducible vía `requirements.txt` o `pyproject.toml`.

Driver requerido del sistema: **ODBC Driver 17 for SQL Server**.

---

## 3. Mapa de flujo del proceso

A muy alto nivel, el proceso se compone de seis etapas:

1. **Carga** de fuentes (SQL × 3, LDAP, CSVs, Excel, Google Sheets).
2. **Normalización de identidades** — resolver inconsistencias entre nombres de usuario, cédulas, nombres completos y `sAMAccountName` cruzando contra Kactus, Aranda y LDAP.
3. **Estandarización de catálogos** — homogenizar nombres de servicios, tipos de caso, valores de cumplimiento ANS.
4. **Consolidación** — concatenar Discovery, Aranda (3 SP), GLPI, GEUS, ASMS y Tareas en un único DataFrame.
5. **Modelado** — regresión lineal y polinómica para predicción de cantidad de casos; regresión logística para predicción de cumplimiento ANS.
6. **Persistencia** — exportación a `.xlsx` para consumo por Power BI.

---

## 4. Cuellos de botella críticos (priorizados)

### 🔴 #1 — LDAP en bucle con apertura/cierre de conexión por iteración

**Ubicación:** Bloque 20 (notebook 1), funciones `convertirCedula` (Bloque 13) y `convertirUsername` (Bloque 32).

**Patrón actual:**
```python
for i, fila, in discovery.iterrows():
    if discovery1.loc[i , 'username_ufinal'].isdigit():
        discovery1.loc[i, 'username_ufinal'] = convertirCedula(...)
```

Y dentro de `convertirCedula`:
```python
with Connection(server, user=username, password=password, ...) as conn:
    conn.bind()
    conn.search(...)
```

**Diagnóstico:**
- Cada llamada **abre una conexión TCP, autentica (bind LDAP), busca, cierra**.
- Si hay K cédulas distintas a resolver, son K conexiones LDAP secuenciales.
- Cada handshake + bind LDAP cuesta entre 50 ms y 500 ms sobre red corporativa.

**Complejidad:** O(K) consultas de red secuenciales.

**Solución propuesta:**
- Una sola conexión LDAP reutilizada (módulo `loaders/ldap_client.py`).
- Búsqueda batch con filtro OR: `(|(employeeID=123)(employeeID=456)...)` paginando en chunks de 200-500.
- Cache local en dict.
- Priorizar resolución desde `kactus` antes de consultar LDAP.

**Ganancia esperada:** Reducción >95% en el tiempo de esta sección.

---

### 🔴 #2 — Bucles anidados `iterrows()` para enriquecer DataFrames

**Ubicaciones:** Bloques 18, 24, 30, 34 (`llenarConAranda`), 42 (`corregirResponsables`), 83 (`completarUsernames`), 97 (`completarUsernames1`), 112 (`completarUsernamesGEUS`).

**Patrón actual (ejemplo Bloque 18):**
```python
for i, fila, in discovery1.iterrows():
    if discovery1.loc[i , 'username_ufinal'].isdigit():
        for j, fila, in kactus.iterrows():
            if kactus.loc[j,'cedula'] == discovery1.loc[i , 'username_ufinal']:
                valor = kactus.loc[j, 'username']
                discovery1.loc[i , 'username_ufinal'] = valor
```

**Diagnóstico:**

1. `iterrows()` es ~50–200x más lento que las operaciones vectorizadas de pandas.
2. Doble loop anidado → complejidad **O(N·M)** donde N ≈ 60.000 y M ≈ 1.000–5.000.
3. Asignación con `.loc[i, col] = valor` en cada iteración dispara validación de índices.

**Caso especialmente patológico (Bloque 83 / 112 — `completarUsernames`):**
```python
for i, fila, in dataframe.iterrows():        
        for j, fila, in arandaUsuarios.iterrows():
            valor_aranda = unidecode(arandaUsuarios.loc[j, campoAranda]).lower()
            valor_glpi = unidecode(dataframe.loc[i, campoGLPI]).lower()
```
Aquí además se llama a `unidecode()` dentro del bucle interno, ejecutándolo millones de veces sobre los mismos valores.

**Solución propuesta:**
- Reemplazar cada bucle anidado por `pd.merge` o `.map()` con diccionarios precomputados.
- Pre-normalizar columnas una sola vez fuera del bucle.
- Complejidad final: O(N + M).

**Ganancia esperada:** Reducción >98% en cada uno de estos bloques.

> Es importante notar que el autor **ya identificó parcialmente** este problema: en los Bloques 48 y 49 reemplazó `corregirResponsables` por `.map(diccionario_norm_esp)`. La tarea es propagar ese mismo patrón a los 6-7 lugares restantes.

---

### 🟠 #3 — Escrituras intermedias a Excel

**Ubicaciones:** ~25 invocaciones de `df.to_excel(...)` distribuidas por el notebook.

**Diagnóstico:**

`pd.DataFrame.to_excel()` con `openpyxl` es 5-20x más lento que `to_csv()` o `to_parquet()`. Para un DataFrame de 60.000 filas y 15 columnas, una escritura típica toma entre 15 y 90 segundos. De las 25 escrituras, solo 3-4 corresponden a salidas finales reales.

**Solución propuesta:**
- Eliminar todas las escrituras intermedias en producción.
- Mantener solo las salidas finales que consume Power BI.
- Para inspección durante desarrollo, flag `--debug` que escribe en `data/interim/`.
- Para escrituras intermedias necesarias (cache entre etapas), preferir Parquet.

**Ganancia esperada:** 1–3 minutos menos por corrida.

---

### 🟠 #4 — Lectura de Stored Procedures sin parametrización ni timeout

**Ubicación:** Bloques 7, 9, 10 (notebook 1).

**Diagnóstico:**

Los SP retornan **todos los casos históricos** (sin filtros de fecha). Confirmado al inspeccionar `indicators1.xlsx`: contiene casos desde 2014. Cada ejecución descarga 12 años de datos que en su gran mayoría no han cambiado. No hay manejo de errores ni timeouts.

**Solución propuesta:**
- Parametrizar los SP con fecha de corte.
- Considerar **carga incremental**: descargar solo lo nuevo, conservar histórico en parquet local.
- Encapsular las llamadas en `try/except` con logging.
- Agregar `connection_timeout` y `query_timeout`.

**Ganancia esperada:** Variable. Si el histórico antiguo se cachea en parquet, el ahorro puede ser muy significativo en corridas frecuentes.

---

### 🟡 #5 — `.copy()` y DataFrames intermedios excesivos

**Diagnóstico:**

El notebook crea más de 25 DataFrames intermedios (`discovery1`, `discovery2`, `glpi1` a `glpi6`, `geus`, `geus1`, `indicadores`, `indicadores1` a `indicadores4`, etc.). En su mayoría son `.copy()` defensivos no necesarios. Esto duplica el uso de memoria y dificulta seguir el flujo del código.

**Solución propuesta:**
- En PRISMA, encadenar transformaciones en pipelines (`df.pipe(...)` o method chaining).
- Documentar las copias estrictamente necesarias.

**Ganancia esperada:** Bajo en CPU, alto en memoria.

---

## 5. Issues secundarios detectados

### Bugs latentes y comportamientos inesperados

- **Bloque 105** (notebook 1): `geus['tiempoTranscurrido'] = '300'` — **confirmado por Fabián como intencional**. Corresponde a una fuente legacy fuera de soporte (datos GEUS anteriores a marzo 2025). En PRISMA debe documentarse explícitamente con un comentario claro y tratarse como un caso de borde manejado por el módulo correspondiente, no como un valor mágico hardcoded.
- **Bloque 58** (notebook 1): `np.random.choice(usuariosFinales)` se evalúa una sola vez por línea, no por cada fila. Todas las filas afectadas reciben el mismo valor "aleatorio", lo cual probablemente no es la intención.
- **Bloque 27**: `.str.replace('.','')` sin `regex=False` — en pandas reciente esto genera FutureWarning y trata el `.` como regex (cualquier carácter).
- **Bloque 129**: `indicadores.loc[..., "username_ufinal"] = 'Luis Francisco Muñoz'` — está asignando un nombre completo a una columna de username.
- **Bloques 199, 207**: Asignación sobre slice de DataFrame mayor → `SettingWithCopyWarning`.
- **Bloque 210**: Se reusa el mismo `label_encoder` para múltiples columnas, sobrescribiéndolo en cada iteración. Si se necesita decodificar después, los mapeos están perdidos.

### Seguridad

- **Credenciales hardcoded en texto plano** en Bloques 6, 7, 13, 32: tres conexiones SQL Server y una cuenta de servicio LDAP. Es un riesgo crítico.
- **Conexiones nunca se cierran** explícitamente.
- **Connection strings expuestos** si el notebook se publica accidentalmente.

### Calidad de código

- **Código duplicado** entre notebooks: los renombrados de columnas para incidentes/requerimientos/cambios/tareas son casi idénticos.
- **Catálogo de servicios incrustado en código:** ~80 reglas `df.loc[df["servicio"] == X, "servicio"] = Y`. En PRISMA va a `config/catalogo_servicios.yaml`.
- **Estandarización manual de usuarios:** decenas de líneas hardcoded del tipo `df.loc[df["usuariofinal"] == "X", "username_ufinal"] = "y"`. En PRISMA va a `config/excepciones_usuarios.yaml`.
- **Imports redundantes:** `from datetime import time, date, datetime` y luego `from datetime import datetime` otra vez. `import re` aparece dos veces.
- **Residuos de Jupyter:** `%matplotlib inline`, `display.max_columns = None`, `!pip install statsmodels` comentado.

### Trazabilidad

- No hay logging estructurado: solo `print(datetime.now())` esparcidos.
- No hay control de versiones del proceso.
- Sin manejo de errores: cualquier fallo deja el proceso a medias y los XLSX intermedios en estado inconsistente.

---

## 6. Análisis algorítmico — comparativo

| Operación | Implementación actual | Complejidad actual | Implementación PRISMA | Complejidad PRISMA |
|---|---|---|---|---|
| Mapear cédula→username vs Kactus | Doble `iterrows()` | O(N·M) | `.map(dict)` | O(N+M) |
| Completar `responsable` desde Kactus | Doble `iterrows()` | O(N·M) | `pd.merge` | O(N+M) |
| Resolver cédula vía LDAP | Loop con conexión por iteración | O(K) consultas red | Conexión persistente + filtro batch + cache | O(K/B) |
| `unidecode(aranda) in unidecode(glpi)` | Doble loop con normalización dentro | O(N·M) + O(N·M) `unidecode` | Pre-normalizar + `merge` | O(N+M) |
| Estandarización de servicios (~80 reglas) | 80× `.loc[mask, col] = X` | O(N·R) | `.replace(dict_mapping)` | O(N) |
| Escritura intermedia `.xlsx` | 25× `to_excel` | Lento | Parquet o eliminar | 5–20× más rápido |

(N = filas del DataFrame principal, M = filas del DataFrame de lookup, K = cédulas a resolver, B = tamaño del batch LDAP, R = número de reglas).

---

## 7. Riesgos y supuestos

**Riesgos identificados:**
1. **Credenciales hardcoded** son un incidente de seguridad latente.
2. El proceso es **idempotente solo en parte** — dependencias de orden y archivos en disco.
3. El **bug del Bloque 58** (random.choice una sola vez) puede estar afectando la integridad de los datos.
4. Las **dos URLs públicas de Google Sheets** son punto único de falla externo.
5. **Solapamiento entre `indicators1` y `provisionalASMS`**: ambos contienen casos Aranda ASMS. Power BI debe estar deduplicando o usándolos para visuales distintos. PRISMA debe respetar esta separación.

**Supuestos validados con Fabián:**
- ✅ Tiempo total de ejecución: 7m 11s.
- ✅ El `'300'` del Bloque 105 es intencional (fuente legacy fuera de soporte).
- ✅ Archivos finales que consume Power BI: `indicators1.xlsx`, `provisionalASMS.xlsx`, `tareas1.xlsx`.
- ✅ La `BITACORA` es un archivo manual mantenido aparte, fuera del alcance del refactor.

**Pendiente de aclarar:**
- Posibles campos adicionales que solicite Stefanini (impacto menor, ya contemplado en arquitectura).

---

## 8. Recomendaciones para Fase 2

La Fase 2 (profiling y diseño detallado) debe:

1. **Validar empíricamente** los cuellos de botella ejecutando el notebook actual con `cProfile` y `line_profiler`.
2. **Establecer línea base detallada** — desglose de los 6m53s del notebook 1 por sección.
3. **Validar suposición** sobre tiempo dominante de LDAP vs `iterrows` vs SQL vs Excel.
4. **Diseñar el módulo de identidades** con detalle de implementación.
5. **Construir fixtures anonimizados** para tests de paridad con notebook legacy.

---

*Documento mantenido como parte del versionado del proyecto PRISMA-GTI.*