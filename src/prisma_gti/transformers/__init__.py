"""Capa transformers: funciones puras de transformación de DataFrames.

Todos los módulos de esta capa siguen el contrato:

- Reciben un DataFrame (o Series), retornan un DataFrame nuevo o copia.
- No tienen I/O ni estado.
- No mutan el input.
- 100% vectorizadas — prohibido ``iterrows()``.

Componentes
-----------

- :mod:`normalization` — ``unidecode``/``strip``/``lower`` y fixes de
  casing del bloque 42 del legacy.
- :mod:`service_catalog` — carga y aplicación de las 90 reglas del
  YAML de catálogo de servicios.
- :mod:`date_handling` — conversión robusta de strings de fecha a
  ``datetime`` probando múltiples formatos.
- :mod:`time_metrics` — cálculo de ``tiempoTranscurrido``,
  ``CUMPLE_ANS_ATENCION``, normalización de ``CUMPLE_ANS`` y el
  tiempo fijo de GEUS.
- :mod:`schema_align` — alineación al esquema canónico de
  ``indicators1.xlsx`` antes de concatenar.
"""

from prisma_gti.transformers.date_handling import (
    DEFAULT_DATE_FORMATS,
    add_date_features,
    parse_date_column,
)
from prisma_gti.transformers.normalization import (
    fix_responsable_casing,
    normalize_column,
    normalize_text,
)
from prisma_gti.transformers.schema_align import (
    align_schemas,
    get_indicators1_schema,
)
from prisma_gti.transformers.service_catalog import (
    ServiceCatalog,
    apply_asms_overrides,
    apply_indicadores_overrides,
    apply_proyecto_overrides,
    load_service_catalog,
)
from prisma_gti.transformers.time_metrics import (
    GEUS_FIXED_TIME_MINUTES,
    apply_geus_fixed_time,
    compute_cumple_ans_atencion,
    compute_cumple_ans_tareas,
    compute_tiempo_atencion,
    compute_tiempo_transcurrido,
    normalize_cumple_ans,
    parse_glpi_duration_string,
    set_cumple_ans_geus,
)

__all__ = [
    "DEFAULT_DATE_FORMATS",
    "GEUS_FIXED_TIME_MINUTES",
    "ServiceCatalog",
    "add_date_features",
    "align_schemas",
    "apply_asms_overrides",
    "apply_geus_fixed_time",
    "apply_indicadores_overrides",
    "apply_proyecto_overrides",
    "compute_cumple_ans_atencion",
    "compute_cumple_ans_tareas",
    "compute_tiempo_atencion",
    "compute_tiempo_transcurrido",
    "fix_responsable_casing",
    "get_indicators1_schema",
    "load_service_catalog",
    "normalize_column",
    "normalize_cumple_ans",
    "normalize_text",
    "parse_date_column",
    "parse_glpi_duration_string",
    "set_cumple_ans_geus",
]
