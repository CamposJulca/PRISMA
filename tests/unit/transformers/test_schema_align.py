"""Tests unitarios de :mod:`prisma_gti.transformers.schema_align`."""

from __future__ import annotations

import pandas as pd

from prisma_gti.transformers.schema_align import (
    align_schemas,
    get_indicators1_schema,
)


class TestGetIndicators1Schema:
    def test_returns_list_of_strings(self) -> None:
        schema = get_indicators1_schema()
        assert isinstance(schema, list)
        assert all(isinstance(c, str) for c in schema)

    def test_returns_14_columns(self) -> None:
        assert len(get_indicators1_schema()) == 14

    def test_contains_key_columns(self) -> None:
        schema = get_indicators1_schema()
        assert "numero_caso" in schema
        assert "origen_caso" in schema
        assert "CUMPLE_ANS" in schema

    def test_returns_fresh_list_each_call(self) -> None:
        a = get_indicators1_schema()
        a.append("contaminated")
        b = get_indicators1_schema()
        assert "contaminated" not in b


class TestAlignSchemas:
    def test_adds_missing_columns_with_fill_value(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        aligned = align_schemas({"src": df}, target_columns=["a", "b"])
        out = aligned["src"]
        assert list(out.columns) == ["a", "b"]
        assert out["b"].isna().all()

    def test_drops_extra_columns(self) -> None:
        df = pd.DataFrame({"a": [1], "extra": [99]})
        aligned = align_schemas({"src": df}, target_columns=["a"])
        out = aligned["src"]
        assert list(out.columns) == ["a"]
        assert "extra" not in out.columns

    def test_reorders_columns_to_target_order(self) -> None:
        df = pd.DataFrame({"b": [1], "a": [2]})
        aligned = align_schemas({"src": df}, target_columns=["a", "b"])
        out = aligned["src"]
        assert list(out.columns) == ["a", "b"]

    def test_custom_fill_value(self) -> None:
        df = pd.DataFrame({"a": [1]})
        aligned = align_schemas(
            {"src": df}, target_columns=["a", "b"], fill_value=0
        )
        assert aligned["src"]["b"].iloc[0] == 0

    def test_multiple_dataframes_processed(self) -> None:
        d1 = pd.DataFrame({"a": [1]})
        d2 = pd.DataFrame({"b": [2]})
        aligned = align_schemas(
            {"d1": d1, "d2": d2}, target_columns=["a", "b"]
        )
        assert list(aligned["d1"].columns) == ["a", "b"]
        assert list(aligned["d2"].columns) == ["a", "b"]
        assert aligned["d1"]["a"].iloc[0] == 1
        assert pd.isna(aligned["d1"]["b"].iloc[0])
        assert aligned["d2"]["b"].iloc[0] == 2

    def test_does_not_mutate_inputs(self) -> None:
        df = pd.DataFrame({"a": [1], "extra": [99]})
        _ = align_schemas({"src": df}, target_columns=["a", "b"])
        assert list(df.columns) == ["a", "extra"]

    def test_already_aligned_passes_through(self) -> None:
        df = pd.DataFrame({"a": [1], "b": [2]})
        aligned = align_schemas({"src": df}, target_columns=["a", "b"])
        assert aligned["src"]["a"].iloc[0] == 1
        assert aligned["src"]["b"].iloc[0] == 2

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame()
        aligned = align_schemas({"src": df}, target_columns=["a", "b"])
        assert list(aligned["src"].columns) == ["a", "b"]
        assert len(aligned["src"]) == 0

    def test_preserves_dict_keys(self) -> None:
        d1 = pd.DataFrame({"a": [1]})
        d2 = pd.DataFrame({"a": [2]})
        aligned = align_schemas({"d1": d1, "d2": d2}, target_columns=["a"])
        assert set(aligned.keys()) == {"d1", "d2"}
