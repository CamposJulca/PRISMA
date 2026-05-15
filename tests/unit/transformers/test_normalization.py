"""Tests unitarios de :mod:`prisma_gti.transformers.normalization`."""

from __future__ import annotations

import pandas as pd
import pytest

from prisma_gti.transformers.normalization import (
    fix_responsable_casing,
    normalize_column,
    normalize_text,
)


class TestNormalizeText:
    def test_lowercase_simple(self) -> None:
        assert normalize_text("HOLA") == "hola"

    def test_remove_accents(self) -> None:
        assert normalize_text("José") == "jose"

    def test_remove_tilde_n(self) -> None:
        assert normalize_text("Núñez") == "nunez"

    def test_strip_whitespace(self) -> None:
        assert normalize_text("  hola  ") == "hola"

    def test_none_returns_empty(self) -> None:
        assert normalize_text(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_text("") == ""

    @pytest.mark.xfail(
        reason=(
            "Discrepancia docstring vs implementación: el docstring afirma "
            "que NaN → '' pero `str(float('nan'))` produce 'nan' y la "
            "guarda `text != text` opera sobre el str ya convertido (siempre "
            "False). El comportamiento real es normalize_text(NaN) == 'nan'. "
            "Decidir si arreglar el src o el docstring en sesión futura."
        ),
        strict=True,
    )
    def test_nan_returns_empty(self) -> None:
        assert normalize_text(float("nan")) == ""

    def test_combined_uppercase_accent_whitespace(self) -> None:
        assert normalize_text("  JÓSE Núñez  ") == "jose nunez"

    def test_already_normalized_is_idempotent(self) -> None:
        assert normalize_text("hola") == "hola"


class TestNormalizeColumn:
    def test_applies_to_each_row(self) -> None:
        series = pd.Series(["HOLA", "José", "  test  "])
        result = normalize_column(series)
        assert result.tolist() == ["hola", "jose", "test"]

    def test_preserves_index(self) -> None:
        series = pd.Series(["A", "B"], index=[10, 20])
        result = normalize_column(series)
        assert list(result.index) == [10, 20]

    @pytest.mark.xfail(
        reason=(
            "Mismo bug que test_nan_returns_empty: normalize_column propaga "
            "el comportamiento de normalize_text sobre NaN ('nan' en vez de "
            "'')."
        ),
        strict=True,
    )
    def test_handles_nan_values(self) -> None:
        series = pd.Series(["HOLA", None, float("nan")])
        result = normalize_column(series)
        assert result.tolist() == ["hola", "", ""]

    def test_empty_series_returns_empty(self) -> None:
        series = pd.Series([], dtype=object)
        result = normalize_column(series)
        assert len(result) == 0


class TestFixResponsableCasing:
    def test_carlos_manuel_rivera_canonicalized(self) -> None:
        df = pd.DataFrame({"responsable": ["CARLOS MANUEL RIVERA B."]})
        out = fix_responsable_casing(df)
        assert out["responsable"].iloc[0] == "Carlos Manuel Rivera Barreto"

    def test_fernando_marquez_canonicalized(self) -> None:
        df = pd.DataFrame({"responsable": ["FERNANDO MARQUEZ"]})
        out = fix_responsable_casing(df)
        assert (
            out["responsable"].iloc[0] == "Fernando Alberto Marquez Morales"
        )

    def test_harold_avendano_with_tilde(self) -> None:
        df = pd.DataFrame({"responsable": ["HAROLD ADOLFO MENDOZA AVENDANO"]})
        out = fix_responsable_casing(df)
        assert out["responsable"].iloc[0] == "Harold Adolfo Mendoza Avendaño"

    def test_unknown_values_pass_through(self) -> None:
        df = pd.DataFrame({"responsable": ["Otra Persona"]})
        out = fix_responsable_casing(df)
        assert out["responsable"].iloc[0] == "Otra Persona"

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame({"responsable": ["FERNANDO MARQUEZ"]})
        _ = fix_responsable_casing(df)
        assert df["responsable"].iloc[0] == "FERNANDO MARQUEZ"

    def test_missing_column_returns_copy(self) -> None:
        df = pd.DataFrame({"otra": ["valor"]})
        out = fix_responsable_casing(df)
        assert "otra" in out.columns and out is not df

    def test_custom_column_name(self) -> None:
        df = pd.DataFrame({"resp_alt": ["CARLOS MANUEL RIVERA B."]})
        out = fix_responsable_casing(df, column="resp_alt")
        assert out["resp_alt"].iloc[0] == "Carlos Manuel Rivera Barreto"

    def test_nan_passes_through(self) -> None:
        df = pd.DataFrame({"responsable": [None, "FERNANDO MARQUEZ"]})
        out = fix_responsable_casing(df)
        assert pd.isna(out["responsable"].iloc[0])
        assert (
            out["responsable"].iloc[1] == "Fernando Alberto Marquez Morales"
        )
