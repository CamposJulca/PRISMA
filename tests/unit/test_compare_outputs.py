"""Tests unitarios de ``scripts/compare_outputs.py``.

Importa el script standalone vía ``importlib`` (no es paquete) y
prueba la clasificación de divergencias y el flujo end-to-end con
Excels sintéticos.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest


def _load_compare_outputs() -> ModuleType:
    """Carga ``scripts/compare_outputs.py`` como módulo aislado."""
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "compare_outputs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_compare_outputs_under_test", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_compare_outputs_under_test"] = module
    spec.loader.exec_module(module)
    return module


compare_outputs = _load_compare_outputs()
OutputComparator = compare_outputs.OutputComparator


def _make_comparator(
    prisma: Path, legacy: Path, **kwargs: object
) -> object:
    return OutputComparator(
        prisma_path=prisma,
        legacy_path=legacy,
        **kwargs,  # type: ignore[arg-type]
    )


# ---- Clasificador estático ------------------------------------------------


class TestClassifySingle:
    """Cubre los 4 tipos de divergencia: case, type, value, null."""

    def test_case_difference(self) -> None:
        assert (
            OutputComparator._classify_single("HOLA", "hola")
            == "case_difference"
        )

    def test_value_mismatch_strings(self) -> None:
        assert (
            OutputComparator._classify_single("foo", "bar")
            == "value_mismatch"
        )

    def test_null_mismatch_one_side_nan(self) -> None:
        assert (
            OutputComparator._classify_single(float("nan"), "x")
            == "null_mismatch"
        )
        assert (
            OutputComparator._classify_single("x", float("nan"))
            == "null_mismatch"
        )

    def test_type_mismatch_int_vs_float_same_value(self) -> None:
        assert (
            OutputComparator._classify_single(1, 1.0) == "type_mismatch"
        )

    def test_value_mismatch_numbers(self) -> None:
        assert (
            OutputComparator._classify_single(1.0, 2.0) == "value_mismatch"
        )

    def test_value_mismatch_different_types_different_values(self) -> None:
        # str vs int, distintos → type_mismatch (fallback).
        result = OutputComparator._classify_single("1", 1)
        assert result == "type_mismatch"


# ---- Divergence mask -----------------------------------------------------


class TestDivergenceMask:
    def test_strings_iguales_no_divergen(self, tmp_path: Path) -> None:
        cmp = _make_comparator(tmp_path / "p.xlsx", tmp_path / "l.xlsx")
        p = pd.Series(["a", "b", "c"])
        l_ = pd.Series(["a", "b", "c"])
        mask = cmp._divergence_mask(p, l_)
        assert mask.sum() == 0

    def test_strings_distintos_divergen(self, tmp_path: Path) -> None:
        cmp = _make_comparator(tmp_path / "p.xlsx", tmp_path / "l.xlsx")
        p = pd.Series(["a", "b"])
        l_ = pd.Series(["a", "X"])
        mask = cmp._divergence_mask(p, l_)
        assert mask.tolist() == [False, True]

    def test_ambos_nan_no_divergen(self, tmp_path: Path) -> None:
        cmp = _make_comparator(tmp_path / "p.xlsx", tmp_path / "l.xlsx")
        p = pd.Series([float("nan"), 1.0])
        l_ = pd.Series([float("nan"), 1.0])
        mask = cmp._divergence_mask(p, l_)
        assert mask.sum() == 0

    def test_uno_nan_diverge(self, tmp_path: Path) -> None:
        cmp = _make_comparator(tmp_path / "p.xlsx", tmp_path / "l.xlsx")
        p = pd.Series([float("nan"), 1.0])
        l_ = pd.Series([2.0, 1.0])
        mask = cmp._divergence_mask(p, l_)
        assert mask.tolist() == [True, False]

    def test_floats_dentro_de_tolerancia_no_divergen(
        self, tmp_path: Path
    ) -> None:
        cmp = _make_comparator(
            tmp_path / "p.xlsx", tmp_path / "l.xlsx", atol=1e-3
        )
        p = pd.Series([1.0, 2.0])
        l_ = pd.Series([1.0005, 2.0])
        mask = cmp._divergence_mask(p, l_)
        assert mask.sum() == 0

    def test_ignore_case_true_no_diverge_por_casing(
        self, tmp_path: Path
    ) -> None:
        cmp = _make_comparator(
            tmp_path / "p.xlsx", tmp_path / "l.xlsx", ignore_case=True
        )
        p = pd.Series(["HOLA"])
        l_ = pd.Series(["hola"])
        mask = cmp._divergence_mask(p, l_)
        assert mask.sum() == 0

    def test_ignore_case_false_diverge_por_casing(
        self, tmp_path: Path
    ) -> None:
        cmp = _make_comparator(
            tmp_path / "p.xlsx", tmp_path / "l.xlsx", ignore_case=False
        )
        p = pd.Series(["HOLA"])
        l_ = pd.Series(["hola"])
        mask = cmp._divergence_mask(p, l_)
        assert mask.iloc[0]


# ---- Strip unwanted columns ---------------------------------------------


class TestStripUnwantedColumns:
    def test_drops_unnamed_columns(self, tmp_path: Path) -> None:
        cmp = _make_comparator(tmp_path / "p.xlsx", tmp_path / "l.xlsx")
        df = pd.DataFrame(
            {"a": [1], "Unnamed: 0": [99], "b": [2]}
        )
        out = cmp._strip_unwanted_columns(df, label="x")
        assert "Unnamed: 0" not in out.columns
        assert list(out.columns) == ["a", "b"]

    def test_drops_ignore_columns(self, tmp_path: Path) -> None:
        cmp = _make_comparator(
            tmp_path / "p.xlsx",
            tmp_path / "l.xlsx",
            ignore_columns=("ignorada",),
        )
        df = pd.DataFrame({"a": [1], "ignorada": [99]})
        out = cmp._strip_unwanted_columns(df, label="x")
        assert "ignorada" not in out.columns


# ---- End-to-end con Excels sintéticos -----------------------------------


def _write_excel(path: Path, df: pd.DataFrame) -> None:
    df.to_excel(path, index=False)


@pytest.fixture
def small_excel_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Par de Excels mínimos con esquema indicators1-like."""
    df_p = pd.DataFrame(
        {
            "origen_caso": ["A", "A"],
            "numero_caso": [1, 2],
            "valor": ["hola", "mundo"],
        }
    )
    df_l = pd.DataFrame(
        {
            "origen_caso": ["A", "A"],
            "numero_caso": [1, 2],
            "valor": ["hola", "mundo"],
        }
    )
    p_path = tmp_path / "prisma.xlsx"
    l_path = tmp_path / "legacy.xlsx"
    _write_excel(p_path, df_p)
    _write_excel(l_path, df_l)
    return p_path, l_path


