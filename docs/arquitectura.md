# Arquitectura — PRISMA-GTI

**Versión:** 1.0
**Estado:** Diseño aprobado, en implementación

---

## 1. Contexto y motivación

PRISMA reemplaza un proceso manual basado en dos notebooks Jupyter (`ProyectoFinal3.ipynb` con 246 bloques y `Indicadores2026.ipynb` con 47 bloques) que se ejecutan célula por célula. El proceso actual presenta los siguientes problemas:

- **Operación manual** — requiere intervención humana celda por celda, con duración total ~7 minutos de CPU pero potencialmente horas de tiempo de operador.
- **Credenciales en texto plano** — tres conexiones SQL Server y una cuenta de servicio LDAP están hardcodeadas en el código.
- **Acoplamiento fuerte** — lógica de carga, transformación, modelado y escritura están entrelazadas en el mismo notebook.
- **Lógica duplicada** — el patrón de transformación de los CSVs de Aranda se repite entre los dos notebooks con pequeñas variaciones.
- **Cuellos de botella algorítmicos** — siete bucles `iterrows()` anidados con complejidad O(N·M) y consultas LDAP secuenciales con apertura/cierre de conexión por iteración.
- **Sin trazabilidad** — solo hay `print(datetime.now())` esparcidos; no hay logging estructurado ni manejo de errores.

PRISMA aborda estos problemas mediante una arquitectura modular, configuración externalizada, y separación clara de responsabilidades.

---

## 2. Principios de diseño

La arquitectura se rige por cinco principios:

1. **Separación de responsabilidades** — carga, transformación, escritura y orquestación viven en módulos distintos. Cada uno se puede testear de forma aislada.
2. **Configuración externa** — las reglas de negocio (mapeos de servicios, overrides de usuarios) viven en archivos YAML editables sin tocar código.
3. **Credenciales fuera del código** — todas las conexiones se autentican vía variables de entorno cargadas desde `.env`.
4. **Funciones puras donde sea posible** — los `transformers` reciben DataFrames y retornan DataFrames sin efectos colaterales, lo cual los hace triviales de testear.
5. **Idempotencia** — ejecutar el pipeline dos veces produce el mismo resultado. No hay estado escondido entre corridas.

---

## 3. Estructura del proyecto

```
prisma-gti/
│
├── pyproject.toml              # Metadata, dependencias, configuración de tooling
├── README.md                   # Guía de instalación y uso
├── .env.example                # Plantilla de variables de entorno
├── .gitignore                  # Excluye .env, /data, /output, __pycache__
│
├── config/
│   ├── settings.yaml           # Configuración general (rutas, fechas, batch sizes)
│   ├── catalogo_servicios.yaml # ~80 reglas de mapeo de servicios
│   ├── excepciones_usuarios.yaml # Overrides manuales username→nombre
│   └── logging.yaml            # Configuración de logging
│
├── src/prisma_gti/
│   ├── __init__.py
│   ├── cli.py                  # Punto de entrada CLI (typer)
│   │
│   ├── core/                   # Componentes transversales
│   │   ├── config.py           # Carga de YAML + variables de entorno
│   │   ├── logger.py           # Logger estructurado
│   │   ├── secrets.py          # Lectura segura de credenciales
│   │   └── exceptions.py       # Excepciones del dominio
│   │
│   ├── loaders/                # Una clase por fuente, todas heredan de BaseLoader
│   │   ├── base.py
│   │   ├── aranda_sql.py
│   │   ├── discovery_sql.py
│   │   ├── kactus_sql.py
│   │   ├── ldap_client.py
│   │   ├── glpi_csv.py
│   │   ├── geus_excel.py
│   │   ├── asms_csv.py
│   │   └── stefanini_csv.py
│   │
│   ├── identity/               # Resolución de identidades (cuello de botella crítico)
│   │   ├── resolver.py
│   │   ├── ldap_cache.py
│   │   ├── kactus_index.py
│   │   └── manual_overrides.py
│   │
│   ├── transformers/           # Transformaciones puras
│   │   ├── normalization.py
│   │   ├── service_catalog.py
│   │   ├── date_handling.py
│   │   ├── time_metrics.py
│   │   └── schema_align.py
│   │
│   ├── pipelines/              # Flujos de negocio
│   │   ├── historico.py        # → indicators1.xlsx
│   │   ├── stefanini.py        # → provisionalASMS.xlsx + tareas1.xlsx
│   │   └── ml_models.py        # Regresiones polinómica y logística
│   │
│   └── writers/                # Escritura de outputs
│       ├── excel.py
│       └── parquet.py
│
├── tests/
│   ├── unit/                   # Tests por módulo
│   ├── integration/            # Tests con fixtures reducidos
│   └── fixtures/               # Muestras anonimizadas
│
├── data/                       # Datos locales (gitignored)
│   ├── raw/                    # CSVs de entrada
│   ├── interim/                # Cachés en parquet
│   └── output/                 # Excels finales para Power BI
│
├── scripts/
│   ├── profile_pipeline.py     # cProfile + line_profiler
│   └── compare_outputs.py      # Validación contra notebook legacy
│
└── docs/
    ├── arquitectura.md         # Este documento
    ├── fase1_diagnostico.md
    ├── fase2_profiling.md
    └── runbook.md
```

