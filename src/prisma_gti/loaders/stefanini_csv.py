"""Loader de los 4 CSVs de Stefanini desde ``raw_dir``.

Los cuatro archivos (``IncidentesStefanini.csv``,
``RequerimientosStefanini.csv``, ``ProblemasStefanini.csv``,
``CambiosStefanini.csv``) son exports tabulares con separador ``,``
que el notebook legacy consume en celdas 13 (incidentes,
requerimientos, problemas) y 30 (cambios) de
``Indicadores2026.ipynb``.

Diferencias con los CSVs de Aranda ASMS — esto importa para los
transformers
----------------------------------------------------------------

Los CSVs de Stefanini comparten el núcleo de columnas con los de
ASMS pero **agregan campos adicionales** que aún no existen en
ASMS. Las columnas extra son:

- ``AUTOR DEL CASO``
- ``FECHA DE REGISTRO``
- ``PRIORIDAD``
- ``ASUNTO``
- ``GRUPO ESPECIALISTA`` (presente en Incidentes/Requerimientos/
  Cambios; **ausente en Problemas**)
- ``FECHA ESTIMADA ATENCION`` / ``FECHA ESTIMADA SOLUCION``
- ``FECHA ATENCIÓN REAL`` / ``FECHA SOLUCIÓN REAL`` (ASMS solo trae
  ``FECHA ATENCIÓN`` / ``FECHA SOLUCIÓN`` sin sufijo)
- ``ESTADO``, ``RAZON``
- ``PROGRESO %``
- ``UBICACION``, ``SERVICIO AGROS``

Inconsistencia tipográfica que **se conserva literal** porque es
contrato del export:

- ``Incidentes`` y ``Problemas`` traen ``NúMERO DE CASO`` (``ú``
  minúscula).
- ``Requerimientos`` y ``Cambios`` traen ``NÚMERO DE CASO`` (``Ú``
  mayúscula).

Estos hallazgos quedan documentados aquí para que los transformers
los manejen explícitamente al alinear el esquema con el de ASMS
(ver ``transformers/schema_align.py``).
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
_FILE_INCIDENTES: Final[str] = "IncidentesStefanini.csv"
_FILE_REQUERIMIENTOS: Final[str] = "RequerimientosStefanini.csv"
_FILE_PROBLEMAS: Final[str] = "ProblemasStefanini.csv"
_FILE_CAMBIOS: Final[str] = "CambiosStefanini.csv"

# Columnas-huella por archivo. La columna ``NUMERO DE CASO`` viene
# con casing distinto entre archivos (``ú`` vs ``Ú``) — se valida
# con el casing exacto del export para detectar cambios silenciosos.
_FP_INCIDENTES: Final[tuple[str, ...]] = (
    "NúMERO DE CASO",
    "AUTOR DEL CASO",
    "LOGIN RESPONSABLE",
    "GRUPO ESPECIALISTA",
)
_FP_REQUERIMIENTOS: Final[tuple[str, ...]] = (
    "NÚMERO DE CASO",
    "AUTOR DEL CASO",
    "LOGIN RESPONSABLE",
    "GRUPO ESPECIALISTA",
)
# Problemas NO trae ``GRUPO ESPECIALISTA`` — fingerprint específica.
_FP_PROBLEMAS: Final[tuple[str, ...]] = (
    "NúMERO DE CASO",
    "AUTOR DEL CASO",
    "LOGIN RESPONSABLE",
    "ESTADO",
)
_FP_CAMBIOS: Final[tuple[str, ...]] = (
    "NÚMERO DE CASO",
    "AUTOR DEL CASO",
    "LOGIN RESPONSABLE",
    "GRUPO ESPECIALISTA",
)


@dataclass(frozen=True)
class StefaniniCsvResult:
    """DataFrames crudos de los 4 CSVs de Stefanini.

    Atributos
    ---------
    incidentes : pd.DataFrame
        Contenido de ``IncidentesStefanini.csv``.
    requerimientos : pd.DataFrame
        Contenido de ``RequerimientosStefanini.csv``.
    problemas : pd.DataFrame
        Contenido de ``ProblemasStefanini.csv``.
    cambios : pd.DataFrame
        Contenido de ``CambiosStefanini.csv``.
    """

    incidentes: pd.DataFrame
    requerimientos: pd.DataFrame
    problemas: pd.DataFrame
    cambios: pd.DataFrame


class StefaniniCsvLoader(BaseLoader):
    """Carga los 4 CSVs de Stefanini desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._raw_dir = Path(raw_dir)

    def load(self) -> StefaniniCsvResult:
        """Lee los 4 CSVs en orden y valida sus columnas-huella.

        Retorna
        -------
        StefaniniCsvResult
            DataFrames crudos de los 4 archivos.

        Lanza
        -----
        LoaderError
            Si algún archivo no existe, si su lectura falla, o si su
            esquema no contiene las columnas-huella esperadas.
        """
        incidentes = self._read_one(
            _FILE_INCIDENTES, _FP_INCIDENTES, "incidentes"
        )
        requerimientos = self._read_one(
            _FILE_REQUERIMIENTOS, _FP_REQUERIMIENTOS, "requerimientos"
        )
        problemas = self._read_one(
            _FILE_PROBLEMAS, _FP_PROBLEMAS, "problemas"
        )
        cambios = self._read_one(_FILE_CAMBIOS, _FP_CAMBIOS, "cambios")
        return StefaniniCsvResult(
            incidentes=incidentes,
            requerimientos=requerimientos,
            problemas=problemas,
            cambios=cambios,
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
                f"stefanini_csv: archivo {label!r} no encontrado en "
                f"{path}. Verifica DATA_RAW_DIR y que el export de "
                f"Stefanini haya sido depositado allí."
            )

        self.logger.info("stefanini_csv: leyendo {} ({})", path, label)
        start = time.perf_counter()
        try:
            df = pd.read_csv(path, sep=",", encoding="utf-8")
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise LoaderError(
                f"stefanini_csv: fallo leyendo {path} ({label}): {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "stefanini_csv: {} → {} filas en {:.2f}s",
            label,
            len(df),
            elapsed,
        )
        self._validate_schema(df, fingerprint, source=f"stefanini_csv/{label}")
        return df
