"""Loader del CSV ``especialistas.csv`` (diccionario de responsables).

Archivo plano de 2 columnas (``username_resp``, ``responsable``)
mantenido manualmente por el equipo funcional. Cumple el mismo
rol que :mod:`usuarios_csv` pero para la columna ``responsable``:
provee mapeo bidireccional username ↔ nombre.

- **Forward** (``username_resp`` → ``responsable``) — bloque 47 del
  notebook legacy.
- **Inverse** (``responsable`` → ``username_resp``) — bloques 93,
  111, 135 del notebook legacy.

Ambos diccionarios se construyen en
:mod:`prisma_gti.pipelines.historico`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import pandas as pd

from prisma_gti.core import LoaderError
from prisma_gti.loaders.base import BaseLoader

_FILENAME: Final[str] = "especialistas.csv"

_FINGERPRINT_COLUMNS: Final[tuple[str, ...]] = (
    "username_resp",
    "responsable",
)


class EspecialistasCsvLoader(BaseLoader):
    """Carga ``especialistas.csv`` desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._path = Path(raw_dir) / _FILENAME

    def load(self) -> pd.DataFrame:
        """Lee el CSV y valida sus columnas-huella.

        Retorna
        -------
        pd.DataFrame
            DataFrame con columnas ``username_resp`` y ``responsable``.

        Lanza
        -----
        LoaderError
            Si el archivo no existe, si la lectura falla, o si faltan
            las columnas-huella.
        """
        if not self._path.exists():
            raise LoaderError(
                f"especialistas_csv: archivo no encontrado en "
                f"{self._path}. Verifica DATA_RAW_DIR y que "
                f"especialistas.csv esté allí."
            )

        self.logger.info("especialistas_csv: leyendo {}", self._path)
        start = time.perf_counter()
        try:
            df = pd.read_csv(self._path, encoding="utf-8")
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise LoaderError(
                f"especialistas_csv: fallo leyendo {self._path}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "especialistas_csv: {} → {} filas en {:.2f}s",
            _FILENAME,
            len(df),
            elapsed,
        )
        self._validate_schema(
            df, _FINGERPRINT_COLUMNS, source="especialistas_csv"
        )
        return df
