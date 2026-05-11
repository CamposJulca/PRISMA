"""Pipeline histórico: genera ``indicators1.xlsx``.

Orquesta loaders + identity + transformers + writers para producir
el archivo consolidado que consume Power BI. Replica el orden y las
transformaciones del notebook legacy ``ProyectoFinal3.ipynb``.

Estructura general
------------------

1. Carga todas las fuentes (Kactus + USUARIOS Aranda + Discovery +
   Aranda SP + GLPI + GEUS + ASMS + usuarios.csv + especialistas.csv).
2. Construye la infraestructura de identidad (índice Kactus enriquecido
   con Aranda USUARIOS, manual_overrides, diccionarios bidireccionales).
3. Procesa cada fuente con sus quirks específicos (sección "_process_*").
4. Consolida vía ``pd.concat`` + ``align_schemas`` al esquema canónico
   de 14 columnas.
5. Aplica transformaciones finales sobre el consolidado (catálogo de
   servicios, fix_responsable_casing, dropna casos abiertos).
6. Escribe ``indicators1.xlsx``.

Si ``save_interim=True``, cada DataFrame procesado por fuente se
escribe a Parquet en ``settings.paths.interim_dir`` para facilitar
debugging y validaciones post-hoc con ``compare_outputs.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from unidecode import unidecode

from prisma_gti.core import (
    LoaderError,
    Secrets,
    Settings,
    get_logger,
)
from prisma_gti.identity import (
    IdentityResolutionStats,
    IdentityResolver,
    KactusIndex,
    LdapResolver,
    ManualOverrides,
    build_kactus_index,
    load_manual_overrides,
)
from prisma_gti.loaders import (
    ArandaSqlLoader,
    ArandaSqlResult,
    ArandaUsersLoader,
    AsmsCsvLoader,
    AsmsCsvResult,
    DiscoverySqlLoader,
    EspecialistasCsvLoader,
    GeusExcelLoader,
    GlpiCsvLoader,
    KactusSqlLoader,
    LdapClient,
    UsuariosCsvLoader,
)
from prisma_gti.transformers import (
    align_schemas,
    apply_asms_overrides,
    apply_geus_fixed_time,
    apply_indicadores_overrides,
    apply_proyecto_overrides,
    compute_cumple_ans_tareas,
    compute_tiempo_transcurrido,
    fix_responsable_casing,
    get_indicators1_schema,
    load_service_catalog,
    normalize_cumple_ans,
    parse_date_column,
    parse_glpi_duration_string,
    set_cumple_ans_geus,
)
from prisma_gti.writers import write_excel, write_parquet

logger = get_logger(__name__)


_OUTPUT_FILENAME: Final[str] = "indicators1.xlsx"


# ---- Tipos públicos --------------------------------------------------------


@dataclass(frozen=True)
class HistoricoPipelineResult:
    """Resultado de una corrida de :class:`HistoricoPipeline`.

    Atributos
    ---------
    indicators1_path : Path
        Ruta del archivo Excel generado.
    total_rows : int
        Filas en el consolidado final.
    rows_by_origin : dict[str, int]
        Distribución de filas por ``origen_caso``.
    duration_seconds : float
        Tiempo total de ejecución.
    identity_stats : IdentityResolutionStats
        Métricas de la resolución de identidades de Discovery (la
        única fuente que pasa por la cadena Kactus + LDAP).
    services_normalized : int
        Cantidad de servicios únicos en el output final tras el
        catálogo.
    unresolved_identities : int
        Total de filas (no cédulas únicas) con identidad no resuelta.
    """

    indicators1_path: Path
    total_rows: int
    rows_by_origin: dict[str, int]
    duration_seconds: float
    identity_stats: IdentityResolutionStats
    services_normalized: int
    unresolved_identities: int


# ---- Helpers privados a nivel módulo --------------------------------------


def _normalize_key(value: str) -> str:
    """``unidecode → strip → lower`` aplicado a un string crudo."""
    return unidecode(str(value)).strip().lower()


def _invert_normalized(forward: dict[str, str]) -> dict[str, str]:
    """Construye el dict inverso normalizando la **value** del forward.

    El forward es ``{username: nombre}``; el inverso es
    ``{normalize(nombre): username}``. Si dos nombres normalizan al
    mismo string, gana el último (comportamiento de dict-comprehension).
    """
    return {_normalize_key(v): _normalize_key(k) for k, v in forward.items()}


def _extract_last_responsable(series: pd.Series) -> pd.Series:
    """Si el valor contiene ``\\n``, retorna sólo el último segmento.

    Replica :func:`obtenerResponsable` del bloque 69 del notebook
    legacy, **vectorizado** con ``.str.split('\\n').str[-1]``. NaN se
    propaga naturalmente con el accessor ``.str``.
    """
    return series.str.split("\n").str[-1]


def _extract_primary_servicio(series: pd.Series) -> pd.Series:
    """Si el servicio contiene ``' > '``, retorna sólo el primer segmento.

    Replica :func:`seleccionarServicio` del bloque 73 del notebook
    legacy, **vectorizado** con ``.str.split(' > ').str[0]``. NaN se
    propaga naturalmente con el accessor ``.str`` (el legacy hace
    ``.apply(seleccionarServicio)`` que crashearía sobre NaN —
    propagar es la lectura correcta para que el ``dropna(['servicio'])``
    en :meth:`_consolidate_and_finalize` los elimine después).
    """
    return series.str.split(" > ").str[0]


def _reorder_name_parts(value: str) -> str:
    """Reordena nombres GLPI cuando vienen invertidos (apellidos primero).

    Replica :func:`ordenarResponsables` del bloque 70 del notebook
    legacy. La lógica per-row depende del número de palabras y de
    excepciones puntuales (Carlos Fabian Millan, Luis Francisco
    Muñoz). Es la única función de esta capa que usa ``apply`` porque
    el branching es per-row y no vectorizable de forma clara.
    """
    if not isinstance(value, str):
        value = str(value)
    parts = value.split()
    excepciones = {
        "carlos fabian millan salazar",
        "luis francisco munoz ortiz",
        "luis francisco muñoz ortiz",
    }
    if len(parts) == 6:
        return " ".join(parts[4:] + parts[0:4])
    if len(parts) > 2 and value.lower() not in excepciones:
        return " ".join(parts[2:] + parts[:2])
    if len(parts) == 2:
        return f"{parts[1]} {parts[0]}"
    if len(parts) == 5:
        return " ".join(parts[3:] + parts[:3])
    return value


# Constantes del legacy para fill de GLPI (bloque 58).
_GLPI_USUARIOS_FINALES_AGROS: Final[tuple[str, ...]] = (
    "CARLOS FABIAN MILLAN SALAZAR",
    "LUIS FRANCISCO MUÑOZ ORTIZ",
)
_GLPI_FILL_FAG_AS400_USER: Final[str] = "de la Parra Carrasco Nubia Isabel"
_GLPI_FILL_AGROS_RESP: Final[str] = "Ricardo Francisco Ortiz Pantoja"
_GLPI_FILL_FAG_RESP: Final[str] = "Harold Adolfo Mendoza Avendaño"

# Columnas crudas de GLPI a descartar (bloque 53).
_GLPI_COLUMNS_TO_DROP: Final[tuple[str, ...]] = (
    "TITULO",
    "TIPO_INCIDENTE",
    "APROBRACION",
    "ASIG_PROVEE",
    "PRIORIDAD",
    "TIEMPO_ATENDER_SERVICIO",
    "TIEMPO_ESPERA",
    "TIEMPO_POSEER_EXCEDIDO",
    "TIEMPO_SOLUCION",
    "ULTIMA_ACTUALIZACION",
)

# Map de rename para GLPI (bloque 54).
_GLPI_RENAME_MAP: Final[dict[str, str]] = {
    "id": "numero_caso",
    "TIPO": "tipo_de_caso",
    "SOLICITANTE": "usuariofinal",
    "ASIGANADO_A": "responsable",
    "CATEGORIA": "servicio",
    "FECHA_APERTURA": "fecha_creacion",
    "TIEMPO_ADUEÑARSE": "fecha_atencion",
    "FECHA_SOLUCION": "fecha_solucion",
    "TIEMPO_SOLUCION.1": "tiempoTranscurrido",
    "TIEMPO_RESOLVER_EXCEDIO": "CUMPLE_ANS",
}

# Map de rename para GEUS (bloque 101).
_GEUS_RENAME_MAP: Final[dict[str, str]] = {
    "Fecha de creación": "fecha_creacion",
    "Fecha de modificación": "fecha_atencion",
    "(No modificar) Fecha de modificación": "fecha_solucion",
    "Autor": "usuariofinal",
    "Tipo de Requerimiento": "servicio",
    "Número de solicitud": "numero_caso",
    "Usuario que Gestiona": "responsable",
}

# Maps de rename para ASMS — tres archivos comparten el mismo
# (con la salvedad del header de ``cambios``, que trae
# 'FECHA  ESTIMADA ATENCIÓN' con dos espacios, mapeado a
# ``fecha_atencion`` para paridad con cells 152-154 del legacy).
_ASMS_RENAME_MAP_BASE: Final[dict[str, str]] = {
    "NúMERO DE CASO": "numero_caso",
    "TIPO DE CASO": "tipo_de_caso",
    "USUARIO FINAL": "usuariofinal",
    "ESPECIALISTA": "responsable",
    "SERVICIO": "servicio",
    "FECHA CREACIÓN": "fecha_creacion",
    "FECHA ATENCIÓN": "fecha_atencion",
    "FECHA SOLUCIÓN": "fecha_solucion",
    "TIEMPO TRANSCURRIDO": "tiempoTranscurrido",
    "CUMPLIMIENTO ANS": "CUMPLE_ANS",
    "ORIGEN CASO": "origen_caso",
    "PROYECTO": "proyecto",
    "LOGIN RESPONSABLE": "username_resp",
    "LOGIN USUARIO FINAL": "username_ufinal",
}
_ASMS_CAMBIOS_EXTRA_RENAME: Final[dict[str, str]] = {
    "FECHA  ESTIMADA ATENCIÓN": "fecha_atencion",
}
_ASMS_TAREAS_RENAME_MAP: Final[dict[str, str]] = {
    "NUMERO DE LA TAREA": "numero_caso",
    "TIPO DE CASO": "tipo_de_caso",
    "AUTOR DE LA TAREA": "usuariofinal",
    "SERVICIO": "servicio",
    "RESPONSABLE TAREA": "responsable",
    "FECHA DE REGISTRO CASO": "fecha_creacion",
    "FECHA INICIO TAREA": "fecha_atencion",
    "FECHA FIN REAL TAREA": "fecha_solucion",
    "ORIGEN CASO": "origen_caso",
    "PROYECTO": "proyecto",
    "LOGIN RESPONSABLE TAREA": "username_resp",
    "LOGIN AUTOR TAREA": "username_ufinal",
}
_ASMS_TAREAS_DROP_COLS: Final[tuple[str, ...]] = (
    "CASO RELACIONADO",
    "NOMBRE TAREA",
    "DESCRIPCION TAREA",
    "ESTADO TAREA",
    "FECHA FIN ESTIMADA TAREA",
    "PROGRESO TAREA %",
    "TIEMPO ESTIMADO TAREA",
)


# ---- Pipeline -------------------------------------------------------------


class HistoricoPipeline:
    """Orquestador del pipeline histórico que produce ``indicators1.xlsx``."""

    def __init__(
        self,
        settings: Settings,
        secrets: Secrets,
        *,
        save_interim: bool = False,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._save_interim = save_interim
        self.logger = get_logger(self.__class__.__module__)

    # ---- Entry point ------------------------------------------------------

    def run(self) -> HistoricoPipelineResult:
        """Ejecuta el flujo completo y retorna métricas + ruta del output."""
        start = time.perf_counter()
        self.logger.info("historico: inicio del pipeline")

        # 1. Cargar fuentes.
        sources = self._load_all_sources()

        # 2. Construir infraestructura de identidad.
        infra = self._build_identity_infrastructure(
            kactus_df=sources["kactus"],
            aranda_users_df=sources["aranda_users"],
            usuarios_df=sources["usuarios"],
            especialistas_df=sources["especialistas"],
        )

        # 3. Procesar cada fuente con LDAP persistente.
        with LdapClient(self._secrets.ldap) as ldap_client:
            ldap_resolver = LdapResolver(ldap_client)
            resolver = IdentityResolver(
                kactus_index=infra["kactus_index"],
                ldap_resolver=ldap_resolver,
                manual_overrides=infra["manual_overrides"],
            )

            discovery_processed, identity_stats = self._process_discovery(
                sources["discovery"], resolver, infra
            )
            aranda_processed = self._process_aranda(
                sources["aranda"], resolver, infra
            )
            glpi_processed = self._process_glpi(
                sources["glpi"], resolver, infra
            )
            geus_processed = self._process_geus(
                sources["geus"], resolver, infra
            )
            asms_processed = self._process_asms(
                sources["asms"], resolver, infra
            )

        # 4-5. Consolidar y finalizar.
        consolidated = self._consolidate_and_finalize(
            {
                "discovery": discovery_processed,
                "aranda": aranda_processed,
                "glpi": glpi_processed,
                "geus": geus_processed,
                "asms": asms_processed,
            },
            infra=infra,
        )

        # 6. Escribir output.
        output_path = self._write_output(consolidated)

        # 7. Interim si aplica.
        if self._save_interim:
            self._save_interim_outputs(
                {
                    "discovery": discovery_processed,
                    "aranda": aranda_processed,
                    "glpi": glpi_processed,
                    "geus": geus_processed,
                    "asms": asms_processed,
                    "consolidated": consolidated,
                }
            )

        duration = time.perf_counter() - start
        rows_by_origin = (
            consolidated["origen_caso"].value_counts().to_dict()
        )
        unresolved = int(
            consolidated["username_ufinal"]
            .astype(str)
            .str.strip()
            .str.isdigit()
            .sum()
        )

        self.logger.info(
            "historico: pipeline completado en {:.1f}s → {} filas",
            duration,
            len(consolidated),
        )

        return HistoricoPipelineResult(
            indicators1_path=output_path,
            total_rows=len(consolidated),
            rows_by_origin=rows_by_origin,
            duration_seconds=duration,
            identity_stats=identity_stats,
            services_normalized=int(consolidated["servicio"].nunique()),
            unresolved_identities=unresolved,
        )

    # ---- Etapa 1: carga ---------------------------------------------------

    def _load_all_sources(self) -> dict[str, object]:
        """Invoca todos los loaders necesarios y retorna sus resultados."""
        self.logger.info("historico: cargando fuentes")
        kactus_df = KactusSqlLoader(self._secrets.kactus_db).load()
        aranda_users_df = ArandaUsersLoader(self._secrets.aranda_db).load()
        discovery_df = DiscoverySqlLoader(self._secrets.discovery_db).load()
        aranda_result = ArandaSqlLoader(self._secrets.aranda_db).load()
        glpi_df = GlpiCsvLoader(self._settings.paths.raw_dir).load()
        geus_df = GeusExcelLoader(self._settings.paths.raw_dir).load()
        asms_result = AsmsCsvLoader(self._settings.paths.raw_dir).load()
        usuarios_df = UsuariosCsvLoader(self._settings.paths.raw_dir).load()
        especialistas_df = EspecialistasCsvLoader(
            self._settings.paths.raw_dir
        ).load()
        return {
            "kactus": kactus_df,
            "aranda_users": aranda_users_df,
            "discovery": discovery_df,
            "aranda": aranda_result,
            "glpi": glpi_df,
            "geus": geus_df,
            "asms": asms_result,
            "usuarios": usuarios_df,
            "especialistas": especialistas_df,
        }

    # ---- Etapa 2: infraestructura de identidad ----------------------------

    def _build_identity_infrastructure(
        self,
        kactus_df: pd.DataFrame,
        aranda_users_df: pd.DataFrame,
        usuarios_df: pd.DataFrame,
        especialistas_df: pd.DataFrame,
    ) -> dict[str, object]:
        """Construye índices y diccionarios para la fase de identidad.

        Enriquece el catálogo de Kactus con la tabla ``USUARIOS`` de
        Aranda (mismo esquema de 3 columnas) antes de construir el
        índice. Esto añade cuentas históricas que ya no están en la
        nómina pero quedaron registradas en Aranda — replica el
        comportamiento de ``llenarConAranda()`` del bloque 33 del
        legacy.
        """
        enriched_kactus = pd.concat(
            [kactus_df, aranda_users_df], ignore_index=True
        )
        self.logger.info(
            "historico: índice Kactus enriquecido — Kactus {} + Aranda USUARIOS {} = {}",
            len(kactus_df),
            len(aranda_users_df),
            len(enriched_kactus),
        )
        kactus_index = build_kactus_index(enriched_kactus)

        manual_overrides = load_manual_overrides(
            self._settings.catalogs.excepciones_usuarios_path
        )

        # Diccionarios bidireccionales de usuarios.csv / especialistas.csv.
        dic_usuarios_fwd: dict[str, str] = dict(
            zip(usuarios_df["username_ufinal"], usuarios_df["usuariofinal"])
        )
        dic_especialistas_fwd: dict[str, str] = dict(
            zip(
                especialistas_df["username_resp"],
                especialistas_df["responsable"],
            )
        )
        # Forward normalizado (lowercase key): username lower → name original.
        dic_usuarios_norm_fwd = {
            _normalize_key(k): v for k, v in dic_usuarios_fwd.items()
        }
        dic_especialistas_norm_fwd = {
            _normalize_key(k): v for k, v in dic_especialistas_fwd.items()
        }
        # Inverso normalizado (lowercase del nombre): name lower → username lower.
        dic_usuarios_inv = _invert_normalized(dic_usuarios_fwd)
        dic_especialistas_inv = _invert_normalized(dic_especialistas_fwd)

        service_catalog = load_service_catalog(
            self._settings.catalogs.catalogo_servicios_path
        )

        return {
            "kactus_index": kactus_index,
            "manual_overrides": manual_overrides,
            "dic_usuarios_fwd": dic_usuarios_norm_fwd,
            "dic_especialistas_fwd": dic_especialistas_norm_fwd,
            "dic_usuarios_inv": dic_usuarios_inv,
            "dic_especialistas_inv": dic_especialistas_inv,
            "service_catalog": service_catalog,
        }

    # ---- Etapa 3: procesamiento por fuente --------------------------------

    def _process_discovery(
        self,
        df: pd.DataFrame,
        resolver: IdentityResolver,
        infra: dict[str, object],
    ) -> tuple[pd.DataFrame, IdentityResolutionStats]:
        """Discovery (bloques 11–49 del legacy)."""
        self.logger.info("historico: procesando Discovery ({} filas)", len(df))
        # Resolución de identidades por cédula (Kactus + LDAP residuales).
        df, stats = resolver.resolve_username_ufinal(df)

        # Display names faltantes vía Kactus (bloques 23, 29 + llenarConAranda).
        df, _ = resolver.resolve_display_names(df)

        # Manual overrides (incluye numero_caso, alias, patrones especiales).
        df = resolver.apply_manual_overrides(df)

        # Forward map desde especialistas.csv: username_resp → responsable.
        # Solo donde responsable sigue faltando tras Kactus.
        df = self._fill_from_forward_dict(
            df,
            source_col="username_resp",
            target_col="responsable",
            mapping=infra["dic_especialistas_fwd"],
        )
        df = self._fill_from_forward_dict(
            df,
            source_col="username_ufinal",
            target_col="usuariofinal",
            mapping=infra["dic_usuarios_fwd"],
        )

        df["origen_caso"] = df["origen_caso"].fillna("Discovery")
        return df, stats

    def _process_aranda(
        self,
        result: ArandaSqlResult,
        resolver: IdentityResolver,
        infra: dict[str, object],
    ) -> pd.DataFrame:
        """Aranda (bloque 118): concat de los 3 SP, sin transformación adicional."""
        self.logger.info(
            "historico: procesando Aranda — incidentes={}, requerimientos={}, cambios={}",
            len(result.incidentes),
            len(result.requerimientos),
            len(result.cambios),
        )
        merged = pd.concat(
            [result.cambios, result.requerimientos, result.incidentes],
            ignore_index=True,
        )
        return merged

    def _process_glpi(
        self,
        df: pd.DataFrame,
        resolver: IdentityResolver,
        infra: dict[str, object],
    ) -> pd.DataFrame:
        """GLPI (bloques 52–98 del legacy)."""
        self.logger.info("historico: procesando GLPI ({} filas)", len(df))

        # Bloque 53: drop columnas no usadas y agregar metadata.
        columns_to_drop = [c for c in _GLPI_COLUMNS_TO_DROP if c in df.columns]
        df = df.drop(columns=columns_to_drop)
        df = df.copy()
        df["Proyecto"] = "Soporte"
        df["origen_caso"] = "GLPI"

        # Bloque 54: rename a esquema canónico.
        df = df.rename(columns=_GLPI_RENAME_MAP)

        # Bloque 62: parse fechas (string ISO desde el CSV → datetime).
        for col in ("fecha_creacion", "fecha_atencion", "fecha_solucion"):
            if col in df.columns:
                df[col] = parse_date_column(df[col], errors="coerce")

        # Bloque 55: invertir CUMPLE_ANS (paradoja del export).
        df = normalize_cumple_ans(df, column="CUMPLE_ANS", invert=True)

        # Bloque 58: fill de NaN usuariofinal/responsable para AGROS/FAG/AS400.
        df = self._glpi_fill_na_critical_fields(df)

        # Bloque 58 (final): dropna en responsable + fecha_atencion.
        df = df.dropna(subset=["responsable", "fecha_atencion"]).reset_index(
            drop=True
        )

        # Bloque 63: numero_caso strip espacios + cast int64.
        if df["numero_caso"].dtype == "object":
            df["numero_caso"] = df["numero_caso"].astype(str).str.replace(
                " ", "", regex=False
            )
        df["numero_caso"] = pd.to_numeric(
            df["numero_caso"], errors="coerce"
        ).astype("Int64")

        # Bloque 64: tiempoTranscurrido string → minutos.
        df["tiempoTranscurrido"] = parse_glpi_duration_string(
            df["tiempoTranscurrido"]
        )

        # Bloques 71-72: obtenerResponsable + ordenarResponsables.
        df["responsable"] = _extract_last_responsable(df["responsable"])
        df["responsable"] = df["responsable"].map(_reorder_name_parts)
        df["usuariofinal"] = _extract_last_responsable(df["usuariofinal"])
        df["usuariofinal"] = df["usuariofinal"].map(_reorder_name_parts)

        # Bloque 74: seleccionarServicio.
        df["servicio"] = _extract_primary_servicio(df["servicio"])

        # Bloque 75: 2 service overrides puntuales.
        df["servicio"] = df["servicio"].replace(
            {
                "FAG RECUPERACIONES": "FAG SERVICIOS",
                "AGROS QA": "AGROS",
            }
        )

        # Bloque 78: drop ESTADO (si existe).
        if "ESTADO" in df.columns:
            df = df.drop(columns=["ESTADO"])

        # Bloque 79: crear username vacíos.
        df["username_ufinal"] = ""
        df["username_resp"] = ""

        # Bloque 81: rename Proyecto → proyecto.
        df = df.rename(columns={"Proyecto": "proyecto"})

        # Bloques 86, 88, 89, 95: manual overrides via resolver
        # (vienen del YAML con todas las reglas consolidadas).
        df = resolver.apply_manual_overrides(df)

        # Bloque 90: lowercase + strip de usuariofinal y responsable.
        df["usuariofinal"] = (
            df["usuariofinal"].astype(str).str.strip().str.lower()
        )
        df["responsable"] = (
            df["responsable"].astype(str).str.strip().str.lower()
        )

        # Bloque 93: map inverso para llenar usernames desde nombres.
        df["username_resp"] = df["responsable"].map(
            infra["dic_especialistas_inv"]
        ).fillna(df["username_resp"])
        df["username_ufinal"] = df["usuariofinal"].map(
            infra["dic_usuarios_inv"]
        ).fillna(df["username_ufinal"])

        # Bloque 98: normalizar tipo_de_caso.
        df["tipo_de_caso"] = df["tipo_de_caso"].replace(
            {"INCIDENCIA": "Incidente", "REQUERIMIENTO": "Requerimiento"}
        )

        return df

    def _process_geus(
        self,
        df: pd.DataFrame,
        resolver: IdentityResolver,
        infra: dict[str, object],
    ) -> pd.DataFrame:
        """GEUS (bloques 100–115 del legacy)."""
        self.logger.info("historico: procesando GEUS ({} filas)", len(df))

        # Bloque 101: rename.
        df = df.rename(columns=_GEUS_RENAME_MAP)

        # Bloque 104: dropna responsable.
        df = df.dropna(subset=["responsable"]).reset_index(drop=True)

        # Bloque 105: tiempo fijo 300.
        df = apply_geus_fixed_time(df)

        # Bloque 102: CUMPLE_ANS hardcoded 'SI'.
        df = set_cumple_ans_geus(df)

        # Bloque 107: strip 'SO-' de numero_caso + cast int64.
        df["numero_caso"] = (
            df["numero_caso"].astype(str).str.replace("SO-", "", regex=False)
        )
        df["numero_caso"] = pd.to_numeric(
            df["numero_caso"], errors="coerce"
        ).astype("Int64")

        # Bloque 108: campos pendientes y rename Proyecto.
        df["username_ufinal"] = ""
        df["username_resp"] = ""
        df["origen_caso"] = "GEUS"
        df["proyecto"] = df.get("Proyecto", "Soporte")
        if "Proyecto" in df.columns:
            df = df.drop(columns=["Proyecto"])
        df["tipo_de_caso"] = df.get("tipo_de_caso", "Requerimiento")

        # Bloques 110, 115: manual overrides via resolver.
        df = resolver.apply_manual_overrides(df)

        # Bloque 111: normalize + map inverso.
        df["usuariofinal"] = (
            df["usuariofinal"].astype(str).str.strip().str.lower()
        )
        df["responsable"] = (
            df["responsable"].astype(str).str.strip().str.lower()
        )
        df["usuariofinal"] = df["usuariofinal"].map(_normalize_key)
        df["responsable"] = df["responsable"].map(_normalize_key)
        df["username_resp"] = df["responsable"].map(
            infra["dic_especialistas_inv"]
        ).fillna(df["username_resp"])
        df["username_ufinal"] = df["usuariofinal"].map(
            infra["dic_usuarios_inv"]
        ).fillna(df["username_ufinal"])

        return df

    def _process_asms(
        self,
        result: AsmsCsvResult,
        resolver: IdentityResolver,
        infra: dict[str, object],
    ) -> pd.DataFrame:
        """ASMS — 4 archivos consolidados (bloques 151–179 del legacy)."""
        self.logger.info(
            "historico: procesando ASMS — inc={}, req={}, cam={}, tar={}",
            len(result.incidentes),
            len(result.requerimientos),
            len(result.cambios),
            len(result.tareas),
        )

        inc = self._asms_prepare_basic(result.incidentes, _ASMS_RENAME_MAP_BASE)
        req = self._asms_prepare_basic(result.requerimientos, _ASMS_RENAME_MAP_BASE)
        cam_rename = {**_ASMS_RENAME_MAP_BASE, **_ASMS_CAMBIOS_EXTRA_RENAME}
        # Para cambios el NÚMERO viene con Ú mayúscula; agregar variante:
        cam_rename = {**cam_rename, "NÚMERO DE CASO": "numero_caso"}
        cam = self._asms_prepare_basic(result.cambios, cam_rename)

        tar = self._asms_prepare_tareas(result.tareas)

        # Strip prefijos de numero_caso (bloque 170).
        inc["numero_caso"] = inc["numero_caso"].astype(str).str.replace(
            "IN-TI-", "", regex=False
        )
        req["numero_caso"] = req["numero_caso"].astype(str).str.replace(
            "RQ-TI-", "", regex=False
        )
        cam["numero_caso"] = cam["numero_caso"].astype(str).str.replace(
            "CM-TI-", "", regex=False
        )
        # Filtrar RF-COM de requerimientos.
        req = req[
            ~req["numero_caso"].astype(str).str.contains("RF-COM", na=False)
        ].reset_index(drop=True)

        # tiempoTranscurrido fillna(0) + cast int64 para inc/req/cam.
        for sub in (inc, req, cam):
            sub["tiempoTranscurrido"] = (
                pd.to_numeric(sub["tiempoTranscurrido"], errors="coerce")
                .fillna(0)
                .astype("Int64")
            )

        # numero_caso → int64 para inc/req/cam.
        for sub in (inc, req, cam):
            sub["numero_caso"] = pd.to_numeric(
                sub["numero_caso"], errors="coerce"
            ).astype("Int64")

        # to_datetime para fechas en inc/req/cam (bloque 175).
        for sub in (inc, req, cam):
            for col in ("fecha_atencion", "fecha_creacion", "fecha_solucion"):
                if col in sub.columns:
                    sub[col] = parse_date_column(sub[col], errors="coerce")

        # Concat de los 4 (bloque 176).
        asms = pd.concat([inc, req, cam, tar], ignore_index=True)

        # Bloque 179: catálogo ASMS.
        asms = apply_asms_overrides(asms, infra["service_catalog"])

        return asms

    def _asms_prepare_basic(
        self, df: pd.DataFrame, rename_map: dict[str, str]
    ) -> pd.DataFrame:
        """Pasos comunes a Incidentes/Requerimientos/Cambios."""
        df = df.rename(columns=rename_map).copy()
        df["proyecto"] = "Mesa de Servicios"
        df["origen_caso"] = "Aranda ASMS"
        # Split @ en usernames (bloque 169).
        for col in ("username_ufinal", "username_resp"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.split("@").str[0]
        return df

    def _asms_prepare_tareas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Tareas tiene flujo propio (bloques 156–166 del legacy)."""
        df = df.rename(columns=_ASMS_TAREAS_RENAME_MAP).copy()
        df["proyecto"] = "Mesa de Servicios"
        df["origen_caso"] = "Aranda ASMS"
        df["tipo_de_caso"] = "Tarea"
        # Split @ en usernames (bloque 158).
        for col in ("username_ufinal", "username_resp"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.split("@").str[0]
        # Drop columnas extra (bloque 159).
        cols_drop = [c for c in _ASMS_TAREAS_DROP_COLS if c in df.columns]
        df = df.drop(columns=cols_drop)
        # Parse fechas (bloque 161).
        for col in ("fecha_atencion", "fecha_creacion", "fecha_solucion"):
            if col in df.columns:
                df[col] = parse_date_column(df[col], errors="coerce")
        # tiempoTranscurrido = (fecha_solucion - fecha_creacion) en minutos (bloque 162).
        df = compute_tiempo_transcurrido(
            df, "fecha_creacion", "fecha_solucion", "tiempoTranscurrido"
        )
        # CUMPLE_ANS desde TIEMPO REAL TAREA (bloque 163).
        if "TIEMPO REAL TAREA" in df.columns:
            df = compute_cumple_ans_tareas(df, "TIEMPO REAL TAREA")
            df = df.drop(columns=["TIEMPO REAL TAREA"])
        # numero_caso → int64.
        df["numero_caso"] = pd.to_numeric(
            df["numero_caso"], errors="coerce"
        ).astype("Int64")
        return df

    # ---- Etapa 4-5: consolidación y finalización --------------------------

    def _consolidate_and_finalize(
        self,
        processed: dict[str, pd.DataFrame],
        infra: dict[str, object],
    ) -> pd.DataFrame:
        """Consolida los 5 DataFrames y aplica transformaciones finales.

        Replica los bloques 120–185 del notebook legacy.
        """
        self.logger.info("historico: consolidando 5 fuentes procesadas")

        # Alinear esquemas al canónico antes de concat.
        schema = get_indicators1_schema()
        aligned = align_schemas(processed, schema)

        # Bloque 121: concat Discovery + Aranda + GLPI + GEUS.
        # Bloque 180: concat con ASMS.
        # Aquí los junto en una sola llamada (orden = legacy).
        consolidated = pd.concat(
            [
                aligned["discovery"],
                aligned["aranda"],
                aligned["glpi"],
                aligned["geus"],
                aligned["asms"],
            ],
            ignore_index=True,
        )
        self.logger.info(
            "historico: consolidado crudo = {} filas", len(consolidated)
        )

        # Bloque 127: catálogo indicadores.
        consolidated = apply_indicadores_overrides(
            consolidated, infra["service_catalog"]
        )
        # Proyecto override (DESARROLLO → Mesa de Software).
        consolidated = apply_proyecto_overrides(
            consolidated, infra["service_catalog"]
        )

        # Bloque 181: 'Cumple'/'No cumple' → SI/NO.
        consolidated = normalize_cumple_ans(consolidated, column="CUMPLE_ANS")

        # Bloque 182: split @ en usernames finales.
        for col in ("username_ufinal", "username_resp"):
            consolidated[col] = (
                consolidated[col].astype(str).str.split("@").str[0]
            )

        # Bloque 144: title-case en tipo_de_caso para uniformar
        # 'INCIDENTE'/'Incidente' → 'Incidente'.
        consolidated["tipo_de_caso"] = (
            consolidated["tipo_de_caso"].astype(str).str.title()
        )

        # Bloque 42: fix casing de responsable.
        consolidated = fix_responsable_casing(consolidated)

        # Bloque 139: dropna servicio.
        consolidated = consolidated.dropna(subset=["servicio"]).reset_index(
            drop=True
        )

        # Bloque 184: dropna fecha_atencion + fecha_solucion (casos cerrados).
        consolidated = consolidated.dropna(
            subset=["fecha_atencion", "fecha_solucion"]
        ).reset_index(drop=True)

        # Re-alinear estrictamente al schema (orden + sin columnas extras).
        consolidated = align_schemas({"final": consolidated}, schema)["final"]

        self.logger.info(
            "historico: consolidado final = {} filas", len(consolidated)
        )
        return consolidated

    # ---- Etapa 6: write output --------------------------------------------

    def _write_output(self, consolidated: pd.DataFrame) -> Path:
        output_path = self._settings.paths.output_dir / _OUTPUT_FILENAME
        return write_excel(
            consolidated,
            output_path,
            schema=get_indicators1_schema(),
        )

    # ---- Etapa 7: interim outputs -----------------------------------------

    def _save_interim_outputs(
        self, frames: dict[str, pd.DataFrame]
    ) -> None:
        """Persiste cada DataFrame intermedio a Parquet."""
        interim_dir = self._settings.paths.interim_dir
        self.logger.info(
            "historico: guardando {} artefactos intermedios en {}",
            len(frames),
            interim_dir,
        )
        for name, df in frames.items():
            target = interim_dir / f"historico_{name}.parquet"
            try:
                write_parquet(df, target)
            except Exception as exc:  # pragma: no cover - solo trazabilidad
                self.logger.warning(
                    "historico: fallo escribiendo interim {} ({}): {}",
                    name,
                    target,
                    exc,
                )

    # ---- Helpers internos -------------------------------------------------

    @staticmethod
    def _fill_from_forward_dict(
        df: pd.DataFrame,
        source_col: str,
        target_col: str,
        mapping: dict[str, str],
    ) -> pd.DataFrame:
        """Llena ``target_col`` faltante usando ``source_col`` → ``mapping``.

        Mapping se asume normalizado (claves lowercased). Solo se
        escriben filas donde ``target_col`` es NaN/vacío.
        """
        if source_col not in df.columns or target_col not in df.columns:
            return df
        keys = df[source_col].astype(str).map(_normalize_key)
        candidates = keys.map(mapping)
        mask_fill = df[target_col].isna() & candidates.notna()
        out = df.copy()
        out.loc[mask_fill, target_col] = candidates[mask_fill]
        return out

    def _glpi_fill_na_critical_fields(
        self, df: pd.DataFrame
    ) -> pd.DataFrame:
        """Replica el bloque 58 del legacy: fillna por categoría de servicio."""
        out = df.copy()
        servicio = out["servicio"].astype(str)
        # Usuario final.
        agros_mask = out["usuariofinal"].isna() & servicio.str.contains(
            "AGROS", na=False
        )
        # np.random.choice replicado con un valor estable (primer elemento).
        # El legacy usa choice aleatorio — para idempotencia, fijamos el
        # primer usuario de la lista. La diferencia es cosmética: los dos
        # valores se mapean al mismo cluster aguas abajo.
        out.loc[agros_mask, "usuariofinal"] = _GLPI_USUARIOS_FINALES_AGROS[0]
        fag_user_mask = out["usuariofinal"].isna() & servicio.str.contains(
            "FAG", na=False
        )
        out.loc[fag_user_mask, "usuariofinal"] = _GLPI_FILL_FAG_AS400_USER
        as400_user_mask = out["usuariofinal"].isna() & servicio.str.contains(
            "AS400", na=False
        )
        out.loc[as400_user_mask, "usuariofinal"] = _GLPI_FILL_FAG_AS400_USER
        # Responsable.
        agros_resp_mask = out["responsable"].isna() & servicio.str.contains(
            "AGROS", na=False
        )
        out.loc[agros_resp_mask, "responsable"] = _GLPI_FILL_AGROS_RESP
        fag_resp_mask = out["responsable"].isna() & servicio.str.contains(
            "FAG", na=False
        )
        out.loc[fag_resp_mask, "responsable"] = _GLPI_FILL_FAG_RESP
        return out
