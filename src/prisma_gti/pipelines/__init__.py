"""Capa de pipelines: orquestación de loaders + identity + transformers + writers.

Cada pipeline compone las capas anteriores para producir un output
específico. Es la única capa con lógica de orquestación; las demás
son piezas reutilizables.

Pipelines disponibles:

- :class:`HistoricoPipeline` — genera ``indicators1.xlsx`` consolidando
  Discovery + Aranda (3 SP) + GLPI + GEUS + ASMS. Replica el flujo
  end-to-end del notebook ``ProyectoFinal3.ipynb``.

Los pipelines de Stefanini (``stefanini.py``) y ML (``ml_models.py``)
se implementarán en sesiones posteriores.
"""

from prisma_gti.pipelines.historico import (
    HistoricoPipeline,
    HistoricoPipelineResult,
)

__all__ = [
    "HistoricoPipeline",
    "HistoricoPipelineResult",
]
