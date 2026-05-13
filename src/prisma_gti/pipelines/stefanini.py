"""Pipeline Stefanini: genera ``provisionalASMS.xlsx`` y ``tareas1.xlsx``.

Orquesta loaders + transformers + writers para producir los dos
archivos Excel que alimentan los reportes de Stefanini, replicando el
orden y las transformaciones del notebook legacy
``legacy/Indicadores2026.ipynb`` (47 celdas + 2 vacías).

Estructura general
------------------

1. Carga las fuentes Stefanini (4 CSV) + ``Tareas.csv`` desde el export
   ASMS + infraestructura de identidad (Kactus + Aranda USUARIOS +
   CSVs ``usuarios``/``especialistas``).
2. Construye un :class:`IdentityResolver` dentro de un context manager
   de :class:`LdapClient`. La infraestructura queda disponible por
   consistencia con :mod:`pipelines.historico` y para potencial uso
   futuro, pero **este pipeline NO la consume**: el notebook legacy no
   aplica ``apply_manual_overrides`` ni resolución de cédulas sobre
   las filas Stefanini, y replicamos esa decisión.
3. Procesa ``provisionalASMS`` desde ``IncidentesStefanini`` +
   ``RequerimientosStefanini`` + ``CambiosStefanini`` (los 3 CSV con
   flujo ASMS-style). ``ProblemasStefanini`` **NO se incluye** en el
   output final (replica decisión del notebook).
4. Procesa ``tareas1`` desde ``Tareas.csv`` (formato tarea, schema
   distinto al de ASMS).
5. Escribe ambos archivos Excel finales en ``settings.paths.output_dir``.

Si ``save_interim=True``, los DataFrames procesados se persisten a
Parquet en ``settings.paths.interim_dir`` para debugging post-hoc.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from prisma_gti.core import (
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
    ArandaUsersLoader,
    AsmsCsvLoader,
    AsmsCsvResult,
    EspecialistasCsvLoader,
    KactusSqlLoader,
    LdapClient,
    StefaniniCsvLoader,
    StefaniniCsvResult,
    UsuariosCsvLoader,
)
from prisma_gti.transformers import (
    ServiceCatalog,
    apply_asms_overrides,
    compute_cumple_ans_atencion,
    compute_cumple_ans_tareas,
    compute_tiempo_atencion,
    compute_tiempo_transcurrido,
    load_service_catalog,
    normalize_cumple_ans,
    parse_date_column,
)
from prisma_gti.writers import write_excel, write_parquet

logger = get_logger(__name__)


_OUTPUT_PROVISIONAL_FILENAME: Final[str] = "provisionalASMS.xlsx"
_OUTPUT_TAREAS_FILENAME: Final[str] = "tareas1.xlsx"


# Esquema canónico de ``provisionalASMS.xlsx`` (24 columnas, orden
# exacto del output del notebook legacy en cell 860218cf).
_PROVISIONAL_SCHEMA: Final[tuple[str, ...]] = (
    "tipo_de_caso",
    "origen_caso",
    "proyecto",
    "numero_caso",
    "prioridad",
    "servicio",
    "grupo_especialista",
    "responsable",
    "username_resp",
    "usuariofinal",
    "username_ufinal",
    "estado",
    "razon",
    "fecha_creacion",
    "fecha_estimada_atencion",
    "fecha_atencion",
    "fecha_solucion",
    "tiempoTranscurrido",
    "CUMPLE_ANS",
    "ubicacion",
    "servicio_agros",
    "tiempoTranscurridoAtencion",
    "CUMPLE_ANS_ATENCION",
    "estado_caso",
)

# Esquema canónico de ``tareas1.xlsx`` (16 columnas, orden exacto del
# output del notebook legacy tras los movimientos de cell cdd0bd4a).
# Notar que ``CASO RELACIONADO`` y ``ESTADO TAREA`` **se preservan**
# con espacios y mayúsculas tal cual los emite el CSV original — es
# contrato del schema, no error tipográfico.
_TAREAS_SCHEMA: Final[tuple[str, ...]] = (
    "tipo_de_caso",
    "origen_caso",
    "proyecto",
    "CASO RELACIONADO",
    "numero_caso",
    "servicio",
    "responsable",
    "username_resp",
    "usuariofinal",
    "username_ufinal",
    "ESTADO TAREA",
    "fecha_creacion",
    "fecha_atencion",
    "fecha_solucion",
    "tiempoTranscurrido",
    "CUMPLE_ANS",
)


# Rename map para los 3 CSVs de Stefanini (incidentes/requerimientos/
# cambios). Difiere del de ASMS (``pipelines/historico.py``) por:
#
# - Usa ``FECHA DE REGISTRO``/``FECHA ATENCIÓN REAL``/``FECHA SOLUCIÓN
#   REAL`` (Stefanini agrega el sufijo ``REAL``; ASMS no).
# - Incluye columnas extra que solo existen en el export Stefanini:
#   ``ESTADO``, ``RAZON``, ``FECHA ESTIMADA ATENCION``, ``GRUPO
#   ESPECIALISTA``, ``PRIORIDAD``, ``SERVICIO AGROS``, ``UBICACION``.
# - La clave del número de caso difiere por archivo: ``NúMERO DE CASO``
#   (``ú`` minúscula) en incidentes; ``NÚMERO DE CASO`` (``Ú``
#   mayúscula) en requerimientos y cambios. Ambas se mapean a
#   ``numero_caso``.
_STEFANINI_RENAME_MAP: Final[dict[str, str]] = {
    "NúMERO DE CASO": "numero_caso",
    "NÚMERO DE CASO": "numero_caso",
    "TIPO DE CASO": "tipo_de_caso",
    "USUARIO FINAL": "usuariofinal",
    "ESPECIALISTA": "responsable",
    "SERVICIO": "servicio",
    "FECHA DE REGISTRO": "fecha_creacion",
    "FECHA ATENCIÓN REAL": "fecha_atencion",
    "FECHA SOLUCIÓN REAL": "fecha_solucion",
    "TIEMPO TRANSCURRIDO": "tiempoTranscurrido",
    "CUMPLIMIENTO ANS": "CUMPLE_ANS",
    "ORIGEN CASO": "origen_caso",
    "PROYECTO": "proyecto",
    "LOGIN RESPONSABLE": "username_resp",
    "LOGIN USUARIO FINAL": "username_ufinal",
    "ESTADO": "estado",
    "RAZON": "razon",
    "FECHA ESTIMADA ATENCION": "fecha_estimada_atencion",
    "GRUPO ESPECIALISTA": "grupo_especialista",
    "PRIORIDAD": "prioridad",
    "SERVICIO AGROS": "servicio_agros",
    "UBICACION": "ubicacion",
}

# Columnas del export Stefanini que no se preservan en el output
# canónico (cells 89d881cb y f99a8e30 del notebook legacy).
_STEFANINI_DROP_COLS: Final[tuple[str, ...]] = (
    "AUTOR DEL CASO",
    "FECHA ESTIMADA SOLUCION",
    "PROGRESO %",
    "ASUNTO",
)

# Valores por defecto que el notebook asigna a columnas categóricas
# cuando vienen vacías (cells 08066e36 y bff46c20).
_PROVISIONAL_FILLNA_DEFAULTS: Final[dict[str, str]] = {
    "razon": "Nuevo o Aprobacion",
    "servicio_agros": "No Aplica",
    "ubicacion": "Bogotá, D.C.- Bogotá",
}


# Rename map para ``Tareas.csv``. Equivalente al de ASMS-tareas en
# ``pipelines/historico.py`` pero replicado aquí para que cada
# pipeline mantenga sus propias constantes (cell 58062c16 del legacy).
_TAREAS_RENAME_MAP: Final[dict[str, str]] = {
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

# Columnas de ``Tareas.csv`` que NO se preservan (cell 442a33ce). Es
# un drop más corto que el de ``pipelines/historico.py``: aquí
# ``CASO RELACIONADO`` y ``ESTADO TAREA`` quedan como parte del
# schema canónico de ``tareas1.xlsx``.
_TAREAS_DROP_COLS: Final[tuple[str, ...]] = (
    "NOMBRE TAREA",
    "DESCRIPCION TAREA",
    "FECHA FIN ESTIMADA TAREA",
    "PROGRESO TAREA %",
    "TIEMPO ESTIMADO TAREA",
)


# ---- Tipos públicos --------------------------------------------------------


@dataclass(frozen=True)
class StefaniniPipelineResult:
    """Resultado de una corrida de :class:`StefaniniPipeline`.

    Atributos
    ---------
    provisional_asms_path : Path
        Ruta del archivo ``provisionalASMS.xlsx`` generado.
    tareas_path : Path
        Ruta del archivo ``tareas1.xlsx`` generado.
    total_provisional_rows : int
        Filas en el consolidado de ``provisionalASMS``.
    total_tareas_rows : int
        Filas en ``tareas1``.
    duration_seconds : float
        Tiempo total de ejecución.
    identity_stats : IdentityResolutionStats | None
        Métricas de la resolución de identidades. Es ``None`` en este
        pipeline porque el flujo Stefanini NO ejecuta resolución
        (replica el notebook legacy, que no aplica
        ``apply_manual_overrides`` ni Kactus/LDAP sobre estas filas).
    unresolved_identities : int
        Filas con ``username_ufinal`` aparentemente sin resolver
        (dígitos puros). En este pipeline siempre es ``0`` porque los
        exports Stefanini ya emiten ``username_ufinal``/``username_resp``
        pobladas con el login real.
    """

    provisional_asms_path: Path
    tareas_path: Path
    total_provisional_rows: int
    total_tareas_rows: int
    duration_seconds: float
    identity_stats: IdentityResolutionStats | None
    unresolved_identities: int


# ---- Pipeline --------------------------------------------------------------


class StefaniniPipeline:
    """Orquestador del pipeline Stefanini.

    Produce ``provisionalASMS.xlsx`` (consolidado de
    incidentes + requerimientos + cambios) y ``tareas1.xlsx``
    (``Tareas.csv`` procesado). Replica el flujo del notebook legacy
    ``Indicadores2026.ipynb``.
    """

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

    def run(self) -> StefaniniPipelineResult:
        """Ejecuta el flujo completo y retorna métricas + rutas de outputs."""
        start = time.perf_counter()
        self.logger.info("stefanini: inicio del pipeline")

        # 1. Cargar todas las fuentes (CSV + SQL Kactus + Aranda USUARIOS).
        sources = self._load_all_sources()

        # 2. Cargar el catálogo de servicios y precomputar los índices
        # de identidad. Ninguno de estos componentes se consume en el
        # flujo Stefanini (replica el notebook legacy), pero quedan
        # disponibles para sesiones futuras que decidan aplicar
        # resolución de identidades a estas filas.
        infra = self._build_identity_infrastructure(
            kactus_df=sources["kactus"],
            aranda_users_df=sources["aranda_users"],
            usuarios_df=sources["usuarios"],
            especialistas_df=sources["especialistas"],
        )

        # 3. Procesar las fuentes. Apertura única de LDAP en context
        # manager por consistencia con el patrón de ``historico.py``
        # — el resolver queda construido aunque no se invoque, listo
        # para futuras extensiones que apliquen resolución a Stefanini.
        with LdapClient(self._secrets.ldap) as ldap_client:
            ldap_resolver = LdapResolver(ldap_client)
            _resolver = IdentityResolver(
                kactus_index=infra["kactus_index"],
                ldap_resolver=ldap_resolver,
                manual_overrides=infra["manual_overrides"],
            )

            provisional_df = self._process_provisional_asms(
                sources["stefanini"], catalog=infra["service_catalog"]
            )
            tareas_df = self._process_tareas(
                sources["asms"].tareas, catalog=infra["service_catalog"]
            )

        # 4. Escribir outputs Excel finales.
        provisional_path, tareas_path = self._write_outputs(
            provisional_df, tareas_df
        )

        # 5. Interim si aplica.
        if self._save_interim:
            self._save_interim_if_requested(
                {
                    "provisional_asms": provisional_df,
                    "tareas": tareas_df,
                }
            )

        duration = time.perf_counter() - start
        self.logger.info(
            "stefanini: pipeline completado en {:.1f}s → "
            "provisionalASMS={} filas, tareas1={} filas",
            duration,
            len(provisional_df),
            len(tareas_df),
        )

        return StefaniniPipelineResult(
            provisional_asms_path=provisional_path,
            tareas_path=tareas_path,
            total_provisional_rows=len(provisional_df),
            total_tareas_rows=len(tareas_df),
            duration_seconds=duration,
            identity_stats=None,
            unresolved_identities=0,
        )

    # ---- Etapa 1: carga ---------------------------------------------------

    def _load_all_sources(self) -> dict[str, object]:
        """Invoca todos los loaders necesarios.

        ``ProblemasStefanini.csv`` se carga porque
        :class:`StefaniniCsvLoader` lo carga por defecto, pero **NO se
        incluye** en el output ``provisionalASMS.xlsx``: replica el
        comportamiento del notebook legacy, que carga el archivo (cell
        9ad142ad) pero nunca lo concatena al consolidado final.
        """
        self.logger.info("stefanini: cargando fuentes")
        raw_dir = self._settings.paths.raw_dir

        stefanini_result = StefaniniCsvLoader(raw_dir).load()
        asms_result = AsmsCsvLoader(raw_dir).load()
        kactus_df = KactusSqlLoader(self._secrets.kactus_db).load()
        aranda_users_df = ArandaUsersLoader(self._secrets.aranda_db).load()
        usuarios_df = UsuariosCsvLoader(raw_dir).load()
        especialistas_df = EspecialistasCsvLoader(raw_dir).load()

        self.logger.info(
            "stefanini: problemas cargado ({} filas) pero NO incluido en "
            "provisional ASMS (replica comportamiento del notebook)",
            len(stefanini_result.problemas),
        )

        return {
            "stefanini": stefanini_result,
            "asms": asms_result,
            "kactus": kactus_df,
            "aranda_users": aranda_users_df,
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
        """Construye los índices y catálogos transversales.

        Aunque este pipeline **no consume** Kactus ni los overrides de
        identidad, dejamos la infraestructura armada para mantener la
        forma del patrón de ``historico.py`` y para que sesiones
        futuras puedan agregarle resolución de identidades sin
        replumbeo.
        """
        enriched_kactus = pd.concat(
            [kactus_df, aranda_users_df], ignore_index=True
        )
        self.logger.info(
            "stefanini: índice Kactus enriquecido — Kactus {} + Aranda "
            "USUARIOS {} = {}",
            len(kactus_df),
            len(aranda_users_df),
            len(enriched_kactus),
        )

        kactus_index: KactusIndex = build_kactus_index(enriched_kactus)
        manual_overrides: ManualOverrides = load_manual_overrides(
            self._settings.catalogs.excepciones_usuarios_path
        )
        service_catalog: ServiceCatalog = load_service_catalog(
            self._settings.catalogs.catalogo_servicios_path
        )

        self.logger.info(
            "stefanini: infraestructura lista — usuarios.csv={}, "
            "especialistas.csv={}",
            len(usuarios_df),
            len(especialistas_df),
        )

        return {
            "kactus_index": kactus_index,
            "manual_overrides": manual_overrides,
            "service_catalog": service_catalog,
        }

    # ---- Etapa 3: provisional ASMS ----------------------------------------

    def _process_provisional_asms(
        self,
        stefanini_result: StefaniniCsvResult,
        *,
        catalog: ServiceCatalog,
    ) -> pd.DataFrame:
        """Genera el consolidado provisional desde 3 DataFrames Stefanini.

        Sigue el flujo de las cells 354247b0–8196d14f (inc/req) y
        452d318f–d87251f4 (cambios) del notebook legacy. El consolidado
        se obtiene concatenando inc + req + cam (``problemas`` NO entra)
        y se le agrega la columna ``estado_caso`` (cell f82d60ad).
        """
        self.logger.info(
            "stefanini: procesando provisionalASMS — inc={}, req={}, cam={}",
            len(stefanini_result.incidentes),
            len(stefanini_result.requerimientos),
            len(stefanini_result.cambios),
        )

        inc = self._process_one_provisional(
            stefanini_result.incidentes, "incidentes", catalog
        )
        req = self._process_one_provisional(
            stefanini_result.requerimientos, "requerimientos", catalog
        )
        cam = self._process_one_provisional(
            stefanini_result.cambios, "cambios", catalog
        )

        # cells cdaec433 + 5f52776b: concat de las 3 fuentes.
        consolidated = pd.concat([inc, req, cam], ignore_index=True)

        # cell f82d60ad: estado_caso = Abierto si fecha_solucion es NaT,
        # Cerrado si tiene valor.
        consolidated["estado_caso"] = np.where(
            consolidated["fecha_solucion"].isna(), "Abierto", "Cerrado"
        )

        # Alinear al schema canónico de 24 columnas.
        consolidated = self._align_to_schema(
            consolidated, _PROVISIONAL_SCHEMA
        )

        self.logger.info(
            "stefanini: provisionalASMS consolidado = {} filas",
            len(consolidated),
        )
        return consolidated

    def _process_one_provisional(
        self,
        df: pd.DataFrame,
        label: str,
        catalog: ServiceCatalog,
    ) -> pd.DataFrame:
        """Pasos comunes a incidentes/requerimientos/cambios de Stefanini.

        Replica el flujo del notebook legacy en su orden:

        1. Rename a esquema canónico (cells 354247b0 / 452d318f).
        2. Metadata fija (``proyecto`` + ``origen_caso``).
        3. Split ``@`` en usernames (cells 1dc69dc3 / 6cb29486).
        4. ``tiempoTranscurrido.fillna(0).astype(int64)`` (cells
           4578c9d6 / 4f3ea173).
        5. Catálogo ASMS (15 reglas, cells 46804420 / 8cef4869).
        6. Drop columnas extra (cells 89d881cb / f99a8e30).
        7. Fillna defaults para ``razon``/``servicio_agros``/
           ``ubicacion`` (cells 08066e36 / bff46c20).
        8. ``pd.to_datetime`` para las 4 fechas (cells 01b2e5ba / 08102b5c).
        9. ``tiempoTranscurridoAtencion`` (cells 3e24ca7e / cccddeee).
        10. ``CUMPLE_ANS_ATENCION`` (cells a4223d27 / cccddeee).
        11. ``tiempoTranscurridoAtencion.fillna(0).astype(int64)`` (cells
            8196d14f / d87251f4).
        """
        df = df.rename(columns=_STEFANINI_RENAME_MAP).copy()

        df["proyecto"] = "Mesa de Servicios"
        df["origen_caso"] = "Aranda ASMS"

        for col in ("username_ufinal", "username_resp"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.split("@").str[0]

        if "tiempoTranscurrido" in df.columns:
            df["tiempoTranscurrido"] = (
                pd.to_numeric(df["tiempoTranscurrido"], errors="coerce")
                .fillna(0)
                .astype("int64")
            )

        df = apply_asms_overrides(df, catalog)

        cols_drop = [c for c in _STEFANINI_DROP_COLS if c in df.columns]
        if cols_drop:
            df = df.drop(columns=cols_drop)

        for col, default in _PROVISIONAL_FILLNA_DEFAULTS.items():
            if col in df.columns:
                df[col] = df[col].fillna(default)

        for col in (
            "fecha_atencion",
            "fecha_creacion",
            "fecha_solucion",
            "fecha_estimada_atencion",
        ):
            if col in df.columns:
                df[col] = parse_date_column(df[col], errors="coerce")

        df = compute_tiempo_atencion(
            df,
            fecha_estimada_atencion_col="fecha_estimada_atencion",
            fecha_atencion_col="fecha_atencion",
            result_col="tiempoTranscurridoAtencion",
        )

        df = compute_cumple_ans_atencion(
            df,
            tiempo_col="tiempoTranscurridoAtencion",
            result_col="CUMPLE_ANS_ATENCION",
        )

        df["tiempoTranscurridoAtencion"] = (
            pd.to_numeric(df["tiempoTranscurridoAtencion"], errors="coerce")
            .fillna(0)
            .astype("int64")
        )

        self.logger.info(
            "stefanini: {} procesado → {} filas", label, len(df)
        )
        return df

    # ---- Etapa 4: tareas1 -------------------------------------------------

    def _process_tareas(
        self,
        df: pd.DataFrame,
        *,
        catalog: ServiceCatalog,
    ) -> pd.DataFrame:
        """Genera ``tareas1`` desde ``Tareas.csv``.

        Sigue el flujo de las cells 58062c16–028f1201 del notebook
        legacy. ``origen_caso`` se setea a ``'Aranda tareas'`` —
        difiere de ``'Aranda ASMS'`` que usa ``historico.py`` para las
        mismas filas; replicamos literal el valor del notebook
        Stefanini (cell 442a33ce).
        """
        self.logger.info("stefanini: procesando tareas ({} filas)", len(df))

        df = df.rename(columns=_TAREAS_RENAME_MAP).copy()

        df["proyecto"] = "Mesa de Servicios"
        df["origen_caso"] = "Aranda tareas"
        df["tipo_de_caso"] = "Tarea"

        for col in ("username_ufinal", "username_resp"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.split("@").str[0]

        cols_drop = [c for c in _TAREAS_DROP_COLS if c in df.columns]
        if cols_drop:
            df = df.drop(columns=cols_drop)

        for col in ("fecha_atencion", "fecha_creacion", "fecha_solucion"):
            if col in df.columns:
                df[col] = parse_date_column(df[col], errors="coerce")

        # cell 83bc2a99: tiempoTranscurrido = (fecha_solucion - fecha_creacion)
        # en minutos.
        df = compute_tiempo_transcurrido(
            df,
            fecha_inicio_col="fecha_creacion",
            fecha_fin_col="fecha_solucion",
            result_col="tiempoTranscurrido",
        )

        # cell 4484c51c: CUMPLE_ANS desde signo de TIEMPO REAL TAREA.
        if "TIEMPO REAL TAREA" in df.columns:
            df = compute_cumple_ans_tareas(
                df,
                tiempo_real_col="TIEMPO REAL TAREA",
                result_col="CUMPLE_ANS",
            )
            df = df.drop(columns=["TIEMPO REAL TAREA"])

        # cell 23138420: cast final a int64.
        df["tiempoTranscurrido"] = (
            pd.to_numeric(df["tiempoTranscurrido"], errors="coerce")
            .fillna(0)
            .astype("int64")
        )

        # cell e33303c0: 15 reglas del catálogo ASMS.
        df = apply_asms_overrides(df, catalog)

        # cell 028f1201: normalizar Cumple/No cumple → SI/NO. Aplica
        # SOLO a tareas; el flujo de provisional ASMS NO normaliza
        # (replica el notebook estrictamente).
        df = normalize_cumple_ans(df, column="CUMPLE_ANS")

        # Alinear al schema canónico de 16 columnas.
        df = self._align_to_schema(df, _TAREAS_SCHEMA)

        self.logger.info("stefanini: tareas1 → {} filas", len(df))
        return df

    # ---- Etapa 5: escritura -----------------------------------------------

    def _write_outputs(
        self,
        provisional_df: pd.DataFrame,
        tareas_df: pd.DataFrame,
    ) -> tuple[Path, Path]:
        """Escribe los dos archivos Excel finales."""
        output_dir = self._settings.paths.output_dir
        provisional_path = write_excel(
            provisional_df,
            output_dir / _OUTPUT_PROVISIONAL_FILENAME,
            schema=list(_PROVISIONAL_SCHEMA),
        )
        tareas_path = write_excel(
            tareas_df,
            output_dir / _OUTPUT_TAREAS_FILENAME,
            schema=list(_TAREAS_SCHEMA),
        )
        return provisional_path, tareas_path

    # ---- Etapa 6: interim outputs -----------------------------------------

    def _save_interim_if_requested(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> None:
        """Persiste cada DataFrame intermedio a Parquet."""
        interim_dir = self._settings.paths.interim_dir
        self.logger.info(
            "stefanini: guardando {} artefactos intermedios en {}",
            len(frames),
            interim_dir,
        )
        for name, df in frames.items():
            target = interim_dir / f"stefanini_{name}.parquet"
            try:
                write_parquet(df, target)
            except Exception as exc:  # pragma: no cover - solo trazabilidad
                self.logger.warning(
                    "stefanini: fallo escribiendo interim {} ({}): {}",
                    name,
                    target,
                    exc,
                )

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    def _align_to_schema(
        df: pd.DataFrame,
        schema: tuple[str, ...],
    ) -> pd.DataFrame:
        """Alinea ``df`` al schema canónico.

        Agrega columnas faltantes como ``pd.NA`` y descarta las
        extras. El resultado tiene exactamente las columnas del schema
        en el orden dado. No muta el input.
        """
        out = df.copy()
        for col in schema:
            if col not in out.columns:
                out[col] = pd.NA
        return out[list(schema)]
