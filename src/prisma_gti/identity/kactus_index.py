"""Índices vectorizados construidos sobre el DataFrame de Kactus.

Convierte el resultado de :class:`KactusSqlLoader` en cuatro
diccionarios de lookup O(1) que el resolver consulta en
operaciones vectorizadas (``Series.map``).

Decisiones de diseño
--------------------

- **Cédulas** se almacenan como ``str`` con ``.strip()`` aplicado;
  vienen del SP como ``varchar(50)`` y deben compararse contra
  ``username_ufinal`` que también es ``str``.
- **Usernames** se normalizan a **lowercase** porque los lookups del
  notebook legacy (bloques 17, 23, 29) comparan con ``.lower()`` en
  ambos lados. Esto permite al resolver hacer
  ``Series.str.lower().map(dict)`` sin recomputar la normalización.
- **Duplicados:** gana el último (comportamiento por defecto de
  ``dict(zip(...))``). Si se detectan duplicados se emite WARNING con
  el conteo — sin listar cada uno para evitar log spam.
- Construcción 100% vectorizada: ``dict(zip(serie_a, serie_b))``,
  prohibido ``iterrows()``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from prisma_gti.core import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class KactusIndex:
    """Índices de lookup derivados del DataFrame de Kactus.

    Atributos
    ---------
    cedula_to_username : dict[str, str]
        Cédula (str stripeada) → username (lowercase stripeado).
    cedula_to_nombre : dict[str, str]
        Cédula → ``NombreCompleto`` (preserva casing original).
    username_to_nombre : dict[str, str]
        Username lowercased → ``NombreCompleto`` (preserva casing).
    username_to_cedula : dict[str, str]
        Username lowercased → cédula.
    """

    cedula_to_username: dict[str, str]
    cedula_to_nombre: dict[str, str]
    username_to_nombre: dict[str, str]
    username_to_cedula: dict[str, str]


def build_kactus_index(kactus_df: pd.DataFrame) -> KactusIndex:
    """Construye los 4 índices a partir del DataFrame de Kactus.

    Parámetros
    ----------
    kactus_df : pd.DataFrame
        Resultado de :class:`KactusSqlLoader`. Debe tener las
        columnas ``cedula``, ``username`` y ``NombreCompleto``.

    Retorna
    -------
    KactusIndex
        Estructura inmutable con los cuatro lookups precomputados.
    """
    cedulas = kactus_df["cedula"].astype(str).str.strip()
    usernames_raw = kactus_df["username"].astype(str).str.strip()
    usernames = usernames_raw.str.lower()
    nombres = kactus_df["NombreCompleto"].astype(str).str.strip()

    cedula_to_username = dict(zip(cedulas, usernames))
    cedula_to_nombre = dict(zip(cedulas, nombres))
    username_to_nombre = dict(zip(usernames, nombres))
    username_to_cedula = dict(zip(usernames, cedulas))

    _warn_if_duplicates(cedulas, "cedula")
    _warn_if_duplicates(usernames, "username")

    logger.info(
        "kactus_index: {} cédulas, {} usernames indexados",
        len(cedula_to_username),
        len(username_to_nombre),
    )

    return KactusIndex(
        cedula_to_username=cedula_to_username,
        cedula_to_nombre=cedula_to_nombre,
        username_to_nombre=username_to_nombre,
        username_to_cedula=username_to_cedula,
    )


def _warn_if_duplicates(series: pd.Series, label: str) -> None:
    """Loguea WARNING con el conteo si hay claves duplicadas."""
    duplicates = series.duplicated().sum()
    if duplicates:
        logger.warning(
            "kactus_index: {} {} duplicados detectados; gana el último",
            duplicates,
            label,
        )
