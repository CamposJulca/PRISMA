"""Capa de writers: persistencia de outputs del pipeline.

Componentes
-----------

- :mod:`excel` — archivos finales que consume Power BI
  (``indicators1.xlsx``, ``provisionalASMS.xlsx``, ``tareas1.xlsx``).
- :mod:`parquet` — cachés intermedios entre etapas del pipeline.
  Validado en Fase 2 como 185× más rápido que Excel en escritura
  y 404× en lectura.
"""

from prisma_gti.writers.excel import write_excel
from prisma_gti.writers.parquet import read_parquet, write_parquet

__all__ = [
    "read_parquet",
    "write_excel",
    "write_parquet",
]