class TestEndToEnd:
    def test_paridad_exacta_estado_ok(
        self, small_excel_pair: tuple[Path, Path]
    ) -> None:
        p, l_ = small_excel_pair
        cmp = OutputComparator(prisma_path=p, legacy_path=l_)
        result, report = cmp.run()
        assert result.total_cell_divergences == 0
        assert not result.has_value_divergences
        assert result.structural.compatible
        assert "PARIDAD EXACTA" in report

    def test_value_mismatch_detectado(
        self, tmp_path: Path
    ) -> None:
        df_p = pd.DataFrame(
            {"origen_caso": ["A"], "numero_caso": [1], "valor": ["X"]}
        )
        df_l = pd.DataFrame(
            {"origen_caso": ["A"], "numero_caso": [1], "valor": ["Y"]}
        )
        p_path = tmp_path / "p.xlsx"
        l_path = tmp_path / "l.xlsx"
        _write_excel(p_path, df_p)
        _write_excel(l_path, df_l)
        cmp = OutputComparator(prisma_path=p_path, legacy_path=l_path)
        result, _ = cmp.run()
        assert result.has_value_divergences
        assert result.total_cell_divergences == 1

    def test_columns_mismatch_marca_incompatible(
        self, tmp_path: Path
    ) -> None:
        df_p = pd.DataFrame(
            {"origen_caso": ["A"], "numero_caso": [1], "valor": ["X"]}
        )
        df_l = pd.DataFrame(
            {"origen_caso": ["A"], "numero_caso": [1], "OTRA": ["X"]}
        )
        p_path = tmp_path / "p.xlsx"
        l_path = tmp_path / "l.xlsx"
        _write_excel(p_path, df_p)
        _write_excel(l_path, df_l)
        cmp = OutputComparator(prisma_path=p_path, legacy_path=l_path)
        result, _ = cmp.run()
        assert not result.structural.compatible
        assert not result.structural.columns_match

    def test_rows_mismatch_marca_incompatible(
        self, tmp_path: Path
    ) -> None:
        df_p = pd.DataFrame(
            {"origen_caso": ["A", "A"], "numero_caso": [1, 2]}
        )
        df_l = pd.DataFrame(
            {"origen_caso": ["A"], "numero_caso": [1]}
        )
        p_path = tmp_path / "p.xlsx"
        l_path = tmp_path / "l.xlsx"
        _write_excel(p_path, df_p)
        _write_excel(l_path, df_l)
        cmp = OutputComparator(prisma_path=p_path, legacy_path=l_path)
        result, _ = cmp.run()
        assert not result.structural.compatible
        assert not result.structural.rows_match

    def test_archivo_inexistente_levanta(self, tmp_path: Path) -> None:
        cmp = OutputComparator(
            prisma_path=tmp_path / "no_existe.xlsx",
            legacy_path=tmp_path / "no_existe2.xlsx",
        )
        with pytest.raises(FileNotFoundError):
            cmp.run()
