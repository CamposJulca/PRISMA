"""Loader del export ``GLPI.csv`` (Aranda → herramienta legacy GLPI).

El archivo viene con separador ``;`` y comillas dobles literales
(``quotechar='"'``) — patrón replicado del notebook legacy
``ProyectoFinal3.ipynb`` celda 52. El esquema crudo se conserva tal
cual lo emite GLPI; la normalización ocurre aguas abajo en
``transformers/``.

El loader recibe el ``raw_dir`` y compone internamente el nombre de
archivo, que es contrato fijo de la fuente (no configurable).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import pandas as pd

from prisma_gti.core import LoaderError
from prisma_gti.loaders.base import BaseLoader

_FILENAME: Final[str] = "GLPI.csv"

# Columnas-huella: muestreo pequeño de columnas que el notebook
# legacy consume aguas abajo (bloques 53-83 de ProyectoFinal3). Si
# alguna falta es señal de que GLPI cambió su export y la
# transformación se romperá silenciosamente sin esta validación.
_FINGERPRINT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "TITULO",
    "SOLICITANTE",
    "ESTADO",
    "FECHA_APERTURA",
)


class GlpiCsvLoader(BaseLoader):
    """Carga ``GLPI.csv`` desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._path = Path(raw_dir) / _FILENAME

    def load(self) -> pd.DataFrame:
        """Lee el CSV de GLPI y valida sus columnas-huella.

        Retorna
        -------
        pd.DataFrame
            Contenido crudo de ``GLPI.csv``.

        Lanza
        -----
        LoaderError
            Si el archivo no existe, si la lectura falla, o si el
            esquema no contiene las columnas-huella esperadas.
        """
        if not self._path.exists():
            raise LoaderError(
                f"glpi_csv: archivo no encontrado en {self._path}. "
                f"Verifica DATA_RAW_DIR y que el export de GLPI haya "
                f"sido depositado allí."
            )

        self.logger.info("glpi_csv: leyendo {}", self._path)
        start = time.perf_counter()
        try:
            df = pd.read_csv(
                self._path,
                sep=";",
                quotechar='"',
                encoding="utf-8",
            )
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise LoaderError(
                f"glpi_csv: fallo leyendo {self._path}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "glpi_csv: {} → {} filas en {:.2f}s",
            _FILENAME,
            len(df),
            elapsed,
        )
        self._validate_schema(df, _FINGERPRINT_COLUMNS, source="glpi_csv")
        return df
