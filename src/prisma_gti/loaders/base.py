"""Interfaz común de los loaders de PRISMA-GTI.

Contrato — los loaders **solo cargan**. Devuelven el DataFrame con el
esquema crudo de la fuente. La normalización, el mapeo y el
enriquecimiento ocurren aguas abajo en ``transformers/`` — nunca aquí.
Validar el esquema al cargar (vía :meth:`BaseLoader._validate_schema`)
sí es responsabilidad del loader cuando la fuente tiene un contrato
explícito (ver docs/arquitectura.md §7.3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import pandas as pd

from prisma_gti.core import LoaderError, get_logger


class BaseLoader(ABC):
    """Clase base para todos los loaders de PRISMA-GTI.

    Las subclases implementan :meth:`load`, que produce el resultado
    crudo de la fuente: un :class:`pandas.DataFrame` para fuentes
    simples o una dataclass que agrupa varios DataFrames cuando una
    misma fuente entrega múltiples datasets (ej. los 3 SP de Aranda).

    Cada subclase recibe en ``self.logger`` un logger ya bindeado al
    nombre del módulo donde fue declarada, listo para registrar los
    eventos significativos del ciclo de carga.
    """

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__module__)

    @abstractmethod
    def load(self) -> Any:
        """Carga datos de la fuente y devuelve el resultado crudo.

        El tipo concreto de retorno se especifica en cada subclase.
        """

    def _validate_schema(
        self,
        df: pd.DataFrame,
        expected_columns: Iterable[str],
        source: str,
    ) -> None:
        """Verifica que el DataFrame contenga las columnas esperadas.

        Parámetros
        ----------
        df : pd.DataFrame
            DataFrame a validar.
        expected_columns : Iterable[str]
            Columnas que deben estar presentes para que el resultado
            sea utilizable aguas abajo.
        source : str
            Etiqueta de la fuente (aparece en el mensaje de error).

        Lanza
        -----
        LoaderError
            Si falta alguna de ``expected_columns`` en ``df``.
        """
        missing = [c for c in expected_columns if c not in df.columns]
        if missing:
            raise LoaderError(
                f"{source}: faltan columnas esperadas en el resultado: "
                f"{missing}. Columnas presentes: {list(df.columns)}"
            )

    def _post_load(self, df: pd.DataFrame) -> pd.DataFrame:
        """Hook opcional de post-procesamiento.

        Las subclases pueden sobreescribirlo para validaciones
        adicionales sobre el DataFrame ya cargado. La implementación
        por defecto retorna ``df`` sin cambios.
        """
        return df
