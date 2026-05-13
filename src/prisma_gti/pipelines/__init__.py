"""Capa de pipelines: orquestación de loaders + identity + transformers + writers.

Cada pipeline compone las capas anteriores para producir un output
específico. Es la única capa con lógica de orquestación; las demás
son piezas reutilizables.

Pipelines disponibles:

- :class:`HistoricoPipeline` — genera ``indicators1.xlsx`` consolidando
  Discovery + Aranda (3 SP) + GLPI + GEUS + ASMS. Replica el flujo
  end-to-end del notebook ``ProyectoFinal3.ipynb``.
- :class:`StefaniniPipeline` — genera ``provisionalASMS.xlsx`` (consolidado
  de IncidentesStefanini + RequerimientosStefanini + CambiosStefanini) y
  ``tareas1.xlsx`` (desde ``Tareas.csv``). Replica el flujo del notebook
  ``Indicadores2026.ipynb``.
- :class:`MLPipeline` — genera ``indicadoresPeriodo.xlsx``,
  ``indicadoresPeriodo2026.xlsx`` e ``indicadoresMX.xlsx`` a partir
  de ``indicators1.xlsx``. Entrena las regresiones polinómica y
  logística (cells 186-220 de ``ProyectoFinal3.ipynb``).
"""

from prisma_gti.pipelines.historico import (
    HistoricoPipeline,
    HistoricoPipelineResult,
)
from prisma_gti.pipelines.ml_models import (
    MLPipeline,
    MLPipelineResult,
)
from prisma_gti.pipelines.stefanini import (
    StefaniniPipeline,
    StefaniniPipelineResult,
)

__all__ = [
    "HistoricoPipeline",
    "HistoricoPipelineResult",
    "MLPipeline",
    "MLPipelineResult",
    "StefaniniPipeline",
    "StefaniniPipelineResult",
]
