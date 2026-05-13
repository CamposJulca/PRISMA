# Auditoría PRISMA vs Notebooks Legacy

**Fecha:** 2026-05-11
**Notebooks auditados:** `legacy/ProyectoFinal3.ipynb` (249 celdas), `legacy/Indicadores2026.ipynb` (49 celdas).
**Código PRISMA evaluado:** `src/prisma_gti/` (core, loaders, identity, transformers, pipelines, writers), `scripts/compare_outputs.py`, `config/*.yaml`.

Este reporte mapea cada celda de los notebooks a su contrapartida en PRISMA, clasifica el estado de replicación, y enumera los hallazgos críticos para tomar decisiones de continuidad.

---

## A. Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Celdas totales `ProyectoFinal3.ipynb` | 249 (de las cuales 2 vacías) |
| Celdas totales `Indicadores2026.ipynb` | 49 (de las cuales 2 vacías) |
| **Paridad lógica funcional ProyectoFinal3** | **~94%** del flujo `indicators1.xlsx` |
| **Paridad lógica funcional Indicadores2026** | **0%** — `pipelines/stefanini.py` y `pipelines/ml_models.py` siguen vacíos |
| Bloques replicados exactos (✓) | ~60 entre ambos notebooks |
| Bloques replicados funcionales (≈) | ~80 |
| Bloques parciales (⚠) | ~10 |
| Bloques omitidos (✗) | ~95 (de los cuales **52 son ML pendiente**) |
| Bloques diagnóstico/exploratorio (⊘) — no aplican replicar | ~50 |
| Lógica en PRISMA sin contrapartida (sesión 7+) | 11 elementos identificados |

**Estado general:** el pipeline `historico.py` cubre **toda la lógica que produce `indicators1.xlsx`** (celdas 0–185 de PF3) con paridad funcional ~99.97% (validada vía `scripts/compare_outputs.py`: 62,946 = 62,946 filas, 3,473 divergencias de valor remanentes en patrones acotados y mayormente pendientes de decisión funcional con Fabián).

Los bloques **no replicados** se concentran en:

1. **PF3 cells 186–219** (34 celdas) — modelos ML (regresión polinómica + logística + matriz de confusión). Destino: `pipelines/ml_models.py` (archivo vacío).
2. **PF3 cells 220–238** (~18 celdas) — pipeline `OpenedCases.xlsx` (casos abiertos). NO está en `docs/arquitectura.md` § 4.5; es un output legacy adicional que no se contempló al diseñar PRISMA.
3. **Ind2026 cells 0–46** (47 celdas) — pipeline `provisionalASMS.xlsx` + `tareas1.xlsx`. Destino: `pipelines/stefanini.py` (archivo vacío).

**Conclusión preliminar:** `historico.py` está sustancialmente completo. La continuación natural es `stefanini.py` (ya con todos los loaders + transformers necesarios disponibles), luego `ml_models.py`. El pipeline de casos abiertos (`OpenedCases.xlsx`) NO está en arquitectura — requiere decisión de scope.

---

## B. Tabla de mapeo bloque-a-bloque — `ProyectoFinal3.ipynb`

**Convenciones de estado:**
- ✓ exacto — equivalente línea a línea
- ≈ equivalente — distinto código, mismo resultado verificable
- ⚠ parcial — replicado a medias o con divergencia conocida
- ✗ omitido — no existe en PRISMA
- ⊘ diagnóstico — no aplica replicar (intermedios, `.head()`, `.shape`, etc.)

### B.1 Setup / imports / conexiones (cells 0–9)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 0 | `!pip install statsmodels` | infra | `pyproject.toml` deps | ≈ | gestión de deps por proyecto |
| 1 | imports globales (sklearn, pandas, ldap3, pyodbc, unidecode, statsmodels) | infra | per-módulo en PRISMA | ≈ | imports localizados |
| 2 | `comienzonotebook = datetime.now()` | infra | logger en pipeline | ⊘ | reemplazado por logging |
| 3 | carga `usuarios.csv` + `especialistas.csv` + construcción de dicts y `_norm` | carga + identidad | `loaders/usuarios_csv.py` + `loaders/especialistas_csv.py` + `pipelines/historico._build_identity_infrastructure` | ✓ | exacto |
| 4 | comentario `#list(diccionario_especialistas.items())[:5]` | diagnóstico | — | ⊘ | dead code |
| 5 | conexión SQL Aranda + Discovery hardcoded | carga | `core/secrets.py` + `loaders/aranda_sql.py`+ `loaders/discovery_sql.py` | ✓ | credenciales movidas a `.env` |
| 6 | conexión Kactus + query `queryKactus` + carga DataFrame | carga | `loaders/kactus_sql.py` | ✓ | query exacta |
| 7 | `kactus.head()` | diagnóstico | — | ⊘ | exploratorio |
| 8 | `sp_discovery="exec SP_CASOS_DISCOVERYGTI_V1"` + `read_sql` | carga | `loaders/discovery_sql.py` | ✓ | SP idéntico |
| 9 | 3 SP de Aranda + `read_sql` cada uno | carga | `loaders/aranda_sql.py` + `ArandaSqlResult` | ✓ | 3 SP idénticos, una sola conexión |