---

## 4. Capas y responsabilidades

### 4.1 Capa `core/` — infraestructura transversal

Componentes utilizados por todas las demás capas. Responsable de:

- **Configuración:** cargar `settings.yaml`, validar contra un esquema, exponer un objeto `Settings` tipado.
- **Logging:** configurar el logger raíz con formato estructurado (JSON o texto enriquecido), niveles diferenciados por módulo.
- **Secrets:** leer `.env` con `python-dotenv` y exponer las credenciales como atributos tipados. Bloquea la ejecución si falta alguna credencial requerida.
- **Excepciones:** define `LoaderError`, `IdentityResolutionError`, `TransformerError`, `WriterError` para diferenciar fallos por capa.

### 4.2 Capa `loaders/` — adquisición de datos

Cada loader implementa una interfaz común:

```python
class BaseLoader(ABC):
    @abstractmethod
    def load(self) -> pd.DataFrame: ...
```

Los loaders **solo cargan** — no transforman. Devuelven el DataFrame con el esquema crudo de la fuente. Las transformaciones se hacen aguas abajo en la capa `transformers/`.

Loaders especiales:

- **`ldap_client.py`** — implementa la optimización clave: una sola conexión persistente reutilizada para todas las búsquedas, con cache local de cédula→sAMAccountName y filtros batch (`(|(employeeID=X)(employeeID=Y)...)`). Esto convierte el cuello de botella #1 (de minutos a segundos).
- **Loaders SQL** — encapsulan la conexión, manejan timeouts, y soportan parametrización por fecha de corte. Esto habilita la carga incremental como evolución futura.

### 4.3 Capa `identity/` — resolución de identidades

El componente más complejo del dominio. Su responsabilidad es resolver, para cada caso, la identidad real del usuario final y el responsable, cruzando información de múltiples fuentes.

Estrategia de resolución (en orden de prioridad):

1. **Si el campo `username_ufinal` ya está poblado y es válido** → no hacer nada.
2. **Si contiene una cédula (sólo dígitos)** → buscar en `kactus_index` (lookup O(1) en dict).
3. **Si Kactus no la tiene** → buscar en LDAP usando el cliente con cache.
4. **Si LDAP no la encuentra** → aplicar `manual_overrides` desde YAML.
5. **Si nada funciona** → marcar como no resuelto y continuar (no abortar el pipeline).

Esta capa es donde se concentra la mayor ganancia de rendimiento. La implementación legacy hace doble loop `iterrows()` con O(N·M); la implementación PRISMA usa diccionarios precomputados y operaciones vectorizadas con O(N+M).

### 4.4 Capa `transformers/` — transformaciones puras

Funciones que reciben DataFrames y retornan DataFrames. **Sin efectos colaterales, sin I/O, sin estado.** Esto las hace triviales de testear con fixtures.

Transformadores principales:

