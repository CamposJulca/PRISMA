"""Loader de los 4 CSVs de Aranda ASMS desde ``raw_dir``.

Los cuatro archivos (``Incidentes.csv``, ``Requerimientos.csv``,
``Cambios.csv``, ``Tareas.csv``) son exports tabulares con separador
``,`` que el notebook legacy consume en celdas 151 (incidentes,
requerimientos, cambios) y 155 (tareas) de ``ProyectoFinal3.ipynb``.

Los esquemas son heterogéneos entre los cuatro archivos. Notable:

- ``Incidentes`` y ``Requerimientos`` comparten 14 columnas idénticas
  con ``FECHA ATENCIÓN`` y ``FECHA SOLUCIÓN``.
- ``Cambios`` también tiene 14 columnas pero con ``FECHA  ESTIMADA
  ATENCIÓN`` (dos espacios) en lugar de ``FECHA ATENCIÓN``.
- ``Tareas`` tiene un esquema distinto de 20 columnas centrado en la
  estructura de tarea, no de caso.

El loader NO renombra ni normaliza columnas — esa es responsabilidad
de los transformers (ver ``Indicadores2026.ipynb`` celda 14).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from prisma_gti.core import LoaderError
from prisma_gti.loaders.base import BaseLoader

# Nombres de archivo — contrato fijo de la fuente.
_FILE_INCIDENTES: Final[str] = "Incidentes.csv"
_FILE_REQUERIMIENTOS: Final[str] = "Requerimientos.csv"
_FILE_CAMBIOS: Final[str] = "Cambios.csv"
_FILE_TAREAS: Final[str] = "Tareas.csv"

# Columnas-huella por archivo. ``NúMERO DE CASO`` viene con la ``ú``
# en minúscula desde el export — se conserva literal porque el loader
# no transforma; la normalización ocurre aguas abajo.
_FP_INCIDENTES: Final[tuple[str, ...]] = (
    "NúMERO DE CASO",
    "LOGIN RESPONSABLE",
    "LOGIN USUARIO FINAL",
    "CUMPLIMIENTO ANS",
)
_FP_REQUERIMIENTOS: Final[tuple[str, ...]] = _FP_INCIDENTES
_FP_CAMBIOS: Final[tuple[str, ...]] = _FP_INCIDENTES
_FP_TAREAS: Final[tuple[str, ...]] = (
    "NUMERO DE LA TAREA",
    "LOGIN AUTOR TAREA",
    "RESPONSABLE TAREA",
    "ESTADO TAREA",
)


@dataclass(frozen=True)
class AsmsCsvResult:
    """DataFrames crudos de los 4 CSVs de Aranda ASMS.

    Atributos
    ---------
    incidentes : pd.DataFrame
        Contenido de ``Incidentes.csv``.
    requerimientos : pd.DataFrame
        Contenido de ``Requerimientos.csv``.
    cambios : pd.DataFrame
        Contenido de ``Cambios.csv``.
    tareas : pd.DataFrame
        Contenido de ``Tareas.csv``.
    """

    incidentes: pd.DataFrame
    requerimientos: pd.DataFrame
    cambios: pd.DataFrame
    tareas: pd.DataFrame


class AsmsCsvLoader(BaseLoader):
    """Carga los 4 CSVs de Aranda ASMS desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._raw_dir = Path(raw_dir)

    def load(self) -> AsmsCsvResult:
        """Lee los 4 CSVs en orden y valida sus columnas-huella.

        Retorna
        -------
        AsmsCsvResult
            DataFrames crudos de los 4 archivos.

        Lanza
        -----
        LoaderError
            Si algún archivo no existe, si su lectura falla, o si su
            esquema no contiene las columnas-huella esperadas.
        """
        incidentes = self._read_one(_FILE_INCIDENTES, _FP_INCIDENTES, "incidentes")
        requerimientos = self._read_one(
            _FILE_REQUERIMIENTOS, _FP_REQUERIMIENTOS, "requerimientos"
        )
        cambios = self._read_one(_FILE_CAMBIOS, _FP_CAMBIOS, "cambios")
        tareas = self._read_one(_FILE_TAREAS, _FP_TAREAS, "tareas")
        return AsmsCsvResult(
            incidentes=incidentes,
            requerimientos=requerimientos,
            cambios=cambios,
            tareas=tareas,
        )

    def _read_one(
        self,
        filename: str,
        fingerprint: tuple[str, ...],
        label: str,
    ) -> pd.DataFrame:
        """Lee un CSV, loguea filas/duración y valida la huella."""
        path = self._raw_dir / filename
        if not path.exists():
            raise LoaderError(
                f"asms_csv: archivo {label!r} no encontrado en {path}. "
                f"Verifica DATA_RAW_DIR y que el export de Aranda ASMS "
                f"haya sido depositado allí."
            )

        self.logger.info("asms_csv: leyendo {} ({})", path, label)
        start = time.perf_counter()
        try:
            df = pd.read_csv(path, sep=",", encoding="utf-8")
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise LoaderError(
                f"asms_csv: fallo leyendo {path} ({label}): {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "asms_csv: {} → {} filas en {:.2f}s", label, len(df), elapsed
        )
        self._validate_schema(df, fingerprint, source=f"asms_csv/{label}")
        return df
