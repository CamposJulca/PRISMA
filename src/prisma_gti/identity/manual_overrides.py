"""Carga de ``config/excepciones_usuarios.yaml`` como estructuras tipadas.

El YAML tiene 6 secciones que el resolver aplica en orden:

1. ``patrones_especiales`` — sustituciones literales sobre
   ``username_ufinal`` cuando el sistema escribió un valor que no es
   un username (típicamente una IP de equipo en lugar del login).
2. ``por_numero_caso`` — overrides puntuales por ``numero_caso``.
3. ``por_username_alias`` — alias inconsistentes → username canónico
   (case-sensitive contra el valor crudo, preservando espacios).
4. ``nombres_por_username`` — completar nombre completo en columnas
   de display según ``aplica_a``.
5. ``por_responsable`` — match exacto contra columna ``responsable``;
   normaliza el match a ``strip().lower()`` al cargar para que el
   resolver compare contra la columna también lowercased.
6. ``por_usuariofinal`` — análogo de (5) para ``usuariofinal``.

Las entradas con ``validacion_pendiente: true`` se cargan igualmente;
al cargar se emite WARNING con sus ``match`` para que el operador
sepa que están allí.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from prisma_gti.core import ConfigurationError, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class NombrePorUsername:
    """Regla para completar nombre completo en columnas de display.

    Atributos
    ---------
    username : str
        Username canónico para el lookup. Se preserva el casing del
        YAML.
    nombre : str
        Nombre completo a escribir en la columna destino.
    aplica_a : tuple[str, ...]
        Subset de ``("responsable", "usuariofinal")``. El resolver
        consulta esta tupla para decidir a qué columna(s) aplicar.
    """

    username: str
    nombre: str
    aplica_a: tuple[str, ...]


@dataclass(frozen=True)
class ManualOverrides:
    """Las 6 secciones del YAML como estructuras de lookup tipadas.

    Atributos
    ---------
    patrones_especiales : dict[str, str]
        Match literal sobre ``username_ufinal`` → username canónico.
        **Case-sensitive**: cubre casos donde el sistema escribió
        valores que no son usernames (típicamente una IP).
    por_numero_caso : dict[int, str]
        ``numero_caso`` → ``username_ufinal``.
    por_username_alias : dict[str, str]
        Alias literal → username canónico. **Case-sensitive**: las
        claves preservan el casing y espacios del YAML.
    nombres_por_username : tuple[NombrePorUsername, ...]
        Reglas con metadata ``aplica_a``; conviene mantenerlas como
        tupla en orden de archivo (el resolver itera).
    por_responsable : dict[str, tuple[str, str]]
        Match (lowercased) → (``responsable_canonico``,
        ``username_resp``).
    por_usuariofinal : dict[str, tuple[str, str]]
        Match (lowercased) → (``usuariofinal_canonico``,
        ``username_ufinal``).
    """

    patrones_especiales: dict[str, str]
    por_numero_caso: dict[int, str]
    por_username_alias: dict[str, str]
    nombres_por_username: tuple[NombrePorUsername, ...]
    por_responsable: dict[str, tuple[str, str]]
    por_usuariofinal: dict[str, tuple[str, str]]


def load_manual_overrides(yaml_path: Path) -> ManualOverrides:
    """Carga el YAML de excepciones y retorna :class:`ManualOverrides`.

    Lanza
    -----
    ConfigurationError
        Si el archivo no existe, no parsea, o alguna sección tiene
        formato inesperado.
    """
    path = Path(yaml_path)
    if not path.is_file():
        raise ConfigurationError(
            f"excepciones_usuarios.yaml no encontrado en {path}."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"excepciones_usuarios.yaml inválido: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(
            "excepciones_usuarios.yaml debe ser un mapping en la raíz."
        )

    patrones_especiales = _load_patrones_especiales(
        raw.get("patrones_especiales") or []
    )
    por_numero_caso = _load_por_numero_caso(raw.get("por_numero_caso") or [])
    por_username_alias = _load_por_username_alias(
        raw.get("por_username_alias") or []
    )
    nombres_por_username = _load_nombres_por_username(
        raw.get("nombres_por_username") or []
    )
    por_responsable = _load_match_section(
        raw.get("por_responsable") or [],
        section="por_responsable",
        canonical_key="responsable_canonico",
        username_key="username_resp",
    )
    por_usuariofinal = _load_match_section(
        raw.get("por_usuariofinal") or [],
        section="por_usuariofinal",
        canonical_key="usuariofinal_canonico",
        username_key="username_ufinal",
    )

    logger.info(
        "manual_overrides: cargado YAML {} → {} patrones, {} numero_caso, "
        "{} alias, {} nombres, {} responsable, {} usuariofinal",
        path,
        len(patrones_especiales),
        len(por_numero_caso),
        len(por_username_alias),
        len(nombres_por_username),
        len(por_responsable),
        len(por_usuariofinal),
    )

    return ManualOverrides(
        patrones_especiales=patrones_especiales,
        por_numero_caso=por_numero_caso,
        por_username_alias=por_username_alias,
        nombres_por_username=nombres_por_username,
        por_responsable=por_responsable,
        por_usuariofinal=por_usuariofinal,
    )


def _load_patrones_especiales(entries: Any) -> dict[str, str]:
    """Carga sección ``patrones_especiales``.

    Match literal (case-sensitive) sobre ``username_ufinal``. La clave
    es el valor crudo que el sistema escribió por error (típicamente
    una IP); el valor es el username canónico de reemplazo.
    """
    if not isinstance(entries, list):
        raise ConfigurationError(
            "patrones_especiales debe ser una lista de mappings."
        )
    result: dict[str, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"patrones_especiales[{idx}] debe ser un mapping."
            )
        try:
            match_raw = str(entry["match"])
            username = str(entry["username_ufinal"])
        except KeyError as exc:
            raise ConfigurationError(
                f"patrones_especiales[{idx}] le falta clave {exc}."
            ) from exc
        result[match_raw] = username
    return result


def _load_por_numero_caso(entries: Any) -> dict[int, str]:
    """Carga sección ``por_numero_caso`` validando tipos."""
    if not isinstance(entries, list):
        raise ConfigurationError(
            "por_numero_caso debe ser una lista de mappings."
        )
    result: dict[int, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"por_numero_caso[{idx}] debe ser un mapping."
            )
        try:
            numero = int(entry["numero_caso"])
            username = str(entry["username_ufinal"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"por_numero_caso[{idx}] formato inválido "
                f"(esperado numero_caso:int, username_ufinal:str): {exc}"
            ) from exc
        result[numero] = username
    return result


def _load_por_username_alias(entries: Any) -> dict[str, str]:
    """Carga sección ``por_username_alias``.

    Claves se preservan literal (case-sensitive, espacios incluidos)
    porque el legacy hace comparación exacta contra el valor crudo
    del export.
    """
    if not isinstance(entries, list):
        raise ConfigurationError(
            "por_username_alias debe ser una lista de mappings."
        )
    result: dict[str, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"por_username_alias[{idx}] debe ser un mapping."
            )
        try:
            origin = str(entry["from"])
            target = str(entry["to"])
        except KeyError as exc:
            raise ConfigurationError(
                f"por_username_alias[{idx}] le falta clave {exc}."
            ) from exc
        result[origin] = target
    return result


def _load_nombres_por_username(entries: Any) -> tuple[NombrePorUsername, ...]:
    """Carga sección ``nombres_por_username``."""
    if not isinstance(entries, list):
        raise ConfigurationError(
            "nombres_por_username debe ser una lista de mappings."
        )
    result: list[NombrePorUsername] = []
    valid_targets = {"responsable", "usuariofinal"}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"nombres_por_username[{idx}] debe ser un mapping."
            )
        try:
            username = str(entry["username"])
            nombre = str(entry["nombre"])
            aplica_a_raw = entry["aplica_a"]
        except KeyError as exc:
            raise ConfigurationError(
                f"nombres_por_username[{idx}] le falta clave {exc}."
            ) from exc
        if not isinstance(aplica_a_raw, list) or not aplica_a_raw:
            raise ConfigurationError(
                f"nombres_por_username[{idx}].aplica_a debe ser lista no vacía."
            )
        invalid = [v for v in aplica_a_raw if v not in valid_targets]
        if invalid:
            raise ConfigurationError(
                f"nombres_por_username[{idx}].aplica_a contiene valores "
                f"inválidos {invalid}; permitidos: {sorted(valid_targets)}."
            )
        result.append(
            NombrePorUsername(
                username=username,
                nombre=nombre,
                aplica_a=tuple(aplica_a_raw),
            )
        )
    return tuple(result)


def _load_match_section(
    entries: Any,
    section: str,
    canonical_key: str,
    username_key: str,
) -> dict[str, tuple[str, str]]:
    """Carga ``por_responsable`` / ``por_usuariofinal`` con misma forma.

    Las claves se **normalizan a ``strip().lower()`` al cargar** para
    que el resolver pueda hacer match contra columnas también
    lowercased sin recomputar.
    """
    if not isinstance(entries, list):
        raise ConfigurationError(
            f"{section} debe ser una lista de mappings."
        )
    result: dict[str, tuple[str, str]] = {}
    pending_validations: list[str] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"{section}[{idx}] debe ser un mapping."
            )
        try:
            match_raw = str(entry["match"])
            canonical = str(entry[canonical_key])
            username = str(entry[username_key])
        except KeyError as exc:
            raise ConfigurationError(
                f"{section}[{idx}] le falta clave {exc}."
            ) from exc
        normalized_match = match_raw.strip().lower()
        result[normalized_match] = (canonical, username)
        if entry.get("validacion_pendiente"):
            pending_validations.append(match_raw)

    if pending_validations:
        logger.warning(
            "manual_overrides: {} entrada(s) con validacion_pendiente en "
            "{} (revisar): {}",
            len(pending_validations),
            section,
            pending_validations,
        )

    return result