- **`normalization.py`** — `unidecode`, `strip`, `lower`, manejo de NaN.
- **`service_catalog.py`** — aplica el mapeo del YAML de catálogo (~80 reglas) usando `df['servicio'].replace(mapping_dict)` en una sola operación vectorizada.
- **`date_handling.py`** — conversión robusta de strings a datetime con manejo de errores.
- **`time_metrics.py`** — calcula `tiempoTranscurrido`, `tiempoTranscurridoAtencion`, `CUMPLE_ANS`, `CUMPLE_ANS_ATENCION`.
- **`schema_align.py`** — alinea esquemas heterogéneos antes de concatenar (ej. agregar columnas faltantes con NaN, reordenar).

### 4.5 Capa `pipelines/` — orquestación

Cada pipeline compone loaders + transformers + writers para producir un output específico. Los pipelines son los únicos módulos que tienen lógica de orquestación; el resto son piezas reutilizables.

- **`historico.py`** — orquesta la generación de `indicators1.xlsx` consolidando Discovery + Aranda (3 SP) + GLPI + GEUS + ASMS.
- **`stefanini.py`** — orquesta la generación de `provisionalASMS.xlsx` y `tareas1.xlsx` desde los CSVs de Stefanini.
- **`ml_models.py`** — entrena la regresión polinómica para predicción de cantidad de casos y la regresión logística para predicción de cumplimiento ANS. Consume `indicators1.xlsx` ya generado.

### 4.6 Capa `writers/` — escritura de outputs

Encapsula la lógica de escritura. Permite cambiar de formato sin afectar pipelines.

- **`excel.py`** — escribe los archivos finales que consume Power BI. Aplica el esquema correcto por archivo (las columnas y tipos esperados).
- **`parquet.py`** — usado para cachés intermedios entre etapas. Mucho más rápido que Excel para datasets grandes.

### 4.7 CLI (`cli.py`)

Punto de entrada construido con `typer`. Expone subcomandos que mapean a pipelines:

```
prisma run-historico       # → pipelines.historico
prisma run-stefanini       # → pipelines.stefanini
prisma run-all             # → ambos en secuencia
prisma run-models          # → pipelines.ml_models
prisma run-incremental     # → futuro: solo casos nuevos
```

Flags globales: `--config`, `--debug`, `--dry-run`, `--log-level`.

---

## 5. Flujo de datos end-to-end

### 5.1 Pipeline histórico (`run-historico`)

```
[SQL Aranda] ─┐
[SQL Discovery] ─┤
[SQL Kactus] ────┼──→ loaders/ ──→ identity/resolver ──→ transformers/ ──→ writers/excel ──→ indicators1.xlsx
[LDAP] ──────────┤                  (resuelve identidades)  (normaliza, mapea servicios)
[GLPI.csv] ──────┤
[GEUS.xlsx] ─────┤
[ASMS CSVs] ─────┘
```

### 5.2 Pipeline Stefanini (`run-stefanini`)

```
[Tareas.csv] ─────────┐
[*Stefanini.csv] ─────┼──→ loaders/ ──→ transformers/ ──→ writers/excel ──→ provisionalASMS.xlsx + tareas1.xlsx
                                         (calcula ANS atención,
                                          enriquece con columnas extra)
```

### 5.3 Pipeline ML (`run-models`)

```
indicators1.xlsx ──→ pipelines/ml_models ──→ predicciones2026.xlsx + indicadoresMX.xlsx
                     (regresión polinómica
                      + regresión logística)
```

---

## 6. Decisiones técnicas clave

### 6.1 ¿Por qué Pandas y no Polars?

Polars es más rápido y tiene mejor manejo de memoria. Sin embargo:

- El proyecto tiene 60K filas, no 60M. La diferencia de rendimiento no se siente.
- El ecosistema de testing y la familiaridad del equipo es mayor con Pandas.
- Los notebooks legacy están en Pandas — la migración es directa.
- `pyodbc` y `read_sql` están bien integrados con Pandas.

Si el volumen crece a millones de filas, migrar a Polars es viable porque la arquitectura aísla las transformaciones en módulos pequeños.

### 6.2 ¿Por qué `typer` y no `argparse` o `click`?

Typer da la mejor experiencia de desarrollo: type hints automáticos, validación de argumentos, ayuda autogenerada, y menos código boilerplate. Click es la base de Typer — usar Typer no impide acceder a Click si se necesita lógica más fina.

