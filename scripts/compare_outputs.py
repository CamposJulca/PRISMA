"""Test de paridad funcional PRISMA vs notebook legacy.

Compara el ``indicators1.xlsx`` generado por el pipeline ``HistoricoPipeline``
contra el archivo de referencia producido por el notebook legacy
``ProyectoFinal3.ipynb``. La paridad fila-a-fila y celda-a-celda es la
validación de aceptación más importante del proyecto
(``docs/arquitectura.md`` §7.3): PRISMA solo puede reemplazar al notebook
cuando este script reporta paridad exacta o, a lo sumo, divergencias de
``type_mismatch`` (mismo valor, distinto dtype).

Uso típico::

    python scripts/compare_outputs.py \\
        --prisma data/output/indicators1.xlsx \\
        --legacy data/reference/indicators1_legacy.xlsx \\
        --report data/output/compare_report.md

Códigos de salida:

- ``0``: paridad exacta a nivel valor (acepta dtype mismatches).
- ``1``: divergencias de valor (case_difference, value_mismatch,
  null_mismatch).
- ``2``: incompatibilidad estructural (columnas distintas, filas
  distintas, ``key_columns`` no alinean tras sort).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from prisma_gti.core import get_logger

logger = get_logger(__name__)


# ---- Constantes -----------------------------------------------------------

_DEFAULT_PRISMA: str = "data/output/indicators1.xlsx"
_DEFAULT_LEGACY: str = "data/reference/indicators1_legacy.xlsx"
_DEFAULT_KEY_COLUMNS: tuple[str, ...] = ("origen_caso", "numero_caso")
_DEFAULT_MAX_PATTERNS: int = 10
_DEFAULT_ATOL: float = 1e-3
_UNNAMED_REGEX: re.Pattern[str] = re.compile(r"^Unnamed:\s*\d+$")
_NAN_REPR: str = "<NaN>"


# ---- Tipos ---------------------------------------------------------------


@dataclass(frozen=True)
class DtypeRow:
    """Comparación de dtypes para una columna."""

    column: str
    prisma_dtype: str
    legacy_dtype: str
    match: bool


@dataclass(frozen=True)
class ColumnDivergence:
    """Resumen de divergencias de una columna."""

    column: str
    total_divergences: int
    total_rows: int
    classification_counts: Counter[str]
    dominant_type: str
    unique_patterns: int
    top_patterns: list[tuple[str, str, int]]


@dataclass
class StructuralReport:
    """Diagnóstico estructural — set de columnas, número de filas, dtypes."""

    prisma_rows: int = 0
    legacy_rows: int = 0
    prisma_columns_ordered: list[str] = field(default_factory=list)
    legacy_columns_ordered: list[str] = field(default_factory=list)
    columns_match: bool = False
    rows_match: bool = False
    only_in_prisma: list[str] = field(default_factory=list)
    only_in_legacy: list[str] = field(default_factory=list)
    column_dtypes: list[DtypeRow] = field(default_factory=list)
    key_alignment_ok: bool = False
    key_alignment_notes: list[str] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        """``True`` si la estructura permite comparación fila-a-fila."""
        return (
            self.columns_match
            and self.rows_match
            and self.key_alignment_ok
        )


@dataclass(frozen=True)
class ComparisonResult:
    """Resultado completo de una corrida del comparator."""

    structural: StructuralReport
    column_divergences: list[ColumnDivergence]
    total_cell_divergences: int
    rows_compared: int
    has_value_divergences: bool


# ---- Comparator -----------------------------------------------------------


class OutputComparator:
    """Compara dos archivos Excel ``indicators1.xlsx`` para validar paridad.

    El comparator es **read-only**: nunca modifica los archivos
    comparados ni escribe nada salvo el reporte markdown solicitado.
    """

    def __init__(
        self,
        prisma_path: Path,
        legacy_path: Path,
        *,
        key_columns: tuple[str, ...] = _DEFAULT_KEY_COLUMNS,
        ignore_columns: tuple[str, ...] = (),
        max_patterns: int = _DEFAULT_MAX_PATTERNS,
        atol: float = _DEFAULT_ATOL,
        ignore_case: bool = False,
    ) -> None:
        self.prisma_path = Path(prisma_path)
        self.legacy_path = Path(legacy_path)
        self.key_columns = tuple(key_columns)
        self.ignore_columns = tuple(ignore_columns)
        self.max_patterns = max_patterns
        self.atol = atol
        self.ignore_case = ignore_case

    # ---- Pipeline -------------------------------------------------------

    def run(self) -> tuple[ComparisonResult, str]:
        """Ejecuta el flujo completo y retorna (resultado, reporte)."""
        logger.info("compare: leyendo {} y {}", self.prisma_path, self.legacy_path)
        prisma_df, legacy_df = self._load()

        structural = self._validate_structure(prisma_df, legacy_df)

        if not (structural.columns_match and structural.rows_match):
            logger.error("compare: estructura incompatible, abortando comparación de valores")
            report = self._render_report(
                structural=structural,
                column_divergences=[],
                rows_compared=0,
                total_cell_divergences=0,
                has_value_divergences=False,
            )
            return (
                ComparisonResult(
                    structural=structural,
                    column_divergences=[],
                    total_cell_divergences=0,
                    rows_compared=0,
                    has_value_divergences=False,
                ),
                report,
            )

        prisma_aligned, legacy_aligned = self._align(prisma_df, legacy_df, structural)

        if not structural.key_alignment_ok:
            logger.error("compare: key_columns no alinean tras sort, abortando")
            report = self._render_report(
                structural=structural,
                column_divergences=[],
                rows_compared=0,
                total_cell_divergences=0,
                has_value_divergences=False,
            )
            return (
                ComparisonResult(
                    structural=structural,
                    column_divergences=[],
                    total_cell_divergences=0,
                    rows_compared=0,
                    has_value_divergences=False,
                ),
                report,
            )

        column_divs = self._compare_columns(prisma_aligned, legacy_aligned)

        total_cell_divs = sum(d.total_divergences for d in column_divs)
        has_value_divs = any(
            d.classification_counts.get(t, 0) > 0
            for d in column_divs
            for t in ("case_difference", "value_mismatch", "null_mismatch")
        )

        result = ComparisonResult(
            structural=structural,
            column_divergences=column_divs,
            total_cell_divergences=total_cell_divs,
            rows_compared=len(prisma_aligned),
            has_value_divergences=has_value_divs,
        )

        report = self._render_report(
            structural=structural,
            column_divergences=column_divs,
            rows_compared=len(prisma_aligned),
            total_cell_divergences=total_cell_divs,
            has_value_divergences=has_value_divs,
        )

        return result, report

    # ---- Paso 1: carga --------------------------------------------------

    def _load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Lee ambos Excel y descarta columnas ``Unnamed`` + ``--ignore-columns``."""
        if not self.prisma_path.is_file():
            raise FileNotFoundError(f"PRISMA no encontrado: {self.prisma_path}")
        if not self.legacy_path.is_file():
            raise FileNotFoundError(f"LEGACY no encontrado: {self.legacy_path}")

        prisma_df = pd.read_excel(self.prisma_path)
        legacy_df = pd.read_excel(self.legacy_path)

        prisma_df = self._strip_unwanted_columns(prisma_df, label="prisma")
        legacy_df = self._strip_unwanted_columns(legacy_df, label="legacy")

        logger.info(
            "compare: leído PRISMA={} filas × {} cols, LEGACY={} filas × {} cols",
            len(prisma_df),
            len(prisma_df.columns),
            len(legacy_df),
            len(legacy_df.columns),
        )
        return prisma_df, legacy_df

    def _strip_unwanted_columns(
        self, df: pd.DataFrame, *, label: str
    ) -> pd.DataFrame:
        """Descarta ``Unnamed: N`` (index fantasma de pandas) + ``ignore_columns``."""
        unnamed = [c for c in df.columns if _UNNAMED_REGEX.match(str(c))]
        ignored = [c for c in self.ignore_columns if c in df.columns]
        to_drop = list({*unnamed, *ignored})
        if to_drop:
            logger.info("compare: descartando de {}: {}", label, to_drop)
            df = df.drop(columns=to_drop)
        return df

    # ---- Paso 2: validación estructural ---------------------------------

    def _validate_structure(
        self, prisma: pd.DataFrame, legacy: pd.DataFrame
    ) -> StructuralReport:
        """Verifica set de columnas, número de filas, dtypes."""
        prisma_cols = list(prisma.columns)
        legacy_cols = list(legacy.columns)
        only_p = sorted(set(prisma_cols) - set(legacy_cols))
        only_l = sorted(set(legacy_cols) - set(prisma_cols))
        columns_match = not only_p and not only_l
        rows_match = len(prisma) == len(legacy)

        dtypes: list[DtypeRow] = []
        for col in prisma_cols:
            p_dt = str(prisma[col].dtype)
            l_dt = str(legacy[col].dtype) if col in legacy.columns else "—"
            dtypes.append(
                DtypeRow(
                    column=col,
                    prisma_dtype=p_dt,
                    legacy_dtype=l_dt,
                    match=p_dt == l_dt,
                )
            )

        report = StructuralReport(
            prisma_rows=len(prisma),
            legacy_rows=len(legacy),
            prisma_columns_ordered=prisma_cols,
            legacy_columns_ordered=legacy_cols,
            columns_match=columns_match,
            rows_match=rows_match,
            only_in_prisma=only_p,
            only_in_legacy=only_l,
            column_dtypes=dtypes,
        )

        if columns_match and rows_match:
            logger.info("compare: estructura compatible ({} filas × {} cols)",
                        len(prisma), len(prisma_cols))
        else:
            logger.warning(
                "compare: estructura INCOMPATIBLE — cols_match={} rows_match={}",
                columns_match, rows_match,
            )

        return report

    # ---- Paso 3: alineación --------------------------------------------

    def _align(
        self,
        prisma: pd.DataFrame,
        legacy: pd.DataFrame,
        structural: StructuralReport,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Reordena columnas legacy al orden PRISMA + sort por key_columns.

        Marca ``structural.key_alignment_ok=False`` si tras el sort las
        ``key_columns`` no son idénticas fila a fila (lo cual indica
        que hay filas en un archivo que no están en el otro).
        """
        legacy_ordered = legacy[structural.prisma_columns_ordered].copy()

        missing_keys = [k for k in self.key_columns if k not in prisma.columns]
        if missing_keys:
            structural.key_alignment_ok = False
            structural.key_alignment_notes.append(
                f"key_columns ausentes: {missing_keys}"
            )
            logger.error("compare: key_columns ausentes: {}", missing_keys)
            return prisma, legacy_ordered

        prisma_sorted = (
            prisma.sort_values(by=list(self.key_columns), kind="mergesort")
            .reset_index(drop=True)
        )
        legacy_sorted = (
            legacy_ordered.sort_values(by=list(self.key_columns), kind="mergesort")
            .reset_index(drop=True)
        )

        # Validar que las llaves alinean fila a fila.
        keys_equal = True
        for k in self.key_columns:
            cmp = prisma_sorted[k].astype(object).fillna(_NAN_REPR) == legacy_sorted[k].astype(object).fillna(_NAN_REPR)
            if not cmp.all():
                keys_equal = False
                mismatch_count = int((~cmp).sum())
                structural.key_alignment_notes.append(
                    f"{k}: {mismatch_count} filas no alinean tras sort"
                )

        structural.key_alignment_ok = keys_equal
        if keys_equal:
            logger.info("compare: key_columns alinean tras sort ({})",
                        list(self.key_columns))
        else:
            logger.error(
                "compare: key_columns NO alinean: {}",
                structural.key_alignment_notes,
            )

        return prisma_sorted, legacy_sorted

    # ---- Paso 4: comparación por columna -------------------------------

    def _compare_columns(
        self, prisma: pd.DataFrame, legacy: pd.DataFrame
    ) -> list[ColumnDivergence]:
        """Compara columna por columna y produce una lista de divergencias.

        Las ``key_columns`` se incluyen también — si difieren ahí, el sort
        falló y ya se reportó.
        """
        results: list[ColumnDivergence] = []
        n = len(prisma)
        for col in prisma.columns:
            logger.info("compare: comparando columna '{}'", col)
            p_series = prisma[col]
            l_series = legacy[col]
            mask = self._divergence_mask(p_series, l_series)
            total_div = int(mask.sum())
            if total_div == 0:
                results.append(
                    ColumnDivergence(
                        column=col,
                        total_divergences=0,
                        total_rows=n,
                        classification_counts=Counter(),
                        dominant_type="",
                        unique_patterns=0,
                        top_patterns=[],
                    )
                )
                continue

            classifications = self._classify_pairs(
                p_series[mask], l_series[mask]
            )
            class_counts = Counter(classifications)
            dominant = class_counts.most_common(1)[0][0]

            pattern_counter = self._build_pattern_counter(
                p_series[mask], l_series[mask]
            )
            top = pattern_counter.most_common(self.max_patterns)

            results.append(
                ColumnDivergence(
                    column=col,
                    total_divergences=total_div,
                    total_rows=n,
                    classification_counts=class_counts,
                    dominant_type=dominant,
                    unique_patterns=len(pattern_counter),
                    top_patterns=[(p, l, c) for (p, l), c in top],
                )
            )
        return results

    def _divergence_mask(
        self, p_series: pd.Series, l_series: pd.Series
    ) -> pd.Series:
        """Retorna mask booleana (True = divergente) para una columna.

        Lógica:

        - Ambos NaN → no divergente.
        - Exactamente uno NaN → divergente.
        - Ambos no-NaN:
            - Si dtypes numéricos: ``~np.isclose(..., atol=self.atol)``.
            - Si dtypes datetime: comparación exacta.
            - Si dtypes object/string: comparación exacta o lowercased
              según ``self.ignore_case``.
        """
        p_nan = p_series.isna()
        l_nan = l_series.isna()
        one_nan = p_nan ^ l_nan
        both_valid = ~p_nan & ~l_nan

        diverge = pd.Series(False, index=p_series.index)
        diverge |= one_nan

        if not both_valid.any():
            return diverge

        p_v = p_series[both_valid]
        l_v = l_series[both_valid]
        is_p_num = pd.api.types.is_numeric_dtype(p_series)
        is_l_num = pd.api.types.is_numeric_dtype(l_series)
        is_p_dt = pd.api.types.is_datetime64_any_dtype(p_series)
        is_l_dt = pd.api.types.is_datetime64_any_dtype(l_series)

        if is_p_num and is_l_num:
            with np.errstate(invalid="ignore"):
                val_diff = ~np.isclose(
                    p_v.astype(float).to_numpy(),
                    l_v.astype(float).to_numpy(),
                    atol=self.atol,
                    equal_nan=False,
                )
        elif is_p_dt and is_l_dt:
            val_diff = (p_v != l_v).to_numpy()
        else:
            p_str = p_v.astype(str)
            l_str = l_v.astype(str)
            if self.ignore_case:
                val_diff = (p_str.str.lower() != l_str.str.lower()).to_numpy()
            else:
                val_diff = (p_str != l_str).to_numpy()

        diverge_idx = p_v.index[val_diff]
        diverge.loc[diverge_idx] = True
        return diverge

    def _classify_pairs(
        self, p_div: pd.Series, l_div: pd.Series
    ) -> list[str]:
        """Clasifica cada par divergente según la taxonomía del reporte."""
        classifications: list[str] = []
        for p, l in zip(p_div.to_list(), l_div.to_list()):
            classifications.append(self._classify_single(p, l))
        return classifications

    @staticmethod
    def _classify_single(p, l) -> str:
        p_nan = pd.isna(p)
        l_nan = pd.isna(l)
        if p_nan ^ l_nan:
            return "null_mismatch"
        if p_nan and l_nan:
            return "value_mismatch"  # no debería ocurrir (mask los excluye)
        if isinstance(p, str) and isinstance(l, str):
            if p.lower() == l.lower():
                return "case_difference"
            return "value_mismatch"
        if isinstance(p, (int, float)) and isinstance(l, (int, float)):
            try:
                if float(p) == float(l) and type(p) is not type(l):
                    return "type_mismatch"
            except (TypeError, ValueError):
                pass
            return "value_mismatch"
        if type(p) is not type(l):
            return "type_mismatch"
        return "value_mismatch"

    def _build_pattern_counter(
        self, p_div: pd.Series, l_div: pd.Series
    ) -> Counter[tuple[str, str]]:
        """Construye el counter de patrones ``(prisma_val, legacy_val) → N``."""
        counter: Counter[tuple[str, str]] = Counter()
        for p, l in zip(p_div.to_list(), l_div.to_list()):
            counter[(self._repr_val(p), self._repr_val(l))] += 1
        return counter

    @staticmethod
    def _repr_val(v) -> str:
        if pd.isna(v):
            return _NAN_REPR
        if isinstance(v, str):
            return v
        return str(v)

    # ---- Paso 6: render del reporte markdown ---------------------------

    def _render_report(
        self,
        *,
        structural: StructuralReport,
        column_divergences: list[ColumnDivergence],
        rows_compared: int,
        total_cell_divergences: int,
        has_value_divergences: bool,
    ) -> str:
        """Genera el reporte markdown final."""
        lines: list[str] = []
        a = lines.append

        a("# Reporte de Paridad PRISMA vs Legacy")
        a("")
        a(f"Fecha: {datetime.now().isoformat(timespec='seconds')}")
        a(f"PRISMA: `{self.prisma_path}` ({_human_size(self.prisma_path)}, {structural.prisma_rows:,} filas)")
        a(f"LEGACY: `{self.legacy_path}` ({_human_size(self.legacy_path)}, {structural.legacy_rows:,} filas)")
        a("")

        # Resumen ejecutivo.
        a("## Resumen ejecutivo")
        a("")
        state = self._compute_state(structural, has_value_divergences)
        a(f"- **Estado**: {state}")
        a(f"- Filas comparadas: {rows_compared:,}")
        a(f"- Columnas comparadas: {len(structural.prisma_columns_ordered)}")
        a(f"- Divergencias totales (celdas): {total_cell_divergences:,}")
        if column_divergences:
            type_totals: Counter[str] = Counter()
            for d in column_divergences:
                type_totals.update(d.classification_counts)
            for typ, n in type_totals.most_common():
                a(f"  - {typ}: {n:,}")
        a("")

        # Comparación estructural.
        a("## Comparación estructural")
        a("")
        a("| Métrica | PRISMA | Legacy | OK |")
        a("|---|---|---|---|")
        a(f"| filas | {structural.prisma_rows:,} | {structural.legacy_rows:,} | {_check(structural.rows_match)} |")
        a(f"| columnas (set) | {len(structural.prisma_columns_ordered)} | {len(structural.legacy_columns_ordered)} | {_check(structural.columns_match)} |")
        a(f"| key_columns alinean | — | — | {_check(structural.key_alignment_ok)} |")
        a("")
        if structural.only_in_prisma:
            a(f"- Sólo en PRISMA: `{structural.only_in_prisma}`")
        if structural.only_in_legacy:
            a(f"- Sólo en LEGACY: `{structural.only_in_legacy}`")
        if structural.key_alignment_notes:
            a("- Notas de alineación de keys:")
            for note in structural.key_alignment_notes:
                a(f"  - {note}")
        a("")

        # Tipos de datos por columna (sección obligatoria — ajuste 1).
        a("### Tipos de datos por columna")
        a("")
        a("| Columna | PRISMA | Legacy | Match |")
        a("|---|---|---|---|")
        for d in structural.column_dtypes:
            marker = (
                "✓"
                if d.match
                else "⚠️ dtype distinto"
            )
            # Si distinto, intentar añadir contexto sobre si los valores son equivalentes
            if not d.match:
                cd = next((c for c in column_divergences if c.column == d.column), None)
                if cd is not None and cd.total_divergences == 0:
                    marker = "⚠️ dtype distinto (valores equivalentes)"
            a(f"| {d.column} | `{d.prisma_dtype}` | `{d.legacy_dtype}` | {marker} |")
        a("")

        # Divergencias por columna.
        a("## Divergencias por columna")
        a("")
        cols_with_div = [d for d in column_divergences if d.total_divergences > 0]
        if not cols_with_div:
            a("_Cero divergencias a nivel valor._")
            a("")
        for d in cols_with_div:
            self._render_column_section(lines, d, rows_compared)

        # Conclusión.
        a("## Conclusión")
        a("")
        a(self._conclude(structural, has_value_divergences, total_cell_divergences))
        a("")

        return "\n".join(lines)

    def _render_column_section(
        self,
        lines: list[str],
        d: ColumnDivergence,
        rows_compared: int,
    ) -> None:
        a = lines.append
        pct = (d.total_divergences / rows_compared * 100) if rows_compared else 0
        a(f"### Columna: `{d.column}`")
        a("")
        a(f"- Total divergencias: **{d.total_divergences:,} / {rows_compared:,} ({pct:.1f}%)**")
        a(f"- Tipo dominante: `{d.dominant_type}`")
        if d.classification_counts:
            a("- Conteo por tipo:")
            for typ, n in d.classification_counts.most_common():
                a(f"  - {typ}: {n:,}")
        a(f"- Patrones únicos detectados: **{d.unique_patterns:,}**")
        a("")
        if d.top_patterns:
            a(f"Top {len(d.top_patterns)} patrones (por ocurrencias):")
            a("")
            a("| Patrón PRISMA → Legacy | Ocurrencias |")
            a("|---|---|")
            for p_val, l_val, count in d.top_patterns:
                p_safe = _md_safe(p_val)
                l_safe = _md_safe(l_val)
                a(f"| `{p_safe}` → `{l_safe}` | {count:,} |")
            a("")

    # ---- Helpers de reporte --------------------------------------------

    def _compute_state(
        self,
        structural: StructuralReport,
        has_value_divergences: bool,
    ) -> str:
        if not structural.compatible:
            return "✗ ESTRUCTURALMENTE INCOMPATIBLE"
        if has_value_divergences:
            return "⚠️ DIVERGENCIAS DE VALOR DETECTADAS"
        return "✓ PARIDAD EXACTA (a nivel valor; dtype mismatches en sección estructural si las hay)"

    def _conclude(
        self,
        structural: StructuralReport,
        has_value_divergences: bool,
        total_cell_divergences: int,
    ) -> str:
        if not structural.compatible:
            return (
                "Los archivos no son estructuralmente compatibles. "
                "Revisar la sección de comparación estructural y "
                "regenerar el output si corresponde."
            )
        if has_value_divergences:
            return (
                f"Se detectaron {total_cell_divergences:,} divergencias "
                "de valor. Revisar cada columna en la sección "
                "'Divergencias por columna' para decidir si son "
                "esperadas, bugs de PRISMA, o correcciones legítimas "
                "sobre el legacy."
            )
        return (
            "PRISMA produce un output funcionalmente idéntico al legacy "
            "a nivel de valor. Si hay diferencias de dtype, están "
            "documentadas en la sección 'Tipos de datos por columna' "
            "y no afectan el contenido; el cliente Power BI debe "
            "validar si las consume correctamente."
        )


# ---- Utilidades de presentación ------------------------------------------


def _check(ok: bool) -> str:
    return "✓" if ok else "✗"


def _human_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _md_safe(value: str) -> str:
    """Escapa pipes y newlines para que no rompan tablas markdown."""
    return value.replace("|", "\\|").replace("\n", " ⏎ ")


# ---- CLI -----------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compara indicators1.xlsx generado por PRISMA contra el "
            "archivo de referencia del notebook legacy."
        )
    )
    parser.add_argument("--prisma", default=_DEFAULT_PRISMA, help="Ruta al output de PRISMA")
    parser.add_argument("--legacy", default=_DEFAULT_LEGACY, help="Ruta al output legacy de referencia")
    parser.add_argument(
        "--key-columns",
        nargs="+",
        default=list(_DEFAULT_KEY_COLUMNS),
        help="Columnas que identifican cada fila (default: origen_caso numero_caso)",
    )
    parser.add_argument(
        "--ignore-columns",
        nargs="*",
        default=[],
        help="Columnas adicionales a descartar antes de comparar",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Ruta de salida del reporte markdown (default: stdout)",
    )
    parser.add_argument(
        "--max-divergences",
        type=int,
        default=_DEFAULT_MAX_PATTERNS,
        help="Cantidad máxima de patrones a listar por columna (default: 10)",
    )
    parser.add_argument(
        "--float-tolerance",
        type=float,
        default=_DEFAULT_ATOL,
        help="Tolerancia absoluta para comparación de floats (default: 1e-3)",
    )
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Si se pasa, ignora diferencias de casing en strings",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    comparator = OutputComparator(
        prisma_path=Path(args.prisma),
        legacy_path=Path(args.legacy),
        key_columns=tuple(args.key_columns),
        ignore_columns=tuple(args.ignore_columns),
        max_patterns=args.max_divergences,
        atol=args.float_tolerance,
        ignore_case=args.ignore_case,
    )
    result, report = comparator.run()

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        logger.info("compare: reporte escrito en {}", report_path)
    else:
        sys.stdout.write(report)
        sys.stdout.write("\n")

    if not result.structural.compatible:
        return 2
    if result.has_value_divergences:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