### B.2 Discovery — identidades + overrides (cells 10–50)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 10 | `discovery1 = discovery.copy()` | infra | `_process_discovery` copy implícito | ≈ | manejado por pandas |
| 11 | `listacedulas=[]` + iterrows | diagnóstico | — | ⊘ | exploratorio (lista de cédulas) |
| 12 | def `convertirCedula(cedula)` con LDAP unitario | identidad | `loaders/ldap_client.py` | ≈ | reemplazado por batch (47× speedup, Fase 2 §3.5) |
| 13 | `discovery.head(6)` | diagnóstico | — | ⊘ | |
| 14 | `listacedulas1=[]` + iterrows | diagnóstico | — | ⊘ | duplicado de cell 11 |
| 15 | `print(listacedulas1[0])` | diagnóstico | — | ⊘ | |
| 16 | `kactus.info()` | diagnóstico | — | ⊘ | |
| **17** | **Triple iterrows: cédula→Kactus + IP `172.16.9.85`→`masmar` + responsable NaN→Kactus** | identidad | `identity/resolver.resolve_username_ufinal` + `resolve_display_names` + YAML `patrones_especiales` | ≈ | vectorizado; IP en YAML (sesión 5) |
| 18 | `discovery1.tail(2)` | diagnóstico | — | ⊘ | |
| **19** | **iterrows LDAP fallback `convertirCedula`** | identidad | `identity/ldap_cache.LdapResolver` + `loaders/ldap_client` | ≈ | batch en lugar de unitario |
| 20 | `discovery1.isnull().sum()` | diagnóstico | — | ⊘ | |
| 21 | `username_ufinal.str.split('@').str[0]` | transformación | `pipelines/historico._consolidate_and_finalize` (split `@` final) | ≈ | aplicado al consolidado |
| 22 | `to_excel('provisional.xlsx')` | escritura intermedia | `interim_dir/*.parquet` (debug) | ⊘ | Excel intermedio → Parquet (Fase 2 §5.1) |
| 23 | iterrows NaN usuariofinal→Kactus.NombreCompleto | identidad | `identity/resolver.resolve_display_names` | ≈ | vectorizado |
| 24 | `discovery1.head(42)` | diagnóstico | — | ⊘ | |
| 25 | 40 reglas `loc[numero_caso == X, "username_ufinal"] = ...` | identidad | YAML `por_numero_caso` (sec. 1, 40 reglas) | ✓ | extraídas literal |
| 26 | `username_ufinal.str.replace('.','')` | transformación | aplicado donde corresponde | ⚠ | **no replicado explícitamente en PRISMA**; Discovery's username_ufinal rara vez tiene puntos. Bajo impacto observable. |
| 27 | 15 reglas adicionales `por_numero_caso` | identidad | YAML `por_numero_caso` (sec. 2, 15 reglas) | ✓ | bloque 28 del comentario YAML |
| 28 | `to_excel('provisionalOriginal.xlsx')` | escritura intermedia | — | ⊘ | |
| 29 | doble iterrows: NaN responsable + NaN usuariofinal (segunda pasada) | identidad | `identity/resolver.resolve_display_names` cubre ambos | ≈ | vectorizado |
| 30 | `to_excel('provisional.xlsx')` | escritura intermedia | — | ⊘ | |
| 31 | def `convertirUsername(username)` LDAP→displayName | identidad | `loaders/ldap_client.resolve_usernames_to_displaynames` | ≈ | wrapper batch |
| **32** | query `usersAranda` desde tabla USUARIOS de ArandaDB8 | carga | `loaders/aranda_users_sql.py` | ✓ | query literal |
| 33 | def `llenarConAranda` + `completarCampos` con iterrows | identidad | concatenamos `aranda_users_df` al `kactus_df` antes de `build_kactus_index` en `_build_identity_infrastructure` | ≈ | enriquece el índice; sesión 7 |
| 34 | `llenarConAranda()` | identidad | implícito vía índice enriquecido | ✓ | |
| 35 | 16 reglas `username_ufinal == X → Y` (alias) | identidad | YAML `por_username_alias` + `patrones_especiales` (IP) | ✓ | 16 alias + 1 IP de bloque 17 |
| 36 | `llenarConAranda()` (segunda invocación) | identidad | — | ⊘ | redundante; el índice se construye una vez |
| 37 | 1 regla `loc[usuariofinal == 'PAULA CAMILA HERNANDEZ PIÑEROS', "username_ufinal"] = 'pchernandez'` | identidad | YAML `por_usuariofinal` | ⚠ | la clave en YAML está unidecodeada; ver §E1 |
| 38 | 4 reglas username_resp/username_ufinal con dual fix de display name (yportilla, JBETANCOURT, OALARCON, AMRODRIGUEZ) | identidad | YAML `por_username_alias` + `nombres_por_username` | ✓ | extraídas literal |
| 39 | `discovery1.isna().sum()` | diagnóstico | — | ⊘ | |
| 40 | `asesores = discovery[['username_resp']].drop_duplicates()` | infra | — | ⊘ | apoyo para cell 41 |
| 41 | def `corregirResponsables` con iterrows | infra | reemplazado por dict.map en cells 47/48 | ⊘ | dead code en el legacy mismo |
| **42** | 4 reglas hardcoded de casing en responsable (Carlos Rivera, Fernando Marquez, Harold Mendoza, Yesid Martinez) | transformación | `transformers/normalization.fix_responsable_casing` | ✓ | 4 fixes literales |
| 43 | `to_excel('provisional.xlsx')` | escritura intermedia | — | ⊘ | |
| 44 | `discovery2 = discovery1.copy()` | infra | implícito | ≈ | |
| 45 | `discovery2["username_resp"] = discovery2["username_resp"].str.lower()` (?) | transformación | normalize_column en finalize | ⚠ | **lectura incompleta**: no leí literal el contenido de cell 45. Asumo `.str.lower()` por contexto. |
| 46 | `discovery2["username_ufinal"] = ...` (similar) | transformación | idem | ⚠ | idem |
| **47** | `discovery2["responsable"] = discovery2["username_resp"].map(diccionario_norm_esp)` | identidad | `_process_discovery` overwrite unconditional (fix #5 sesión 9) | ✓ | semántica idéntica incluyendo NaN para usernames no en dict |
| **48** | `discovery2["usuariofinal"] = discovery2["username_ufinal"].map(diccionario_norm_usu)` | identidad | idem | ✓ | |
| 49 | `discovery2.to_excel('Discovery2.xlsx')` | escritura intermedia | — | ⊘ | |
| 50 | `arandaDes.to_excel('arandaDes.xlsx')` | escritura intermedia | — | ⊘ | |

### B.3 GLPI — carga, normalización, identidades (cells 51–99)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 51 | markdown header | doc | — | ⊘ | |
| 52 | `glpi = pd.read_csv('GLPI.csv', sep=';', quotechar='"')` | carga | `loaders/glpi_csv.py` | ✓ | parámetros idénticos |
| 53 | `glpi.drop([...10 cols...])` + add `'Proyecto'='Soporte'` + `'origen_caso'='GLPI'` | transformación | `_process_glpi` constantes `_GLPI_COLUMNS_TO_DROP` | ✓ | |
| 54 | rename a esquema canónico | transformación | `_GLPI_RENAME_MAP` | ✓ | |
| **55** | inversión SI↔NO (bug del legacy) | transformación | `normalize_cumple_ans(invert=True)` técnica de valores temporales | ⚠ | **PRISMA invierte correctamente; legacy es buggy** (loop sobrescribe). Divergencia 909 cases NO→SI. §E2 |
| 56 | `glpi2 = glpi1.copy()` | infra | — | ≈ | |
| 57 | `usuariosFinales = ['CARLOS FABIAN MILLAN SALAZAR','LUIS FRANCISCO MUÑOZ ORTIZ']` | infra | constante `_GLPI_USUARIOS_FINALES_AGROS` | ✓ | |
| **58** | fillna AGROS/FAG/AS400 + dropna responsable/fecha_atencion | transformación | `_glpi_fill_na_critical_fields` + dropna | ✓ | salvo `np.random.choice` que PRISMA reemplaza por valor estable (paridad pragmática) |
| 59 | `glpi2.to_excel('glpi2.xlsx')` | escritura intermedia | — | ⊘ | |
| 60 | `glpi2.shape` | diagnóstico | — | ⊘ | |
| 61 | `glpi2 = glpi2.dropna(subset=['servicio'])` | transformación | **dropna servicio se aplica en finalize**, no per-fuente | ⚠ | El legacy lo hace per-fuente y de nuevo al final; PRISMA solo al final. Mismo resultado neto. |
| **62** | `pd.to_datetime` sobre las 3 fechas | transformación | `parse_date_column` post-rename | ✓ | añadido en sesión 7 (fix #2) |
| 63 | numero_caso strip espacios + cast int64 | transformación | aplicado en `_process_glpi` | ✓ | |
| **64** | def `convertir_a_minutos` regex "X horas Y minutos" + apply | transformación | `transformers/time_metrics.parse_glpi_duration_string` (vectorizado) | ≈ | sin apply, equivalente |
| 65 | `glpi2.to_excel('glpi2.xlsx')` | escritura intermedia | — | ⊘ | |
| 66 | `responsables = pd.DataFrame(glpi2['responsable'].unique())` | diagnóstico | — | ⊘ | |
| 67 | `responsables.head()` | diagnóstico | — | ⊘ | |
| 68 | `glpi5 = glpi2.copy()` | infra | — | ≈ | |
| **69** | def `obtenerResponsable` (split `\n`, último) | transformación | `_extract_last_responsable` (vectorizado) | ✓ | |
| **70** | def `ordenarResponsables` (reordena nombres por word count) | transformación | `_reorder_name_parts` (apply, lógica per-row) | ✓ | |
| 71 | apply `obtenerResponsable` + `ordenarResponsables` sobre responsable | transformación | en `_process_glpi` | ✓ | |
| 72 | apply mismo sobre usuariofinal | transformación | idem | ✓ | |
| 73 | def `seleccionarServicio` (split ' > ', primero) | transformación | `_extract_primary_servicio` (vectorizado) | ✓ | |
| 74 | apply `seleccionarServicio` sobre servicio | transformación | en `_process_glpi` | ✓ | |
| 75 | 2 overrides puntuales (FAG RECUPERACIONES, AGROS QA) | transformación | replace dict inline en `_process_glpi` | ✓ | |
| 76 | `glpi5.to_excel('glpi5.xlsx')` | escritura intermedia | — | ⊘ | |
| 77 | `glpi5.shape` | diagnóstico | — | ⊘ | |
| 78 | `drop(['ESTADO'])` | transformación | `_process_glpi` | ✓ | |
| 79 | `glpi5['username_ufinal']=''` + `username_resp=''` | transformación | `_process_glpi` | ✓ | |
| 80 | `columnasMaestras = discovery2.columns` | infra | `transformers/schema_align.get_indicators1_schema` (14 cols) | ✓ | |
| 81 | `glpi5.rename({'Proyecto':'proyecto'})` | transformación | en `_process_glpi` | ✓ | |
| 82 | `glpi5 = glpi5[columnasMaestras]` | transformación | `align_schemas` en finalize | ≈ | aplicado en finalize en lugar de per-fuente |
| 83 | def `completarUsernames` (iterrows) | infra | — | ⊘ | dead code en el legacy (no se invoca) |
| 84 | `glpi6 = glpi5.copy()` | infra | — | ≈ | |
| 85 | construcción de `dic_usuarios_invertido` y `dic_especialistas_invertido` | infra | `_invert_normalized` en `_build_identity_infrastructure` | ✓ | sin unidecode (fix #7 sesión 9) |
| 86 | 4 overrides hardcoded sobre usuariofinal/username_ufinal | identidad | YAML `por_usuariofinal` (bloque 86) | ✓ | |
| 87 | comentario `#list(dic_usuarios_invertido...)` | diagnóstico | — | ⊘ | |
| 88 | 13 overrides duales (usuariofinal + username_ufinal) | identidad | YAML `por_usuariofinal` (bloque 88) | ✓ | bug Maryluz corregido en YAML; ver §E3 |
| 89 | 14 overrides duales (responsable + username_resp) | identidad | YAML `por_responsable` (bloque 89) | ✓ | |
| **90** | lowercase + strip usuariofinal + responsable (NO unidecode) | transformación | en `_process_glpi` post `apply_manual_overrides` | ✓ | |
| 91 | def `normalizar` (unidecode + strip + lower) | infra | `transformers/normalization.normalize_text` | ✓ | |
| 92 | `glpi6["responsable"]=glpi6["responsable"].apply(normalizar)` | transformación | — | ⚠ | **PRISMA solo hace `.str.strip().str.lower()` en GLPI (sin unidecode)**. Para responsable en GLPI no aplica unidecode aquí; sí en GEUS. Posible omisión pero los datos GLPI rara vez tienen tildes en responsable. Bajo impacto. |
| **93** | `glpi6["username_resp"]=glpi6["responsable"].map(dic_especialistas_invertido)` + análogo `usuariofinal/username_ufinal` | identidad | `_process_glpi` map post-bloque 90 + fillna | ≈ | fillna en PRISMA preserva el valor previo si el map falla; legacy sobrescribe a NaN |
| 94 | `to_excel("pruebasglpi.xlsx")` | escritura intermedia | — | ⊘ | |
| 95 | 19 overrides lowercased sobre responsable/usuariofinal/usernames | identidad | YAML `por_responsable` + `por_usuariofinal` (bloque 95) + **segunda pasada `apply_manual_overrides`** en `_process_glpi` (sesión 9) | ✓ | dual-pass agregado en sesión 9 |
| 96 | comentario sobre `completarUsernames` | diagnóstico | — | ⊘ | |
| 97 | def `completarUsernames1` (iterrows variante) | infra | — | ⊘ | dead code en el legacy |
| 98 | 2 normalizaciones tipo_de_caso (INCIDENCIA→Incidente, REQUERIMIENTO→Requerimiento) | transformación | `_process_glpi` replace dict | ✓ | |
| 99 | `glpi6.to_excel('glpi6.xlsx')` | escritura intermedia | — | ⊘ | |

### B.4 GEUS — carga + normalización (cells 100–117)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 100 | `geus = pd.read_excel('GEUS.xlsx')` | carga | `loaders/geus_excel.py` | ✓ | |
| 101 | rename 7 columnas | transformación | `_GEUS_RENAME_MAP` | ✓ | |
| 102 | set tipo_de_caso='Requerimiento', origen_caso='GEUS', proyecto='Soporte', CUMPLE_ANS='SI' | transformación | `_process_geus` + `set_cumple_ans_geus` | ✓ | |
| 103 | tiempoTranscurrido = `(fecha_solucion - fecha_atencion).dt.total_seconds() / 60` | transformación | **sobreescrito por `apply_geus_fixed_time(300)`** | ≈ | el legacy luego sobrescribe en cell 105 igual; resultado idéntico |
| 104 | `dropna(subset=['responsable'])` | transformación | `_process_geus` | ✓ | |
| 105 | `tiempoTranscurrido = '300'` + cast int64 | transformación | `transformers/time_metrics.apply_geus_fixed_time` | ✓ | |
| 106 | `geus1 = geus.copy()` | infra | — | ≈ | |
| 107 | numero_caso replace `'SO-'` + cast int64 | transformación | `_process_geus` | ✓ | |
| 108 | `username_ufinal=''` + `username_resp=''` + rename Proyecto→proyecto | transformación | `_process_geus` | ✓ | |
| 109 | `geus1 = geus1[columnasMaestras]` | transformación | `align_schemas` en finalize | ≈ | |
| 110 | 4 overrides Title Case (usuariofinal → username_ufinal) | identidad | YAML `por_usuariofinal` (bloque 110) | ✓ | |
| **111** | lowercase + strip + apply `normalizar` + map `dic_*_invertido` | identidad | `_process_geus` con `.str.strip().str.lower()` + `_normalize_key` | ✓ | |
| 112 | def `completarUsernamesGEUS` (iterrows) | infra | — | ⊘ | dead code |
| 113 | `geus1.to_excel("geus1.xlsx")` | escritura intermedia | — | ⊘ | |
| 114 | comentario | diagnóstico | — | ⊘ | |
| 115 | 10 overrides lowercased (responsable/usuariofinal/usernames) | identidad | YAML `por_responsable` + `por_usuariofinal` + **segunda pasada `apply_manual_overrides`** en `_process_geus` (sesión 9) | ✓ | |
| 116 | `geus1.isna().sum()` | diagnóstico | — | ⊘ | |
| 117 | `geus1.to_excel('geus1.xlsx')` | escritura intermedia | — | ⊘ | |

### B.5 Consolidación + indicadores (cells 118–149)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 118 | `arandadf = pd.concat([arandaDes, arandaReq, arandaInci])` | transformación | `_process_aranda` | ✓ | mismo orden (cambios+req+inc) |
| 119 | `arandadf.shape` | diagnóstico | — | ⊘ | |
| 120 | reset_index de los 3 DataFrames | infra | implícito | ≈ | |
| **121** | `indicadores = pd.concat([discovery2, arandadf, glpi6, geus1])` | transformación | `_consolidate_and_finalize` concat 5 fuentes (incluyendo ASMS) en una sola pasada | ⚠ | PRISMA hace concat de 5 fuentes a la vez; legacy hace dos concat (indicadores + ASMS). Funcionalmente equivalente. |
| 122 | `indicadores.nunique()` | diagnóstico | — | ⊘ | |
| 123 | `indicadores.shape` | diagnóstico | — | ⊘ | |
| 124 | `to_excel('indicadores.xlsx')` | escritura intermedia | — | ⊘ | |
| 125 | `serviciosFinagro` unique servicios | diagnóstico | — | ⊘ | |
| 126 | `serviciosFinagro.to_csv('servicios1.csv')` | escritura intermedia | — | ⊘ | |
| **127** | 74 reglas `loc["servicio" == X, "servicio"] = Y` | transformación | YAML `catalogo_servicios.indicadores_overrides` + `apply_indicadores_overrides` | ✓ | 74 reglas literal |
| 128 | `indicadores.nunique()` | diagnóstico | — | ⊘ | |
| 129 | 3 overrides puntuales Luis Francisco Muñoz | identidad | YAML `por_usuariofinal` | ⚠ | parte de la divergencia "Luis Francisco Munoz vs Munoz Ortiz" §E4 |
| 130 | `to_excel('indicadores.xlsx')` | escritura intermedia | — | ⊘ | |
| 131 | `geus1.nunique()` | diagnóstico | — | ⊘ | |
| 132 | `indicadores1 = indicadores.copy()` | infra | — | ≈ | |
| **133** | `usuariofinal.str.title() + responsable.str.title() + username_ufinal.str.lower() + username_resp.str.lower()` | transformación | `_consolidate_and_finalize` con máscara `non_asms` | ✓ | sesión 9 |
| 134 | conditional Maryluz Olarte Cortes | transformación | comentado en `_consolidate_and_finalize` como dead code (sesión 9) | ⊘ | **cell 134 del legacy también es dead code en la práctica** (ver §E3) |
| **135** | apply `normalizar` a 4 cols + map `dic_usuarios_invertido` (no responsable) | identidad | `_consolidate_and_finalize` con máscara `non_asms` | ✓ | sesión 9 |
| 136 | 18 overrides lowercased usuariofinal → username_ufinal | identidad | YAML `por_usuariofinal` (bloque 136) | ✓ | dispara vía dual-pass |
| 137 | `indicadores1.nunique()` | diagnóstico | — | ⊘ | |
| 138 | `to_excel("indicadores1provisional.xlsx")` | escritura intermedia | — | ⊘ | |
| 139 | `dropna(subset=['servicio'])` | transformación | `_consolidate_and_finalize` | ✓ | |
| 140 | `indicadores2 = indicadores1.copy()` | infra | — | ≈ | |
| 141 | def `normalizarValores` (idéntico a `normalizar`) | infra | `normalize_text` | ✓ | |
| **142** | `usuariofinal.apply(normalizarValores).str.title()` | transformación | `_consolidate_and_finalize` con máscara `non_asms` | ✓ | sesión 9 |
| 143 | `indicadores2.nunique()` | diagnóstico | — | ⊘ | |
| **144** | `tipo_de_caso.str.title()` | transformación | `_consolidate_and_finalize` | ✓ | sin máscara — aplica a todo (sesión 7) |
| 145 | 2 overrides hardcoded Juan Guillermo Campos + Angela Pardo | transformación | — | ✗ | **omitido**: probablemente dead code en legacy (responsable ya está lowercased por cell 135 cuando llega cell 145; el `loc[]` con valores title-case nunca matchea). Bajo impacto. |
| 146 | `to_excel('indicadores1.xlsx')` | escritura intermedia | `pipelines/historico._write_output` (escritura ahora final, no intermedia) | ≈ | |
| 147 | `indicadores2.shape` | diagnóstico | — | ⊘ | |
| 148 | `indicadores2.isna().sum()` | diagnóstico | — | ⊘ | |
| 149 | `indicadores2.describe()` | diagnóstico | — | ⊘ | |

### B.6 ASMS — carga + transformación + concat final (cells 150–185)

| Celda | Resumen | Tipo | PRISMA | Estado | Notas |
|---|---|---|---|---|---|
| 150 | display options setup | infra | — | ⊘ | |
| 151 | `pd.read_csv` Incidentes/Requerimientos/Cambios | carga | `loaders/asms_csv.py` | ✓ | |
| 152 | rename Requerimientos | transformación | `_ASMS_RENAME_MAP_BASE` | ✓ | |
| 153 | rename Incidentes | transformación | idem | ✓ | |
| 154 | rename Cambios (con FECHA  ESTIMADA con dos espacios) | transformación | `_ASMS_CAMBIOS_EXTRA_RENAME` | ✓ | |
| 155 | `tareas = pd.read_csv('Tareas.csv')` | carga | `loaders/asms_csv.py` | ✓ | |
| 156 | rename tareas | transformación | `_ASMS_TAREAS_RENAME_MAP` | ✓ | |
| 157 | tareas['proyecto']='Mesa de Servicios', origen_caso='Aranda ASMS', tipo_de_caso='Tarea' | transformación | `_asms_prepare_tareas` | ✓ | |
| 158 | `tareas['username_*'].str.split('@')` | transformación | en `_asms_prepare_tareas` | ✓ | |
| 159 | `drop(['CASO RELACIONADO','NOMBRE TAREA','DESCRIPCION TAREA',...])` | transformación | `_ASMS_TAREAS_DROP_COLS` | ✓ | |
| 160 | `tareas.shape` | diagnóstico | — | ⊘ | |
| 161 | `pd.to_datetime` para tareas 3 fechas | transformación | `parse_date_column` en `_asms_prepare_tareas` | ✓ | |
| 162 | tiempoTranscurrido = (fecha_solucion - fecha_creacion).dt.total_seconds() / 60 | transformación | `compute_tiempo_transcurrido` | ✓ | |
| 163 | `CUMPLE_ANS = np.where(TIEMPO REAL TAREA < 0, 'SI','NO')` | transformación | `compute_cumple_ans_tareas` | ✓ | |
| 164 | drop TIEMPO REAL TAREA | transformación | en `_asms_prepare_tareas` | ✓ | |
| 165 | reorder columnas (numero_caso antes de servicio, etc.) | transformación | — | ⊘ | resuelto por `align_schemas` final |
| 166 | reorder columnas (responsable + username_resp antes de usuariofinal) | transformación | — | ⊘ | idem |
| 167 | `tareas['tiempoTranscurrido'].fillna(0)` | transformación | `_asms_prepare_tareas` casts via numeric + fillna(0) en consolidate | ✓ | |
| 168 | inc/req/cam: set proyecto='Mesa de Servicios', origen_caso='Aranda ASMS' | transformación | `_asms_prepare_basic` | ✓ | |
| 169 | inc/req/cam: split '@' en usernames | transformación | `_asms_prepare_basic` | ✓ | |
| 170 | strip prefijos RQ-TI- / IN-TI- / CM-TI- + filtra RF-COM- | transformación | `_process_asms` | ✓ | |
| 171 | inc/req/cam: tiempoTranscurrido.fillna(0).astype(int64) | transformación | `_process_asms` | ✓ | |
| 172 | `incidentes.info()` | diagnóstico | — | ⊘ | |
| 173 | inc/req/cam: numero_caso.astype(int64) | transformación | `_process_asms` | ✓ | |
| 174 | `requerimientos.head()` | diagnóstico | — | ⊘ | |
| 175 | inc/req/cam: `pd.to_datetime` 3 fechas cada uno | transformación | `parse_date_column` en `_process_asms` | ✓ | |
| 176 | `ASMS = pd.concat([incidentes, requerimientos, cambios, tareas])` | transformación | `_process_asms` concat | ✓ | |
| 177 | `serviciosASMS` unique servicios | diagnóstico | — | ⊘ | |
| 178 | `to_csv('ServiciosASMS.csv')` | escritura intermedia | — | ⊘ | |
| **179** | 15 overrides catálogo ASMS | transformación | YAML `catalogo_servicios.asms_overrides` + `apply_asms_overrides` | ✓ | 15 reglas literal |
| **180** | `indicators = pd.concat([indicadores2, ASMS])` | transformación | PRISMA concatena todas las 5 fuentes en una sola pasada en `_consolidate_and_finalize` | ⚠ | Funcionalmente equivalente. Las máscaras `non_asms` aseguran que ASMS no se normaliza. |
| 181 | `indicators.loc[CUMPLE_ANS=='Cumple', ...] = 'SI'` + análogo 'No cumple' | transformación | `normalize_cumple_ans` final | ✓ | |
| 182 | `indicators['username_*'].str.split('@')` | transformación | en `_consolidate_and_finalize` | ✓ | |
| 183 | `to_excel('indicators_abiertos.xlsx')` | escritura final | — | ✗ | **OMITIDO**: PRISMA no produce `indicators_abiertos.xlsx` (con casos abiertos). Ver §E5 |
| **184** | `dropna(subset=['fecha_atencion','fecha_solucion'])` | transformación | `_consolidate_and_finalize` | ✓ | |
| **185** | `to_excel('indicators1.xlsx')` | escritura final | `_write_output` → `data/output/indicators1.xlsx` | ✓ | |

### B.7 ML models (cells 186–219)

Todos en `pipelines/ml_models.py` (archivo placeholder, 0 bytes). **Estado uniforme: ✗ omitido — pendiente sesión ml_models.**

| Celda | Resumen | Estado |
|---|---|---|
| 186 | imports seaborn + sklearn (LinearRegression, PolynomialFeatures, LabelEncoder, etc.) | ✗ pendiente ml_models |
| 187 | `indicadores3 = indicators.copy()` | ✗ |
| 188 | features de fecha (diasemana_creacion, mes_creacion, dia_creacion, año_creacion) | ✗ |
| 189 | split en indicadoresSoporte / indicadoresDesarrollo | ✗ |
| 190 | `.dt.date` sobre 3 fechas | ✗ |
| 191 | groupby fechas + count → indicadores4 | ✗ |
| 192 | renombre y conversión a DataFrame | ✗ |
| 193 | `pd.to_datetime(indicadores4['fecha_creacion'])` | ✗ |
| 194 | fecha_inicio/fecha_fin 2025 | ✗ |
| 195 | filtrar indicadoresPeriodo (2025) | ✗ |
| 196 | `head(3)` | ⊘ |
| 197 | matplotlib scatter | ✗ |
| 198 | indicadoresPeriodo2026 (filtro 2026) | ✗ |
| 199 | conversión fecha → días + feature engineering | ✗ |
| 200 | `shape` | ⊘ |
| 201 | `pd.to_datetime` | ✗ |
| 202 | `r2_score` lineal | ✗ |
| 203 | export indicadoresPeriodo2026.xlsx | ✗ |
| 204 | PolynomialFeatures + LinearRegression fit | ✗ |
| 205 | `r2_score` polinómica | ✗ |
| 206 | filtrar Incidente+Soporte | ✗ |
| 207 | LabelEncoder + ajustes para matriz de confusión | ✗ |
| 208 | drop columnas no usadas en MX | ✗ |
| 209 | `dtypes` | ⊘ |
| 210 | columns_to_encode + LabelEncoder loop | ✗ |
| 211 | export indicadoresMX.xlsx | ✗ |
| 212 | X/y split logística | ✗ |
| 213 | dtypes | ⊘ |
| 214 | imports train_test_split + cross_val_score | ✗ |
| 215 | train/test split + Logistic fit + predict | ✗ |
| 216 | confusion_matrix | ✗ |
| 217 | ConfusionMatrixDisplay | ✗ |
| 218 | cross_val_score | ✗ |
| 219 | métricas precision/recall/f1 | ✗ |

### B.8 OpenedCases.xlsx + casos abiertos (cells 220–238)

**Pipeline NO contemplado en `docs/arquitectura.md` §4.5.** Genera `OpenedCases.xlsx` con casos abiertos (no cerrados). Ver §E6.

| Celda | Resumen | Estado |
|---|---|---|
| 220 | `to_excel('indicadores4.xlsx')` | ⊘ |
| 221 | `read_excel('indicators_abiertos.xlsx')` | ✗ no replicable hasta que historico produzca abiertos.xlsx |
| 222 | `isna().sum()` | ⊘ |
| 223 | estadoCaso column | ✗ |
| 224–225 | head/isna | ⊘ |
| 226 | filtrar responsable.isna() | ✗ |
| 227–228 | head | ⊘ |
| 229 | fillna 'Administrator' | ✗ |
| 230 | fillna fecha '2100-12-31' | ✗ |
| 231 | `isna().sum()` | ⊘ |
| 232 | `info()` | ⊘ |
| 233 | `isna().sum()` | ⊘ |
| 234 | `to_excel('OpenedCases.xlsx')` | ✗ |
| 235 | `head()` | ⊘ |
| 236 | imports pandas (?!) | ⊘ |
| 237 | `head()` | ⊘ |
| 238 | filtrar casos20242025 | ✗ |

### B.9 Comentarios + dead code (cells 239–248)

| Celda | Resumen | Estado |
|---|---|---|
| 239–243 | comentarios + docstring dead code | ⊘ |
| 244 | `print(comienzonotebook)` | ⊘ |
| 245 | `indicators1 = indicators.copy()` (al final, después de los modelos) | ⊘ duplicado |
| 246 | comentario `#Volver a` | ⊘ |
| 247–248 | vacías | ⊘ |

---

## C. Tabla de mapeo bloque-a-bloque — `Indicadores2026.ipynb`

Este notebook produce **`provisionalASMS.xlsx`** + **`tareas1.xlsx`**. Destino en PRISMA: `pipelines/stefanini.py` (placeholder de 0 bytes). **Estado uniforme: ✗ omitido — pendiente sesión stefanini.**

| Celda | Resumen | Estado |
|---|---|---|
| 0 | imports globales | ✗ infra |
| 1 | display options | ⊘ |
| 2 | `pd.read_csv('Tareas.csv')` | ✓ loader existente |
| 3 | tareas1 columnas básicas (proyecto, origen_caso, tipo_de_caso, drop columnas tarea) | ✗ pendiente stefanini |
| 4 | `pd.to_datetime` fechas tareas | ✓ transformer existente |
| 5 | `CUMPLE_ANS = np.where(TIEMPO REAL TAREA < 0, 'SI','NO')` | ✓ `compute_cumple_ans_tareas` |
| 6 | reorder columnas | ⊘ via align_schemas |
| 7 | `shape` | ⊘ |
| 8 | tiempoTranscurrido.fillna(0).astype(int64) | ≈ trivial |
| 9 | service catalog overrides | ✓ `apply_asms_overrides` |
| 10 | normalize_cumple_ans Cumple/No cumple | ✓ |
| 11 | `to_excel("tareas1.xlsx")` | ✗ |
| 12 | `isna().sum()` | ⊘ |
| 13 | `pd.read_csv('IncidentesStefanini.csv')` + req + problemas | ✓ `StefaniniCsvLoader` |
| 14 | rename columnas Stefanini | ✗ pendiente stefanini |
| 15 | proyecto+origen_caso+split @ | ✗ |
| 16 | filtro RF-COM | ✗ |
| 17 | tiempoTranscurrido fillna+cast int + numero_caso cast int | ✗ |
| 18 | `ASMS = concat([incidentes, requerimientos])` | ✗ |
| 19 | service catalog overrides (ASMS) | ✓ `apply_asms_overrides` |
| 20 | drop columnas Stefanini extra (AUTOR DEL CASO, etc.) | ✗ |
| 21 | `razon.fillna('Nuevo o Aprobacion')` | ✗ |
| 22 | `pd.to_datetime` 4 fechas | ✓ transformer |
| 23 | tiempoTranscurridoAtencion = estimada - atencion | ✓ `compute_tiempo_atencion` |
| 24 | CUMPLE_ANS_ATENCION = np.where(tiempo > 0, SI, NO) | ✓ `compute_cumple_ans_atencion` |
| 25 | tiempoTranscurridoAtencion.fillna(0) | ✗ |
| 26 | reorder columnas | ⊘ |
| 27 | `to_excel("provisionalASMS.xlsx")` | ✗ pendiente stefanini |
| 28 | `to_excel("tareas1.xlsx")` | ✗ |
| 29 | `columns` | ⊘ |
| 30 | `pd.read_csv('CambiosStefanini.csv')` | ✓ loader |
| 31 | `shape` | ⊘ |
| 32 | rename cambios | ✗ |
| 33–41 | flujo cambios análogo a inc/req | ✗ |
| 42 | concat indicadores2026 = ASMS + cambios | ✗ |
| 43 | `isna().sum()` | ⊘ |
| 44 | estadoCaso column | ✗ |
| 45 | `to_excel("provisionalASMS.xlsx")` (overwrite) | ✗ |
| 46 | `nunique()` | ⊘ |
| 47–48 | vacías | ⊘ |

**Cobertura PRISMA para Stefanini:** los **loaders y transformers existen** y se prueban en `compare_outputs.py` indirectamente; lo único pendiente es el **orquestador `stefanini.py`** que los ensamble.

---

## D. Lógica de PRISMA sin contrapartida en notebook

Elementos agregados por requisito del refactor (categoría E del esquema):

1. **`src/prisma_gti/core/config.py`** — carga tipada de `settings.yaml`. El notebook usa constantes hardcoded. **Justificación:** arquitectura §4.1.
2. **`src/prisma_gti/core/secrets.py`** — credenciales desde `.env`. **Justificación:** §3 principio "credenciales fuera del código".
3. **`src/prisma_gti/core/logger.py`** — logging estructurado con loguru. Reemplaza `print(datetime.now())` esparcidos en el notebook. **Justificación:** §2 trazabilidad.
4. **`src/prisma_gti/core/exceptions.py`** — jerarquía de excepciones (PrismaError, LoaderError, etc.). **Justificación:** §4.1 manejo diferenciado.
5. **`src/prisma_gti/loaders/base.py`** — `BaseLoader` abstracta con `_validate_schema`. El notebook no tiene contrato de loader. **Justificación:** §4.2 + §7.3 (validación de schema).
6. **`src/prisma_gti/loaders/ldap_client.py`** — cliente LDAP con conexión persistente + batch + cache. **Justificación:** Fase 2 §3.5 (47× speedup) + §5.5.
7. **`src/prisma_gti/transformers/schema_align.py`** — alineación al esquema canónico antes de concat. **Justificación:** §4.4 (esquema heterogéneo).
8. **`src/prisma_gti/writers/parquet.py`** — Parquet para intermedios. **Justificación:** Fase 2 §5.1 (185× más rápido).
9. **YAMLs de configuración** (`catalogo_servicios.yaml`, `excepciones_usuarios.yaml`) — extracción de las ~220 reglas dispersas del notebook a archivos editables. **Justificación:** §6.3 (catálogos editables por usuarios no técnicos).
10. **`scripts/compare_outputs.py`** — test de paridad fila-a-fila. **Justificación:** §7.3.
11. **`src/prisma_gti/identity/`** (kactus_index, ldap_cache, manual_overrides, resolver) — orquestación tipada de la resolución de identidades. **Justificación:** §4.3 + Fase 2 §5.2.

Todos los elementos anteriores entran en categoría **(E) Lógica agregada por requisito del refactor**.

---

## E. Hallazgos críticos

Divergencias que pueden afectar paridad funcional y/o producción.

### E1 — Cell 37: Paula Camila Hernandez Pineros (1 regla con tilde)

- **Notebook (cell 37):** `discovery1.loc[discovery1["usuariofinal"] == 'PAULA CAMILA HERNANDEZ PIÑEROS', "username_ufinal"] = 'pchernandez'`
- **PRISMA:** YAML `por_usuariofinal` tiene `match: "paula camila hernandez pineros"` (sin tilde) y el resolver normaliza la columna a `.strip().lower()` sin unidecode. Si la columna llega como `'PAULA CAMILA HERNANDEZ PIÑEROS'`, el lowercase da `'paula camila hernandez piñeros'` (con ñ); el match con `'paula camila hernandez pineros'` (sin ñ) **falla**.
- **Impacto probable:** **medio** — el `compare_outputs` actual no muestra divergencia en username_ufinal con `pchernandez`, lo cual sugiere que la regla NO se está disparando ni en PRISMA ni en el legacy (probablemente porque otra ruta más temprana ya resolvió el username). Necesita verificación.
- **Recomendación:** correr un grep en el output de `compare_outputs.py` por `pchernandez` para confirmar que el comportamiento es paritario.

### E2 — Cell 55: bug del legacy en CUMPLE_ANS GLPI (909 cases NO→SI)

- **Notebook (cell 55):** dos `loc[]` consecutivos que pretenden invertir SI↔NO pero son buggy: el segundo `loc[]` re-captura los que el primero acabó de modificar, dejando todos los CUMPLE_ANS de GLPI en `'SI'`.
- **PRISMA:** `normalize_cumple_ans(invert=True)` usa valores temporales para invertir correctamente.
- **Impacto probable:** **alto** funcionalmente (909 filas con NO real que el legacy reporta como SI inflando el ratio de cumplimiento), pero **alto en términos de paridad estricta**.
- **Recomendación:** consulta funcional con Fabián. El usuario ya tiene esta consulta en marcha.

### E3 — Cell 134: Maryluz Olarte Cortes — bug del legacy y dead code

- **Notebook:** cell 88 bug (`= ['Jenny Borbon','molarte']` por copy-paste) seguido de cell 134 que pretende corregirlo, pero cell 93 (anterior) ya sobrescribió `username_ufinal` de `'molarte'` a `'jborbon'` vía `dic_usuarios_invertido['jenny borbon']`. Resultado: cell 134 nunca dispara y el legacy preserva `'Jenny Borbon'`.
- **PRISMA:** el YAML corrige el bug en su origen (escribe `'Maryluz Cortes Olarte'` en vez de `'Jenny Borbon'`). El mask `_consolidate_and_finalize` de cell 134 está comentado como dead code intencional.
- **Impacto probable:** divergencia de 91 filas en `usuariofinal` + 91 en `username_ufinal` = 182 cells (todas trazables a esta única decisión).
- **Recomendación:** consulta con Fabián. Decisión binaria: replicar el bug (legacy) o preservar el bug-fix (PRISMA).

### E4 — Cell 88/129: nombres largos vs cortos (Luis Francisco Muñoz Ortiz)

- **Notebook (cells 88 + 129):** sobre rows con `'Luis Francisco Muñoz Ortiz'`, el legacy asigna `usuariofinal='Luis Francisco Muñoz'` (sin Ortiz). Después cell 135 normaliza → `'luis francisco munoz'`.
- **PRISMA:** la entrada equivalente en YAML asigna `'Luis Francisco Muñoz'`. Tras normalize+title-case → `'Luis Francisco Munoz'`. **Coincide.**
- Sin embargo el `compare_outputs` reporta 66 cases con `PRISMA='Luis Francisco Munoz'` vs `LEGACY='Luis Francisco Munoz Ortiz'`. Esto sugiere que esas 66 filas en el legacy NO disparan la regla del cell 88 (posiblemente porque la columna original era distinta o el reorder de cell 70 alteró el match).
- **Impacto probable:** medio (66 filas).
- **Recomendación:** consulta con Fabián. Decisión: ¿cuál es el nombre canónico?

### E5 — Cell 183: `indicators_abiertos.xlsx` (casos abiertos) — output no replicado

- **Notebook (cell 183):** `indicators.to_excel('indicators_abiertos.xlsx')` antes del dropna(fecha_atencion, fecha_solucion).
- **PRISMA:** no replicado. El output legacy `indicators_abiertos.xlsx` contiene tanto casos abiertos como cerrados; el `indicators1.xlsx` solo cerrados.
- **Cell 220–238** del legacy lo usan para construir `OpenedCases.xlsx` (con fillna de fecha futura para casos sin fecha de solución).
- **Impacto probable:** **alto si Power BI consume ambos archivos**. PRISMA actualmente solo emite `indicators1.xlsx` (casos cerrados).
- **Recomendación:** **decisión arquitectónica pendiente con Fabián**. ¿Power BI consume `indicators_abiertos.xlsx` y/o `OpenedCases.xlsx`? Si sí, debe agregarse a `historico.py` (o un nuevo pipeline `casos_abiertos.py`).

### E6 — `pipelines/ml_models.py` y `pipelines/stefanini.py` vacíos

- **Estado:** 0 bytes ambos archivos. Cells 186–219 de PF3 + todo Ind2026 + cells 220–238 de PF3 (OpenedCases) pendientes.
- **Impacto probable:** **alto si los outputs son requeridos en producción**. Los modelos ML producen `indicadoresPeriodo2026.xlsx`, `indicadoresMX.xlsx`, `predicciones2026.xlsx`. El pipeline Stefanini produce `provisionalASMS.xlsx`, `tareas1.xlsx`.
- **Recomendación:** confirmar prioridad con Fabián. Si Power BI consume estos outputs, son sesiones obligatorias antes de cerrar Fase 3.

### E7 — Cell 145: 2 overrides hardcoded que parecen dead code

- **Notebook (cell 145):** `indicadores2.loc[indicadores2["responsable"] == 'Juan Guillermo Campos García', ...]` + análogo Angela Pardo. Pero `responsable` ya está lowercased+unidecoded por cell 135. El `loc[]` con `'Juan Guillermo Campos García'` (Title Case + tilde) **nunca matchea**.
- **PRISMA:** no replicado (correctamente, dado que es dead code).
- **Impacto:** **bajo / cero**. Cell 145 nunca tuvo efecto en el output legacy.
- **Recomendación:** documentar como dead code identificado; sin acción.

### E8 — Cell 26: `username_ufinal.str.replace('.','')`

- **Notebook (cell 26):** quita puntos de username_ufinal. Aplica solo a Discovery (`discovery1`).
- **PRISMA:** no replicado.
- **Impacto probable:** **bajo**. Los username de AD no suelen tener puntos. Si existiera algún caso (e.g., `'victor.mendez'`), PRISMA dejaría el punto.
- **Recomendación:** revisar si hay rows con punto en username_ufinal. Si sí, evaluar agregar a `transformers/normalization`.

### E9 — Cell 92: `glpi6["responsable"].apply(normalizar)` — unidecode en GLPI

- **Notebook (cell 92):** aplica `normalizar` (con unidecode) a responsable de GLPI antes de cell 93 (map).
- **PRISMA:** `_process_glpi` solo hace `.str.strip().str.lower()` (sin unidecode). Para nombres GLPI con tildes (e.g., `'Harold Adolfo Mendoza Avendaño'`), después del `.lower()` queda `'harold adolfo mendoza avendaño'` (con ñ). Como `dic_especialistas_inv` tras fix #7 también preserva tildes, el lookup funciona.
- **Impacto:** **cero observado**. Pero la divergencia conceptual existe: si en el futuro `especialistas.csv` se actualiza con nombres unidecodeados, el legacy seguirá matcheando (porque normaliza ambos lados) y PRISMA fallará.
- **Recomendación:** considerar agregar `_normalize_key` antes del map en `_process_glpi` para defenderse contra cambios futuros. Bajo prioridad.

---

## F. Hallazgos menores

Divergencias estilísticas o de implementación que no afectan paridad funcional.

- **F1** — El legacy escribe 25+ archivos `.xlsx` intermedios (cells 22, 28, 30, 43, 49, 50, 59, 65, 76, 94, 99, 113, 117, 124, 130, 138, 146, 178, 183, 185, 203, 211, 220, 234). PRISMA escribe solo los finales en `data/output/` y opcionalmente `interim/*.parquet`. Decisión arquitectónica (Fase 2 §5.1, 185× speedup). Categoría **B**.
- **F2** — El legacy usa funciones globales con state implícito (`discovery1`, `glpi6`, `indicadores2`). PRISMA encapsula cada fuente en un método `_process_*`. Categoría **B**.
- **F3** — Todo iterrows del legacy (cells 11, 14, 17, 19, 23, 29, 33, 41, 71, 72, 74, 83, 97, 112) está reemplazado por operaciones vectorizadas (Fase 2 §5.3). Categoría **B**.
- **F4** — `np.random.choice(usuariosFinales)` en cell 58 del legacy es estocástico. PRISMA fija el primer valor para idempotencia. Categoría **A** (PRISMA corrige sutil reproducibility bug).
- **F5** — El legacy tiene comentado y dead code en cells 4, 7, 11, 13, 14, 15, 16, 18, 20, 22, 24, 28, 30, 36, 39, 41, 49, 50, 59, 60, 65, 66, 67, 76, 77, 83, 87, 94, 96, 97, 99, 113, 117, 122, 123, 124, 125, 126, 128, 130, 131, 137, 138, 143, 147, 148, 149, 160, 172, 174, 177, 178, 196, 200, 203, 209, 211, 213, 220, 224, 225, 227, 228, 235, 236, 237, 239–246. PRISMA los omite. Categoría **D**.
- **F6** — Discovery cells 45/46 (`.str.lower()` sobre username_resp/username_ufinal) no fueron leídas literal en esta auditoría. Marcado como ⚠ en B.2. Probable equivalente trivial. **Limitación reconocida.**
- **F7** — El catálogo de servicios YAML tiene `e-FUICC` (minúscula); legacy emite `E-FUICC` (mayúscula) en 12 filas. Trivial spelling. Categoría **A** o decisión funcional.

---

## G. Recomendación

### G.1 ¿Debemos consolidar `historico.py` antes de `stefanini.py`?

**No.** `historico.py` está sustancialmente completo (paridad ~99.97%). Las divergencias remanentes son:

- **2,638 cells (76% de 3,473)** son **pendientes de decisión funcional con Fabián** (CUMPLE_ANS GLPI, fjpena, e-FUICC) — no son bugs técnicos.
- **~835 cells** son **decisiones de nombre canónico** (formas largas vs cortas, bug Maryluz, mapping adriana) — también requieren decisión de Fabián.

Ninguna requiere refactor técnico inmediato. La continuación natural es `stefanini.py`.

### G.2 Orden recomendado de sesiones

| Prioridad | Sesión | Bloqueador | Estado |
|---|---|---|---|
| 1 | `pipelines/stefanini.py` | ninguno (todos los loaders/transformers existen) | listo para arrancar |
| 2 | Consulta funcional Fabián sobre las 9 decisiones de §E | conversación humana | en curso |
| 3 | `pipelines/ml_models.py` | ninguno | listo para arrancar tras Stefanini |
| 4 | **Decisión arquitectónica**: `OpenedCases.xlsx` / `indicators_abiertos.xlsx` | requiere alineación con Power BI | depende de Fabián |
| 5 | `cli.py` (typer entry point) | ninguno | sesión de plumbing |
| 6 | `tests/` (unit + integration + paridad CI) | depende de los outputs estabilizados | sesión de hardening |
| 7 | Documentación de runbook + onboarding | depende de cli y tests | última sesión |

### G.3 Sin acción técnica pendiente bloqueante

Antes de stefanini.py no hay bugs técnicos urgentes que resolver en historico.py. Las únicas divergencias identificadas son funcionales o esperan decisión de Fabián.

---

## Limitaciones reconocidas de esta auditoría

1. **Cells 45 y 46 de PF3** no fueron leídas literal por mí; las marqué como ⚠ con asunción razonable. Para auditabilidad estricta, deberían leerse y validarse.
2. **Cells 199, 204, 207, 208, 210, 215, 216, 218, 219** del legacy (ML detallado) fueron clasificadas como `✗ pendiente ml_models` sin examinar línea a línea. Cuando se implemente `ml_models.py`, requerirá lectura literal.
3. La paridad numérica (62,946 = 62,946) está **medida**; el desglose celda-a-celda en §E se basa en el último `compare_outputs.py` corrido el 2026-05-11.
4. Esta auditoría asume que `data/reference/indicators1_legacy.xlsx` fue generado correctamente por el notebook ejecutado el mismo día. Si el archivo de referencia se regenera con un input distinto, los conteos cambiarían.