### 6.3 ¿Por qué configuración en YAML y no JSON o TOML?

YAML permite comentarios, lo cual es crítico para los catálogos editables por usuarios no técnicos. Fabián debe poder abrir `catalogo_servicios.yaml`, leer un comentario que explique qué hace cada sección, y agregar una nueva regla sin romper nada.

TOML se usa solo en `pyproject.toml` por ser el estándar de empaquetado Python.

### 6.4 ¿Por qué `.env` y no un vault corporativo?

Es un primer paso pragmático. Sacar las credenciales del código es la prioridad inmediata. Migrar a Azure KeyVault, HashiCorp Vault o equivalente es una mejora futura una vez que (a) el área tenga uno disponible, y (b) PRISMA esté estable en producción.

El `.env` queda en el servidor con permisos `chmod 600`, fuera del repo, y solo lo lee el proceso al arrancar.

### 6.5 ¿Por qué tanto módulo para un proyecto de 60K filas?

Es deliberado y discutible. La justificación es que el dolor del notebook legacy no es tanto el rendimiento como la mantenibilidad — y la mantenibilidad solo se compra con estructura. Para 60K filas y 7 minutos podríamos haber hecho un `main.py` plano de 800 líneas; pero ese `main.py` plano sería exactamente el notebook que estamos reemplazando, solo que sin las celdas.

Si en seis meses el negocio pide "agreguen una fuente nueva de Workday" o "cambien el cálculo del ANS", la diferencia entre la versión modular y la versión plana se mide en horas vs días.

---

## 7. Estrategia de testing

### 7.1 Tests unitarios (`tests/unit/`)

Cada `transformer` se testea con DataFrames sintéticos de 5-10 filas. Cada función de `identity/` se testea con diccionarios mock. Los `loaders/` se mockean en su totalidad (no se conecta a SQL ni LDAP en CI).

### 7.2 Tests de integración (`tests/integration/`)

Usan fixtures reducidos (~100 filas representativas, anonimizadas) que cubren los casos edge identificados en el notebook legacy: cédulas como username, IPs como username, nombres con tildes, responsables múltiples separados por `\n`, fechas en formatos heterogéneos, etc.

### 7.3 Test de paridad (`scripts/compare_outputs.py`)

El test de aceptación más importante: compara el output de PRISMA contra el output del notebook legacy ejecutado sobre el mismo input, fila por fila. PRISMA pasa la prueba cuando produce **exactamente** los mismos archivos `.xlsx` que el proceso actual (modulo orden de filas, que se ordena explícitamente para comparar).

Solo cuando este test pasa, PRISMA puede reemplazar al notebook legacy en producción.

---

## 8. Roadmap evolutivo

Una vez que PRISMA esté en paridad con el notebook legacy:

**Fase corto plazo (1-3 meses):**
- Migrar credenciales a vault corporativo.
- Programar ejecución automática (cron, Airflow, o Windows Task Scheduler).
- Notificaciones por correo/Teams ante fallos.

**Fase mediano plazo (3-6 meses):**
- Carga incremental: solo procesar casos nuevos desde la última corrida.
- Cache persistente de Kactus y diccionarios LDAP entre corridas.
- Métricas de calidad de datos (% de identidades resueltas, % de servicios mapeados).

**Fase largo plazo (6-12 meses):**
- API REST para que Power BI consuma directamente sin pasar por archivos Excel.
- Dashboard de monitoreo del pipeline (Grafana o similar).
- Modelos de ML como servicio independiente.

---

## 9. Glosario

- **GTI** — Gestión Tecnológica e Informática.
- **DOT** — Dirección de Operaciones Tecnológicas.
- **ITSM** — IT Service Management.
- **ANS** — Acuerdo de Nivel de Servicio (SLA).
- **ASMS** — Aranda Service Management Suite.
- **GEUS** — sistema legacy de gestión de usuarios.
- **GLPI** — herramienta open-source de mesa de ayuda.

---

*Documento mantenido por el equipo de PRISMA-GTI. Cualquier cambio significativo en la arquitectura debe reflejarse aquí antes de implementarse.*