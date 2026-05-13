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

El pipeline de ML (``ml_models.py``) se implementará en una sesión
posterior.
"""

from prisma_gti.pipelines.historico import (
    HistoricoPipeline,
    HistoricoPipelineResult,
)
from prisma_gti.pipelines.stefanini import (
    StefaniniPipeline,
    StefaniniPipelineResult,
)

__all__ = [
    "HistoricoPipeline",
    "HistoricoPipelineResult",
    "StefaniniPipeline",
    "StefaniniPipelineResult",
]
