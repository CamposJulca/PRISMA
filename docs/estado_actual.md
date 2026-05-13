# Estado Actual del Proyecto PRISMA-GTI

**Última actualización:** 13 de mayo de 2026
**Fase actual:** 3 — Refactor a CLI modular (~92% completado)
**Servidor:** 172.16.0.98 — usuario `ilab` — `/home/ilab/PRISMA/prisma-gti`
**Repositorio:** https://github.com/CamposJulca/PRISMA.git

---

## Estado en una página

PRISMA reemplaza dos notebooks Jupyter de FINAGRO por un sistema
modular en Python. Genera los archivos Excel que alimentan el
dashboard de Power BI del área DOT.

### Capas implementadas (cerradas)

- `core/` — config, secrets, logger, exceptions
- `loaders/` — 12 conectores (SQL Server, LDAP, CSVs, Excel)
- `identity/` — resolver con estrategia Kactus → LDAP → overrides
- `transformers/` — normalización, catálogo, métricas de tiempo
- `writers/` — Excel y Parquet
- `pipelines/historico.py` — genera `indicators1.xlsx`
- `pipelines/stefanini.py` — genera `provisionalASMS.xlsx` y `tareas1.xlsx`
- `scripts/compare_outputs.py` — validación de paridad

### Capas pendientes

- `pipelines/ml_models.py` — regresiones polinómica y logística
- `cli.py` — comando único `prisma run-all`
- `tests/` — suite de tests unitarios

---

## Estado de paridad con el notebook legacy

**Última corrida del 13-may-2026 a las 15:46:**

- `indicators1.xlsx`: 62.946 filas en 15,1 segundos
- Paridad estructural exacta: filas, columnas, dtypes idénticos
- Divergencias remanentes: 3.473 / 881.244 celdas (99,6% coincidencia)
- Las divergencias remanentes están todas atribuidas a causas
  conocidas y documentadas (ver siguiente sección).

`stefanini.py` recién implementado, pendiente comparación contra
archivos legacy de `provisionalASMS.xlsx` y `tareas1.xlsx` que hay
que pedirle a Fabián.

---

## Hallazgos arquitectónicos importantes

**Aranda ASMS NO pasa por `apply_manual_overrides`** en `historico.py`.
Esto es comportamiento deliberado replicando el notebook legacy.
Explica por qué los fixes de identidad (fabian_alean, Maryluz Olarte,
Camilo Estrada) solo aplican parcialmente al consolidado final.

**El log del resolver muestra "overrides=0"** pero es un campo
reservado/engañoso. Los manual_overrides sí se aplican, simplemente
no se contabilizan en esa métrica. Los 3 fixes de Fabián SÍ aparecen
correctamente en los datos.

---

## Decisiones funcionales de Fabián (recibidas 12-may-2026)

| # | Tema | Decisión | Estado |
|---|---|---|---|
| 1 | `indicators_abiertos.xlsx` | NO se consume en Power BI | ✓ Sin acción |
| 2 | CUMPLE_ANS GLPI (909 casos) | Fabián valida la lista | ⏳ Esperando |
| 3 | Fabián Alean username | "fabian_alean" | ✓ Aplicado |
| 4 | Maryluz Olarte | "Maryluz Olarte" (sin Cortes) | ✓ Aplicado |
| 5 | Camilo Estrada | "Camilo Estrada" (sin Pelaez) | ✓ Aplicado |
| 6 | Nombres largos vs cortos | Mantener abreviados (AD) | ✓ Lógica correcta |
| 7 | e-FUICC vs E-FUICC | "e-FUICC" | ✓ Aplicado |
| 8 | Felipe Becker Pardo | Dejar genérico | ✓ Sin acción |
| 9 | Username genérico "adriana" | Dejar genérico | ✓ Sin acción |
| 10 | BITACORA PLATAFORMA TECNOLOGICA | Reunión 15 min pendiente | ⏳ Agendar |

---

## Lo que se hizo en la sesión de hoy (13-may-2026)

1. Validación post-fix de las 3 correcciones funcionales de Fabián.
2. Investigación profunda sobre las 90 filas de Camilo Estrada en GLPI.
3. Análisis del log "overrides=0" — confirmado que es métrica
   engañosa, no bug real.
4. Implementación de `pipelines/stefanini.py` y `StefaniniPipeline`
   actualizando `pipelines/__init__.py`.

---

## Próximos pasos en orden

1. **Pedir a Fabián los archivos legacy** de `provisionalASMS.xlsx`
   y `tareas1.xlsx` para validar paridad de stefanini.
2. **Implementar `pipelines/ml_models.py`** para las regresiones
   polinómica y logística (~52 celdas del notebook ProyectoFinal3).
3. **Implementar `cli.py`** con typer para comando único.
4. **Escribir tests** unitarios e integración.
5. **Reunión 15 min con Fabián** sobre BITACORA.
6. **Recibir decisión de Fabián** sobre los 909 casos CUMPLE_ANS GLPI.
7. **Generar lista de los 909 casos** para enviarla a Fabián.

---

## Comandos útiles

```bash
cd ~/PRISMA/prisma-gti
source .venv/bin/activate

# Ejecutar pipeline histórico
.venv/bin/python -c "
from prisma_gti.core import load_secrets, load_settings, configure_logging
from prisma_gti.pipelines.historico import HistoricoPipeline
secrets = load_secrets()
settings = load_settings(secrets=secrets)
configure_logging(level=secrets.log_level, log_file=secrets.log_file)
pipeline = HistoricoPipeline(settings, secrets)
result = pipeline.run()
print(f'{result.total_rows:,} filas en {result.duration_seconds:.1f}s')
"

# Ejecutar pipeline Stefanini
.venv/bin/python -c "
from prisma_gti.core import load_secrets, load_settings, configure_logging
from prisma_gti.pipelines.stefanini import StefaniniPipeline
secrets = load_secrets()
settings = load_settings(secrets=secrets)
configure_logging(level=secrets.log_level, log_file=secrets.log_file)
pipeline = StefaniniPipeline(settings, secrets)
result = pipeline.run()
print(f'provisionalASMS: {result.total_provisional_rows:,} filas')
print(f'tareas1: {result.total_tareas_rows:,} filas')
"

# Validar paridad contra legacy
.venv/bin/python scripts/compare_outputs.py \
    --prisma data/output/indicators1.xlsx \
    --legacy data/reference/indicators1_legacy.xlsx \
    --report data/output/compare_report.md
```