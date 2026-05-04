# PRISMA-GTI

**Plataforma de Reportes e Indicadores de Servicios y Mesa de Atención**

Pipeline ETL para la consolidación de indicadores de gestión tecnológica de FINAGRO. Reemplaza el proceso manual basado en notebooks Jupyter (`ProyectoFinal3.ipynb` + `Indicadores2026.ipynb`) por un script CLI modular, automatizable y trazable.

---

## ¿Qué hace?

PRISMA consolida casos de servicio (incidentes, requerimientos, cambios y tareas) provenientes de cinco fuentes heterogéneas:

- **Aranda ITSM** (SQL Server) — Discovery, ASMS, usuarios.
- **Active Directory** (LDAP) — resolución de identidades.
- **Kactus** (SQL Server) — datos de empleados.
- **GLPI**, **GEUS** y **Stefanini** — archivos CSV/Excel.

Produce los datasets que alimentan el dashboard de Power BI del área:

- `indicators1.xlsx` — dataset histórico consolidado (todos los orígenes).
- `provisionalASMS.xlsx` — dataset enriquecido específico de Aranda ASMS.
- `tareas1.xlsx` — dataset de tareas Aranda 2026.

---

## Estructura del proyecto

```
prisma-gti/
├── config/         # YAML de configuración y catálogos editables sin código
├── src/prisma_gti/ # Código fuente
│   ├── core/       # Configuración, logging, secrets, excepciones
│   ├── loaders/    # Una clase por fuente de datos
│   ├── identity/   # Resolución de identidades (Kactus + LDAP + overrides)
│   ├── transformers/ # Transformaciones puras sobre DataFrames
│   ├── pipelines/  # Orquestación de los flujos de negocio
│   └── writers/    # Escritura de outputs (Excel, Parquet)
├── tests/          # Tests unitarios e integración
├── scripts/        # Profiling y comparación con notebook legacy
├── docs/           # Documentación por fases del proyecto
└── data/           # Datos locales (gitignored)
```

Para detalles de la arquitectura, ver [`docs/arquitectura.md`](docs/arquitectura.md).

---

## Instalación

### Requisitos previos

- Python 3.11 o superior.
- ODBC Driver 17 for SQL Server.
- Acceso de red al servidor SQL `172.16.20.70` y al LDAP `172.16.0.5:389`.

### Pasos

```bash
# Clonar el repositorio
git clone <url-repo-finagro>/prisma-gti.git
cd prisma-gti

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -e .

# Configurar credenciales (copiar y editar)
cp .env.example .env
# Editar .env con las credenciales reales (ver sección Configuración)
```

---

## Configuración

PRISMA separa la configuración en tres capas:

1. **Variables de entorno** (`.env`) — credenciales y rutas sensibles. Nunca se versionan.
2. **YAML de configuración** (`config/settings.yaml`) — parámetros operacionales (rangos de fecha, tamaños de batch, modo debug).
3. **YAML de catálogos** (`config/catalogo_servicios.yaml`, `config/excepciones_usuarios.yaml`) — reglas de negocio editables sin tocar código.

### Variables de entorno requeridas

Ver `.env.example` para la lista completa. Como referencia rápida:

```
ARANDA_DB_SERVER=172.16.20.70
ARANDA_DB_NAME=ArandaDB8
ARANDA_DB_USER=...
ARANDA_DB_PASSWORD=...

DISCOVERY_DB_NAME=DiscovSQL
DISCOVERY_DB_USER=...
DISCOVERY_DB_PASSWORD=...

KACTUS_DB_NAME=kactus
KACTUS_DB_USER=...
KACTUS_DB_PASSWORD=...

LDAP_SERVER=ldap://172.16.0.5:389
LDAP_BASE_DN=dc=FINAGRO,dc=LOC
LDAP_USER=FINAGRO\entrustuser
LDAP_PASSWORD=...
```

---

## Uso

PRISMA expone una CLI con tres comandos principales:

```bash
# Ejecuta el flujo histórico completo (genera indicators1.xlsx)
prisma run-historico

# Ejecuta el flujo Stefanini/2026 (genera provisionalASMS.xlsx + tareas1.xlsx)
prisma run-stefanini

# Ejecuta ambos flujos en secuencia (reemplazo del notebook manual)
prisma run-all

# Modo debug: conserva intermedios en data/interim/ para inspección
prisma run-all --debug

# Ejecuta solo los modelos de ML sobre datos ya consolidados
prisma run-models
```

Para ver todas las opciones:

```bash
prisma --help
prisma run-all --help
```

---

## Desarrollo

```bash
# Instalar en modo desarrollo con dependencias de testing
pip install -e ".[dev]"

# Correr tests
pytest

# Correr tests con cobertura
pytest --cov=prisma_gti --cov-report=html

# Linter y formato
ruff check src/
ruff format src/

# Profiling de la corrida actual (Fase 2)
python scripts/profile_pipeline.py

# Comparar output del refactor contra el notebook legacy
python scripts/compare_outputs.py --legacy data/legacy/ --new data/output/
```

---

## Documentación adicional

- [`docs/arquitectura.md`](docs/arquitectura.md) — diseño y decisiones técnicas.
- [`docs/fase1_diagnostico.md`](docs/fase1_diagnostico.md) — diagnóstico inicial del notebook legacy.
- [`docs/fase2_profiling.md`](docs/fase2_profiling.md) — resultados del profiling (en progreso).
- [`docs/runbook.md`](docs/runbook.md) — operación, troubleshooting y FAQ.

---

## Equipo

**Dirección de Operaciones Tecnológicas — FINAGRO**

- Propietario funcional: Fabián (DOT)
- Mantenedor técnico: ilab

---

## Licencia

Software propietario de FINAGRO. Uso interno exclusivo.