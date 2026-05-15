"""Tests unitarios de :mod:`prisma_gti.transformers.date_handling`."""

from __future__ import annotations

import pandas as pd
import pytest

from prisma_gti.core import TransformerError
from prisma_gti.transformers.date_handling import (
    add_date_features,
    parse_date_column,
)


class TestParseDateColumn:
    def test_parses_12h_with_ampm(self) -> None:
        series = pd.Series(["3/5/2026 9:14:30 AM"])
        result = parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2026-03-05 09:14:30")

    def test_parses_24h_format(self) -> None:
        series = pd.Series(["4/6/2026 17:00:03"])
        result = parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2026-04-06 17:00:03")

    def test_parses_iso_format(self) -> None:
        series = pd.Series(["2026-03-05 09:14:30"])
        result = parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2026-03-05 09:14:30")

    def test_mixed_formats_in_same_series(self) -> None:
        series = pd.Series(
            ["3/5/2026 9:14:30 AM", "2026-04-06 17:00:03"]
        )
        result = parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2026-03-05 09:14:30")
        assert result.iloc[1] == pd.Timestamp("2026-04-06 17:00:03")

    def test_nan_propagates_as_nat(self) -> None:
        series = pd.Series([None, "2026-01-01 00:00:00"])
        result = parse_date_column(series, errors="coerce")
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == pd.Timestamp("2026-01-01 00:00:00")

    def test_empty_series_returns_empty(self) -> None:
        result = parse_date_column(pd.Series([], dtype=object))
        assert len(result) == 0

    def test_unparseable_with_raise_raises(self) -> None:
        series = pd.Series(["no es fecha"])
        with pytest.raises(TransformerError):
            parse_date_column(series, errors="raise")

    def test_unparseable_with_coerce_yields_nat(self) -> None:
        series = pd.Series(["no es fecha", "2026-01-01 00:00:00"])
        result = parse_date_column(series, errors="coerce")
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == pd.Timestamp("2026-01-01 00:00:00")

    def test_returns_datetime64_dtype(self) -> None:
        series = pd.Series(["2026-01-01 00:00:00"])
        result = parse_date_column(series)
        assert pd.api.types.is_datetime64_any_dtype(result)

    def test_preserves_index(self) -> None:
        series = pd.Series(
            ["2026-01-01 00:00:00", "2026-02-02 00:00:00"],
            index=[5, 10],
        )
        result = parse_date_column(series)
        assert list(result.index) == [5, 10]


class TestAddDateFeatures:
    def test_adds_three_columns(self) -> None:
        df = pd.DataFrame(
            {"fecha": pd.to_datetime(["2026-03-05 09:14:30"])}
        )
        out = add_date_features(df, "fecha")
        assert out["fecha_anio"].iloc[0] == 2026
        assert out["fecha_mes"].iloc[0] == 3
        assert out["fecha_dia"].iloc[0] == 5

    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"otra": [1]})
        with pytest.raises(TransformerError):
            add_date_features(df, "fecha")

    def test_non_datetime_column_raises(self) -> None:
        df = pd.DataFrame({"fecha": ["2026-03-05"]})
        with pytest.raises(TransformerError):
            add_date_features(df, "fecha")

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame(
            {"fecha": pd.to_datetime(["2026-03-05"])}
        )
        _ = add_date_features(df, "fecha")
        assert "fecha_anio" not in df.columns

    def test_nat_yields_nan_features(self) -> None:
        df = pd.DataFrame(
            {"fecha": pd.to_datetime([None, "2026-03-05"])}
        )
        out = add_date_features(df, "fecha")
        assert pd.isna(out["fecha_anio"].iloc[0])
        assert out["fecha_anio"].iloc[1] == 2026
