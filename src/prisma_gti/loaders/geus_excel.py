"""Loader del export ``GEUS.xlsx`` (sistema legacy GEUS).

Único Excel binario real del pipeline. Se lee con
``pd.read_excel`` (primera hoja por defecto) replicando el notebook
legacy ``ProyectoFinal3.ipynb`` celda 100. El esquema crudo se
conserva tal cual lo emite GEUS; la normalización y el filtrado por
``Usuario que Gestiona`` ocurren en ``transformers/``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import pandas as pd

from prisma_gti.core import LoaderError
from prisma_gti.loaders.base import BaseLoader

_FILENAME: Final[str] = "GEUS.xlsx"

# Columnas-huella: muestreo pequeño de columnas que el notebook
# legacy consume aguas abajo (bloques 100-115 de ProyectoFinal3).
_FINGERPRINT_COLUMNS: Final[tuple[str, ...]] = (
    "Número de solicitud",
    "Fecha de creación",
    "Autor",
    "Usuario que Gestiona",
)


class GeusExcelLoader(BaseLoader):
    """Carga ``GEUS.xlsx`` desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._path = Path(raw_dir) / _FILENAME

    def load(self) -> pd.DataFrame:
        """Lee el Excel de GEUS y valida sus columnas-huella.

        Retorna
        -------
        pd.DataFrame
            Contenido crudo de la primera hoja de ``GEUS.xlsx``.

        Lanza
        -----
        LoaderError
            Si el archivo no existe, si la lectura falla, o si el
            esquema no contiene las columnas-huella esperadas.
        """
        if not self._path.exists():
            raise LoaderError(
                f"geus_excel: archivo no encontrado en {self._path}. "
                f"Verifica DATA_RAW_DIR y que el export de GEUS haya "
                f"sido depositado allí."
            )

        self.logger.info("geus_excel: leyendo {}", self._path)
        start = time.perf_counter()
        try:
            df = pd.read_excel(self._path)
        except (OSError, ValueError) as exc:
            raise LoaderError(
                f"geus_excel: fallo leyendo {self._path}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "geus_excel: {} → {} filas en {:.2f}s",
            _FILENAME,
            len(df),
            elapsed,
        )
        self._validate_schema(df, _FINGERPRINT_COLUMNS, source="geus_excel")
        return df
