"""Pipeline ML: regresiones polinómica y logística sobre ``indicators1.xlsx``.

Replica las celdas 186–220 del notebook legacy
``legacy/ProyectoFinal3.ipynb``.

Produce tres archivos Excel consumidos por Power BI (confirmado con
Fabián el 13-may-2026):

- ``indicadoresPeriodo.xlsx`` — subset 2025 agrupado por día con
  features de fecha. Insumo del gráfico histórico.
- ``indicadoresPeriodo2026.xlsx`` — subset 2026 análogo, contra el
  cual Power BI compara la predicción.
- ``indicadoresMX.xlsx`` — matriz codificada (incidentes de Soporte
  con ``fecha_solucion`` en 2025) usada como insumo de la regresión
  logística de cumplimiento ANS.

Estructura general
------------------

1. Lee ``data/output/indicators1.xlsx`` generado por
   :class:`HistoricoPipeline`. Si no existe, falla con
   :class:`LoaderError` indicando que hay que correr ``historico``
   primero.
2. Construye ``indicadores3`` con features de fecha (día de semana,
   mes, día, año) y ``indicadores4`` con el conteo de casos por día.
3. Entrena regresión polinómica (``degree=2``) sobre el subset 2025.
   La regresión lineal previa del notebook también se entrena para
   trazabilidad (se loguea su R² pero no se persiste).
4. Construye ``indicadoresMX`` con filtros + ``LabelEncoder`` sobre
   las columnas categóricas.
5. Entrena regresión logística sobre ``indicadoresMX``.
6. Escribe los tres archivos Excel finales.

Hiperparámetros — decisiones replicadas del notebook
----------------------------------------------------

Valores del notebook legacy (celdas 199-219). Si Fabián requiere
ajuste futuro, extraer a ``settings.yaml``.

- Regresiones (lineal y polinómica): ``test_size=0.22``,
  ``random_state=1000``, ``PolynomialFeatures(degree=2)``.
- Regresión logística: ``test_size=0.40``, ``random_state=42``,
  ``LogisticRegression()`` con defaults de sklearn.

Sobre reproducibilidad del LabelEncoder
---------------------------------------

El encoding se recalcula en cada corrida; los valores codificados
**NO son estables entre corridas** (replica comportamiento del
notebook legacy). Si en el futuro se requiere reproducibilidad,
persistir el encoder y serializar el mapeo a YAML o joblib.

Los modelos entrenados NO se persisten — solo se reportan las
métricas en :class:`MLPipelineResult`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, PolynomialFeatures

from prisma_gti.core import (
    LoaderError,
    Secrets,
    Settings,
    get_logger,
)
from prisma_gti.writers import write_excel, write_parquet

logger = get_logger(__name__)


_INPUT_FILENAME: Final[str] = "indicators1.xlsx"
_OUTPUT_PERIODO_2025_FILENAME: Final[str] = "indicadoresPeriodo.xlsx"
_OUTPUT_PERIODO_2026_FILENAME: Final[str] = "indicadoresPeriodo2026.xlsx"
_OUTPUT_MX_FILENAME: Final[str] = "indicadoresMX.xlsx"


# Hiperparámetros del notebook legacy (celdas 199-219). Si Fabián
# requiere ajuste futuro, extraer a settings.yaml.
_POLY_TEST_SIZE: Final[float] = 0.22
_POLY_RANDOM_STATE: Final[int] = 1000
_POLY_DEGREE: Final[int] = 2
_LOGISTIC_TEST_SIZE: Final[float] = 0.40
_LOGISTIC_RANDOM_STATE: Final[int] = 42


# Ventanas temporales (celdas 194-198).
_PERIODO_2025_START: Final[str] = "2025-01-01"
_PERIODO_2025_END: Final[str] = "2025-12-31"
_PERIODO_2026_START: Final[str] = "2026-01-01"
_PERIODO_2026_END: Final[str] = "2026-12-31"


# Columnas a dropear de ``indicadoresMX`` (cell 208 del notebook).
_MX_DROP_COLS: Final[tuple[str, ...]] = (
    "tipo_de_caso",
    "proyecto",
    "username_resp",
    "usuariofinal",
    "username_ufinal",
    "fecha_solucion",
    "fecha_creacion",
    "fecha_atencion",
    "diasemana_creacion",
    "mes_creacion",
    "dia_creacion",
    "año_creacion",
)

# Columnas categóricas a label-encodear en ``indicadoresMX`` (cell 210).
_MX_LABEL_ENCODE_COLS: Final[tuple[str, ...]] = (
    "origen_caso",
    "servicio",
    "responsable",
)


# ---- Tipos públicos --------------------------------------------------------


@dataclass(frozen=True)
class MLPipelineResult:
    """Resultado de una corrida de :class:`MLPipeline`.

    Atributos
    ---------
    periodo_2025_path : Path
        Ruta del archivo ``indicadoresPeriodo.xlsx`` (subset 2025).
    periodo_path : Path
        Ruta del archivo ``indicadoresPeriodo2026.xlsx`` (subset 2026).
    mx_path : Path
        Ruta del archivo ``indicadoresMX.xlsx`` (matriz codificada
        para regresión logística).
    duration_seconds : float
        Tiempo total de ejecución del pipeline.
    polynomial_r2 : float | None
        R² del modelo polinómico (``degree=2``) sobre el test set.
        Es ``None`` cuando el subset 2025 tiene menos de 5 filas y
        no se puede hacer el split.
    logistic_accuracy : float | None
        Accuracy de la regresión logística sobre el test set. Es
        ``None`` cuando ``indicadoresMX`` tiene menos de 5 filas.
    total_periodo_2025_rows : int
        Filas en ``indicadoresPeriodo.xlsx``.
    total_periodo_rows : int
        Filas en ``indicadoresPeriodo2026.xlsx``.
    total_mx_rows : int
        Filas en ``indicadoresMX.xlsx``.
    """

    periodo_2025_path: Path
    periodo_path: Path
    mx_path: Path
    duration_seconds: float
    polynomial_r2: float | None
    logistic_accuracy: float | None
    total_periodo_2025_rows: int
    total_periodo_rows: int
    total_mx_rows: int


# ---- Pipeline --------------------------------------------------------------


class MLPipeline:
    """Orquestador del pipeline ML.

    Lee el output consolidado de :class:`HistoricoPipeline`
    (``indicators1.xlsx``), construye los datasets de entrenamiento,
    entrena las dos regresiones (polinómica para predicción de
    volumen y logística para cumplimiento ANS), y escribe los tres
    archivos Excel que consume Power BI.

    Nota sobre reproducibilidad
    ---------------------------

    Los ``LabelEncoder`` se recalculan en cada corrida — los valores
    codificados **NO son estables entre corridas** (replica el
    comportamiento del notebook legacy). Si en el futuro se requiere
    estabilidad, persistir el encoder y serializar el mapeo.
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

    def run(self) -> MLPipelineResult:
        """Ejecuta el flujo completo y retorna métricas + rutas de outputs."""
        start = time.perf_counter()
        self.logger.info("ml_models: inicio del pipeline")

        # 1. Cargar indicators1.xlsx (output de HistoricoPipeline).
        indicators = self._load_indicators1()

        # 2. Build indicadores3 (con features) + indicadores4 (groupby diario).
        indicadores3, indicadores4 = self._build_indicadores4(indicators)

        # 3. Filtrar por periodo y agregar columna integer fecha.
        periodo_2025 = self._filter_periodo(
            indicadores4, _PERIODO_2025_START, _PERIODO_2025_END
        )
        periodo_2026 = self._filter_periodo(
            indicadores4, _PERIODO_2026_START, _PERIODO_2026_END
        )
        periodo_2025 = self._add_fecha_column(periodo_2025)
        periodo_2026 = self._add_fecha_column(periodo_2026)
        self.logger.info(
            "ml_models: periodo 2025 = {} filas, periodo 2026 = {} filas",
            len(periodo_2025),
            len(periodo_2026),
        )

        # 4. Entrenar regresiones sobre el subset 2025.
        polynomial_r2 = self._train_regressions(periodo_2025)

        # 5. Build indicadoresMX y entrenar regresión logística.
        indicadores_mx = self._build_indicadores_mx(indicadores3)
        logistic_accuracy = self._train_logistic_regression(indicadores_mx)

        # 6. Escribir outputs.
        paths = self._write_outputs(
            periodo_2025, periodo_2026, indicadores_mx
        )

        # 7. Interim si aplica.
        if self._save_interim:
            self._save_interim_if_requested(
                {
                    "indicadores4": indicadores4,
                    "periodo_2025": periodo_2025,
                    "periodo_2026": periodo_2026,
                    "indicadores_mx": indicadores_mx,
                }
            )

        duration = time.perf_counter() - start
        self.logger.info(
            "ml_models: pipeline completado en {:.1f}s — "
            "polynomial R²={}, logistic accuracy={}",
            duration,
            "n/a" if polynomial_r2 is None else f"{polynomial_r2:.4f}",
            "n/a" if logistic_accuracy is None else f"{logistic_accuracy:.4f}",
        )

        return MLPipelineResult(
            periodo_2025_path=paths["periodo_2025"],
            periodo_path=paths["periodo_2026"],
            mx_path=paths["mx"],
            duration_seconds=duration,
            polynomial_r2=polynomial_r2,
            logistic_accuracy=logistic_accuracy,
            total_periodo_2025_rows=len(periodo_2025),
            total_periodo_rows=len(periodo_2026),
            total_mx_rows=len(indicadores_mx),
        )

    # ---- Etapa 1: carga ---------------------------------------------------

    def _load_indicators1(self) -> pd.DataFrame:
        """Lee ``indicators1.xlsx`` desde ``settings.paths.output_dir``."""
        path = self._settings.paths.output_dir / _INPUT_FILENAME
        if not path.is_file():
            raise LoaderError(
                f"ml_models: indicators1.xlsx no encontrado en {path}. "
                f"Ejecuta HistoricoPipeline primero."
            )

        self.logger.info("ml_models: leyendo {}", path)
        start = time.perf_counter()
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except (OSError, ValueError) as exc:
            raise LoaderError(
                f"ml_models: fallo leyendo {path}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start

        # Asegurar dtypes datetime. ``read_excel`` ya los detecta, pero
        # un Excel regenerado podría traer las columnas como strings.
        for col in ("fecha_creacion", "fecha_atencion", "fecha_solucion"):
            df[col] = pd.to_datetime(df[col], errors="coerce")

        self.logger.info(
            "ml_models: indicators1 → {} filas en {:.2f}s", len(df), elapsed
        )
        return df

    # ---- Etapa 2: feature engineering + groupby ---------------------------

    def _build_indicadores4(
        self, indicators: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Construye ``indicadores3`` (con features) y ``indicadores4``.

        Replica cells 187-193 del notebook. Devuelve ambos DataFrames
        para evitar mutación cruzada: ``indicadores3`` mantiene fechas
        como ``datetime`` (necesario para el flujo MX más adelante);
        el groupby por día se hace sobre una copia donde las fechas
        están reducidas a ``.dt.date``.
        """
        indicadores3 = indicators.copy()

        # cell 188: features de fecha extraídas de fecha_creacion.
        indicadores3["diasemana_creacion"] = (
            indicadores3["fecha_creacion"].dt.dayofweek
        )
        indicadores3["mes_creacion"] = indicadores3["fecha_creacion"].dt.month
        indicadores3["dia_creacion"] = indicadores3["fecha_creacion"].dt.day
        indicadores3["año_creacion"] = indicadores3["fecha_creacion"].dt.year

        # cells 190-192: groupby por fecha-sin-hora para contar casos
        # por día. Trabajamos sobre una copia para no perder la
        # componente datetime de ``indicadores3`` — el flujo MX más
        # adelante (cells 206-207) la necesita en su forma original.
        df_for_group = indicadores3.copy()
        df_for_group["fecha_creacion"] = df_for_group["fecha_creacion"].dt.date

        indicadores4 = df_for_group.groupby(
            [
                "fecha_creacion",
                "año_creacion",
                "mes_creacion",
                "dia_creacion",
                "diasemana_creacion",
            ]
        )["fecha_creacion"].size()
        indicadores4.name = "cantidadCasos"
        indicadores4 = indicadores4.to_frame().reset_index()

        # cell 193: fecha_creacion de vuelta a datetime para los filtros
        # y la columna integer ``fecha`` que entrará a la regresión.
        indicadores4["fecha_creacion"] = pd.to_datetime(
            indicadores4["fecha_creacion"]
        )

        self.logger.info(
            "ml_models: indicadores4 = {} filas (grupo por día)",
            len(indicadores4),
        )
        return indicadores3, indicadores4

    # ---- Etapa 3: filtrado por periodo + feature integer ------------------

    def _filter_periodo(
        self,
        df: pd.DataFrame,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Filtra ``indicadores4`` por rango de ``fecha_creacion``.

        Replica cells 195 y 198 del notebook.
        """
        mask = (df["fecha_creacion"] >= start) & (df["fecha_creacion"] <= end)
        return df[mask].copy().reset_index(drop=True)

    def _add_fecha_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega columna ``fecha`` = días desde el primer día + 1.

        Replica cell 199. Es la feature integer que consume la regresión
        (lineal y polinómica) — la fecha datetime no se puede pasar
        directamente a sklearn.
        """
        out = df.copy()
        if len(out) == 0:
            out["fecha"] = pd.Series(dtype="int64")
            return out
        out["fecha"] = (
            out["fecha_creacion"] - out["fecha_creacion"].min()
        ).dt.days + 1
        return out

    # ---- Etapa 4: regresiones (lineal + polinómica) -----------------------

    def _train_regressions(
        self, periodo_2025: pd.DataFrame
    ) -> float | None:
        """Entrena regresión lineal (trazabilidad) + polinómica.

        Replica cells 199-205 del notebook. Mismas X/y, mismo
        ``train_test_split``, hiperparámetros hardcoded.

        Retorna el R² del modelo polinómico (la métrica reportada en
        :class:`MLPipelineResult`). El R² del modelo lineal se loguea
        para trazabilidad pero no se persiste — es paso preparatorio
        del notebook, no producto final.
        """
        if len(periodo_2025) < 5:
            self.logger.warning(
                "ml_models: periodo 2025 tiene {} filas (<5); se omite "
                "el entrenamiento de regresiones",
                len(periodo_2025),
            )
            return None

        X = periodo_2025[["fecha"]]
        y = periodo_2025["cantidadCasos"].values

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=_POLY_TEST_SIZE,
            random_state=_POLY_RANDOM_STATE,
        )

        # cells 199, 202: regresión lineal (trazabilidad).
        linear = LinearRegression()
        linear.fit(X_train, y_train)
        y_pred_linear = linear.predict(X_test)
        r2_linear = r2_score(y_test, y_pred_linear)
        rmse_linear = float(np.sqrt(mean_squared_error(y_test, y_pred_linear)))
        self.logger.info(
            "ml_models: regresión lineal — R²={:.4f}, RMSE={:.4f}",
            r2_linear,
            rmse_linear,
        )

        # cells 204-205: regresión polinómica grado 2 (métrica reportada).
        poly = PolynomialFeatures(degree=_POLY_DEGREE)
        X_poly_train = poly.fit_transform(X_train)
        X_poly_test = poly.transform(X_test)

        poly_model = LinearRegression()
        poly_model.fit(X_poly_train, y_train)
        y_pred_poly = poly_model.predict(X_poly_test)

        r2_poly = float(r2_score(y_test, y_pred_poly))
        rmse_poly = float(np.sqrt(mean_squared_error(y_test, y_pred_poly)))
        self.logger.info(
            "ml_models: regresión polinómica (degree={}) — R²={:.4f}, RMSE={:.4f}",
            _POLY_DEGREE,
            r2_poly,
            rmse_poly,
        )

        return r2_poly

    # ---- Etapa 5: matriz MX + regresión logística -------------------------

    def _build_indicadores_mx(
        self, indicadores3: pd.DataFrame
    ) -> pd.DataFrame:
        """Construye ``indicadoresMX`` desde ``indicadores3``.

        Replica cells 206-211 del notebook:

        1. Filtra por ``tipo_de_caso == 'Incidente' AND proyecto == 'Soporte'``.
        2. Filtra por ``fecha_solucion`` en 2025.
        3. Encodea ``fecha_solucion`` → ``fechaCaso`` y normaliza
           ``CUMPLE_ANS`` ('NO'→0, 'SI'→1 por orden alfabético del
           ``LabelEncoder``).
        4. Agrega columna ``indice`` (índice del DataFrame original).
        5. Drop de 12 columnas no relevantes para el modelo.
        6. Encodea las 3 columnas categóricas restantes
           (``origen_caso``, ``servicio``, ``responsable``).

        El índice se preserva (no se hace ``.reset_index()``) porque
        el notebook usa ``df.index`` como columna ``indice``.
        """
        # cell 206: filtro Incidente + Soporte (descarta requerimientos,
        # cambios, tareas, y todo lo que no sea proyecto Soporte).
        df = indicadores3[
            (indicadores3["tipo_de_caso"] == "Incidente")
            & (indicadores3["proyecto"] == "Soporte")
        ].copy()
        self.logger.info(
            "ml_models: indicadoresSoporte (Incidente+Soporte) = {} filas",
            len(df),
        )

        # cell 207: filtro por fecha_solucion en 2025.
        df = df[
            (df["fecha_solucion"] >= "2025-01-01")
            & (df["fecha_solucion"] <= "2025-12-31")
        ].copy()

        # cell 207: LabelEncoder sobre fechaCaso (desde fecha_solucion)
        # y CUMPLE_ANS. El notebook usa la misma instancia para ambas
        # columnas; el ``fit_transform`` reinicia el state internamente,
        # así que el resultado es idéntico a usar dos instancias.
        label_encoder = LabelEncoder()
        df["fechaCaso"] = label_encoder.fit_transform(df["fecha_solucion"])
        df["CUMPLE_ANS"] = label_encoder.fit_transform(df["CUMPLE_ANS"])
        df["indice"] = df.index

        # cell 208: drop columnas no usadas por el modelo logístico.
        cols_to_drop = [c for c in _MX_DROP_COLS if c in df.columns]
        df = df.drop(columns=cols_to_drop)

        # cell 210: encode las categóricas restantes (string → int).
        for col in _MX_LABEL_ENCODE_COLS:
            if col in df.columns:
                df[col] = label_encoder.fit_transform(df[col])

        self.logger.info(
            "ml_models: indicadoresMX = {} filas × {} columnas",
            len(df),
            len(df.columns),
        )
        return df

    def _train_logistic_regression(
        self, indicadores_mx: pd.DataFrame
    ) -> float | None:
        """Entrena la regresión logística sobre ``indicadoresMX``.

        Replica cells 212-215 del notebook.

        - X = ``indicadoresMX`` sin ``CUMPLE_ANS``, ``indice`` ni
          ``fechaCaso`` (5 features residuales).
        - y = ``CUMPLE_ANS`` (binaria 0/1).
        - Split: ``test_size=0.40, random_state=42``.
        - Modelo: ``LogisticRegression()`` con defaults de sklearn.

        Retorna accuracy sobre el test set. El notebook reporta además
        confusion_matrix, cross_val_score, precision, recall y F1 —
        están omitidos aquí; si se requieren para producción se
        agregan al :class:`MLPipelineResult`.
        """
        if len(indicadores_mx) < 5:
            self.logger.warning(
                "ml_models: indicadoresMX tiene {} filas (<5); se omite "
                "el entrenamiento logístico",
                len(indicadores_mx),
            )
            return None

        X = indicadores_mx.drop(columns=["CUMPLE_ANS", "indice", "fechaCaso"])
        y = indicadores_mx["CUMPLE_ANS"]

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=_LOGISTIC_TEST_SIZE,
            random_state=_LOGISTIC_RANDOM_STATE,
        )

        model = LogisticRegression()
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        accuracy = float(accuracy_score(y_test, y_pred))

        self.logger.info(
            "ml_models: regresión logística — accuracy={:.4f} "
            "({} train, {} test)",
            accuracy,
            len(X_train),
            len(X_test),
        )

        return accuracy

    # ---- Etapa 6: escritura -----------------------------------------------

    def _write_outputs(
        self,
        periodo_2025: pd.DataFrame,
        periodo_2026: pd.DataFrame,
        indicadores_mx: pd.DataFrame,
    ) -> dict[str, Path]:
        """Escribe los tres archivos Excel finales."""
        output_dir = self._settings.paths.output_dir
        return {
            "periodo_2025": write_excel(
                periodo_2025,
                output_dir / _OUTPUT_PERIODO_2025_FILENAME,
            ),
            "periodo_2026": write_excel(
                periodo_2026,
                output_dir / _OUTPUT_PERIODO_2026_FILENAME,
            ),
            "mx": write_excel(
                indicadores_mx,
                output_dir / _OUTPUT_MX_FILENAME,
            ),
        }

    # ---- Etapa 7: interim outputs -----------------------------------------

    def _save_interim_if_requested(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> None:
        """Persiste cada DataFrame intermedio a Parquet."""
        interim_dir = self._settings.paths.interim_dir
        self.logger.info(
            "ml_models: guardando {} artefactos intermedios en {}",
            len(frames),
            interim_dir,
        )
        for name, df in frames.items():
            target = interim_dir / f"ml_{name}.parquet"
            try:
                write_parquet(df, target)
            except Exception as exc:  # pragma: no cover - solo trazabilidad
                self.logger.warning(
                    "ml_models: fallo escribiendo interim {} ({}): {}",
                    name,
                    target,
                    exc,
                )
