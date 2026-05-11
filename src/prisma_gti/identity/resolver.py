"""Orquestador de la resolución de identidades.

Implementa la estrategia validada empíricamente en Fase 2:

1. **Kactus primero** — lookup O(1) sobre el dict precomputado.
   Cubre el 88,4% de las cédulas según el script 08 (ver
   ``docs/fase2_profiling.md`` §3.8).
2. **LDAP solo para residuales** — UNA sola llamada batch con todas
   las cédulas que Kactus no resolvió (47× speedup vs por-iteración,
   §3.5).
3. **Manual overrides como respaldo** — método separado
   :meth:`apply_manual_overrides` que recibe el DataFrame ya
   resuelto y aplica las 5 secciones del YAML en orden.
4. **No resueltos** — mantener el valor original, contar como
   ``unresolved``. NO se aborta el pipeline (ver
   ``docs/arquitectura.md`` §4.3).

Toda la lógica está vectorizada — prohibido ``iterrows()``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from prisma_gti.core import get_logger
from prisma_gti.identity.kactus_index import KactusIndex
from prisma_gti.identity.ldap_cache import LdapResolver
from prisma_gti.identity.manual_overrides import ManualOverrides

logger = get_logger(__name__)


@dataclass(frozen=True)
class IdentityResolutionStats:
    """Métricas de una pasada de :meth:`IdentityResolver.resolve_username_ufinal`.

    Atributos
    ---------
    total_input : int
        Filas candidatas (es decir, ``username_ufinal`` que era solo
        dígitos antes de la resolución).
    resolved_from_kactus : int
        Cédulas resueltas vía ``KactusIndex.cedula_to_username``.
    resolved_from_ldap : int
        Cédulas resueltas vía LDAP batch (residuales de Kactus).
    resolved_from_overrides : int
        Reservado: siempre ``0`` aquí; los overrides se aplican en
        :meth:`apply_manual_overrides` como pasada separada.
    unresolved : int
        Cédulas que ni Kactus ni LDAP pudieron resolver. El valor
        original se preserva en el DataFrame.
    """

    total_input: int
    resolved_from_kactus: int
    resolved_from_ldap: int
    resolved_from_overrides: int
    unresolved: int


@dataclass(frozen=True)
class DisplayNameStats:
    """Métricas de :meth:`IdentityResolver.resolve_display_names`."""

    usuariofinal_filled: int
    responsable_filled: int


class IdentityResolver:
    """Resuelve identidades vía Kactus → LDAP → manual overrides.

    El resolver es **stateless con respecto a la conexión LDAP**: la
    instancia se construye con un :class:`LdapResolver` que ya
    envuelve un :class:`LdapClient` conectado (típicamente vía
    context manager en el caller).
    """

    def __init__(
        self,
        kactus_index: KactusIndex,
        ldap_resolver: LdapResolver,
        manual_overrides: ManualOverrides,
    ) -> None:
        self._kactus = kactus_index
        self._ldap = ldap_resolver
        self._overrides = manual_overrides

    # ---- Resolución principal de username_ufinal ---------------------------

    def resolve_username_ufinal(
        self,
        df: pd.DataFrame,
        column: str = "username_ufinal",
    ) -> tuple[pd.DataFrame, IdentityResolutionStats]:
        """Resuelve la columna ``username_ufinal`` de un DataFrame.

        Estrategia (vectorizada):

        1. Identifica filas candidatas: ``column`` contiene solo dígitos.
        2. Hace lookup vectorizado contra
           :attr:`KactusIndex.cedula_to_username`.
        3. Para las cédulas que Kactus no resolvió, las agrupa en un
           set único y hace **una sola** llamada batch a
           :class:`LdapResolver`.
        4. Combina ambos resultados y los escribe en el DataFrame.
           Cuando Kactus resuelve, además llena ``usuariofinal`` con
           el ``NombreCompleto`` (paridad con bloque 17 del legacy).
        5. Las cédulas que ni Kactus ni LDAP encontraron se mantienen
           con su valor original.

        Parámetros
        ----------
        df : pd.DataFrame
            DataFrame con la columna a resolver. NO se muta — se
            opera sobre una copia.
        column : str
            Nombre de la columna con el username o cédula candidata.

        Retorna
        -------
        tuple[pd.DataFrame, IdentityResolutionStats]
            DataFrame modificado y métricas agregadas.
        """
        df = df.copy()
        col = df[column]

        # 1. Candidatas: solo dígitos. astype(str) maneja int/float/object.
        candidate_mask = col.astype(str).str.strip().str.isdigit().fillna(False)
        total_input = int(candidate_mask.sum())

        if total_input == 0:
            logger.info(
                "identity_resolver: 0 candidatas a resolver en columna {!r}",
                column,
            )
            return df, IdentityResolutionStats(
                total_input=0,
                resolved_from_kactus=0,
                resolved_from_ldap=0,
                resolved_from_overrides=0,
                unresolved=0,
            )

        cedulas_serie = (
            df.loc[candidate_mask, column].astype(str).str.strip()
        )

        # 2. Lookup vectorizado contra Kactus.
        kactus_hits = cedulas_serie.map(self._kactus.cedula_to_username)
        kactus_mask_in_candidates = kactus_hits.notna()
        resolved_from_kactus = int(kactus_mask_in_candidates.sum())

        # 3. Residuales → LDAP batch (una sola llamada).
        ldap_inputs = cedulas_serie[~kactus_mask_in_candidates]
        ldap_result = self._ldap.resolve_cedulas(ldap_inputs.tolist())
        ldap_hits = ldap_inputs.map(ldap_result.resolved)
        ldap_mask_in_candidates = ldap_hits.notna()
        resolved_from_ldap = int(ldap_mask_in_candidates.sum())

        # 4. Combinar y escribir. Kactus tiene prioridad por construcción
        #    (ldap_inputs ya excluye los Kactus hits).
        df.loc[kactus_hits.dropna().index, column] = kactus_hits.dropna()
        df.loc[ldap_hits.dropna().index, column] = ldap_hits.dropna()

        # 4b. Cuando Kactus resuelve, llenar también `usuariofinal` con
        # NombreCompleto (paridad con bloque 17 del legacy).
        if "usuariofinal" in df.columns:
            nombres = cedulas_serie.map(self._kactus.cedula_to_nombre)
            df.loc[nombres.dropna().index, "usuariofinal"] = nombres.dropna()

        unresolved = total_input - resolved_from_kactus - resolved_from_ldap

        logger.info(
            "identity_resolver: total={}, kactus={}, ldap={}, overrides=0, "
            "unresolved={}",
            total_input,
            resolved_from_kactus,
            resolved_from_ldap,
            unresolved,
        )

        return df, IdentityResolutionStats(
            total_input=total_input,
            resolved_from_kactus=resolved_from_kactus,
            resolved_from_ldap=resolved_from_ldap,
            resolved_from_overrides=0,
            unresolved=unresolved,
        )

    # ---- Display names (bloques 23, 29 del legacy) -------------------------

    def resolve_display_names(
        self,
        df: pd.DataFrame,
        usuariofinal_col: str = "usuariofinal",
        username_ufinal_col: str = "username_ufinal",
        responsable_col: str = "responsable",
        username_resp_col: str = "username_resp",
    ) -> tuple[pd.DataFrame, DisplayNameStats]:
        """Llena ``usuariofinal`` y ``responsable`` faltantes vía Kactus.

        Replica los bloques 23 y 29 del legacy: para cada fila donde
        el display name (``usuariofinal`` o ``responsable``) está
        ausente, intenta resolver mediante ``KactusIndex.username_to_nombre``
        usando el username correspondiente lowercased.

        Si la columna username no existe, esa rama se omite sin error.
        """
        df = df.copy()
        usuariofinal_filled = 0
        responsable_filled = 0

        if (
            usuariofinal_col in df.columns
            and username_ufinal_col in df.columns
        ):
            usuariofinal_filled = self._fill_display_name(
                df,
                display_col=usuariofinal_col,
                username_col=username_ufinal_col,
            )

        if (
            responsable_col in df.columns
            and username_resp_col in df.columns
        ):
            responsable_filled = self._fill_display_name(
                df,
                display_col=responsable_col,
                username_col=username_resp_col,
            )

        logger.info(
            "identity_resolver: display names llenados → usuariofinal={}, "
            "responsable={}",
            usuariofinal_filled,
            responsable_filled,
        )

        return df, DisplayNameStats(
            usuariofinal_filled=usuariofinal_filled,
            responsable_filled=responsable_filled,
        )

    def _fill_display_name(
        self,
        df: pd.DataFrame,
        display_col: str,
        username_col: str,
    ) -> int:
        """Llena ``display_col`` faltante usando ``username_col``.

        Mutates ``df`` in-place (caller ya hizo copy). Retorna el
        número de filas efectivamente llenadas.
        """
        mask_missing = df[display_col].isna()
        if not mask_missing.any():
            return 0
        usernames = (
            df.loc[mask_missing, username_col]
            .astype(str)
            .str.strip()
            .str.lower()
        )
        nombres = usernames.map(self._kactus.username_to_nombre)
        filled_idx = nombres.dropna().index
        df.loc[filled_idx, display_col] = nombres.dropna()
        return int(len(filled_idx))

    # ---- Manual overrides (las 5 secciones del YAML) -----------------------

    def apply_manual_overrides(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica las 6 secciones del YAML en orden (última gana).

        El orden empieza por ``patrones_especiales`` (limpieza de
        valores que no son usernames, ej. IPs) y termina con las
        reglas más específicas (``por_responsable`` y
        ``por_usuariofinal``). Cada sección opera sobre columnas
        distintas o sobre la misma columna sobrescribiendo a la
        anterior.

        Las reglas case-insensitive (``por_responsable`` y
        ``por_usuariofinal``) hacen match contra la columna
        lowercased; las case-sensitive (``patrones_especiales``,
        ``por_username_alias``) hacen match literal.
        """
        df = df.copy()
        ov = self._overrides

        # 1. patrones_especiales → reemplazo case-sensitive en username_ufinal
        # (limpia valores que no son usernames, típicamente IPs).
        if "username_ufinal" in df.columns and ov.patrones_especiales:
            df["username_ufinal"] = df["username_ufinal"].replace(
                ov.patrones_especiales
            )

        # 2. por_numero_caso → escribe username_ufinal por numero_caso
        if "numero_caso" in df.columns and "username_ufinal" in df.columns:
            mapped = df["numero_caso"].map(ov.por_numero_caso)
            df.loc[mapped.dropna().index, "username_ufinal"] = mapped.dropna()

        # 3. por_username_alias → reemplazo case-sensitive en ambas
        # columnas username si existen
        for col in ("username_ufinal", "username_resp"):
            if col in df.columns:
                df[col] = df[col].replace(ov.por_username_alias)

        # 4. nombres_por_username → llena display name por username canónico
        for rule in ov.nombres_por_username:
            for target in rule.aplica_a:
                username_col = (
                    "username_ufinal"
                    if target == "usuariofinal"
                    else "username_resp"
                )
                if target not in df.columns or username_col not in df.columns:
                    continue
                mask = df[username_col] == rule.username
                df.loc[mask, target] = rule.nombre

        # 5. por_responsable → match (lowercased) → (canonico, username_resp)
        self._apply_match_section(
            df,
            mapping=ov.por_responsable,
            match_col="responsable",
            canonical_col="responsable",
            username_col="username_resp",
        )

        # 6. por_usuariofinal → match (lowercased) → (canonico, username_ufinal)
        self._apply_match_section(
            df,
            mapping=ov.por_usuariofinal,
            match_col="usuariofinal",
            canonical_col="usuariofinal",
            username_col="username_ufinal",
        )

        logger.info(
            "identity_resolver: manual_overrides aplicados (6 secciones)"
        )
        return df

    def _apply_match_section(
        self,
        df: pd.DataFrame,
        mapping: dict[str, tuple[str, str]],
        match_col: str,
        canonical_col: str,
        username_col: str,
    ) -> None:
        """Aplica una sección match → (canonical, username) sobre ``df``.

        Mutates ``df`` in-place. El match es case-insensitive porque
        las claves del mapping ya fueron lowercased al cargar el YAML.
        """
        if match_col not in df.columns or not mapping:
            return

        normalized = df[match_col].astype(str).str.strip().str.lower()
        canonical_series = normalized.map(
            {k: v[0] for k, v in mapping.items()}
        )
        username_series = normalized.map(
            {k: v[1] for k, v in mapping.items()}
        )

        canonical_idx = canonical_series.dropna().index
        df.loc[canonical_idx, canonical_col] = canonical_series.dropna()
        if username_col in df.columns:
            username_idx = username_series.dropna().index
            df.loc[username_idx, username_col] = username_series.dropna()
