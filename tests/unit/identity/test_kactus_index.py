"""Tests unitarios de :mod:`prisma_gti.identity.kactus_index`."""

from __future__ import annotations

import pandas as pd

from prisma_gti.identity.kactus_index import KactusIndex, build_kactus_index


def _sample_kactus(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["cedula", "username", "NombreCompleto"])


class TestBuildKactusIndex:
    def test_builds_four_lookups(self) -> None:
        df = _sample_kactus(
            [
                ("123", "jperez", "Juan Pérez"),
                ("456", "mgomez", "María Gómez"),
            ]
        )
        index = build_kactus_index(df)
        assert isinstance(index, KactusIndex)
        assert index.cedula_to_username == {
            "123": "jperez",
            "456": "mgomez",
        }
        assert index.cedula_to_nombre == {
            "123": "Juan Pérez",
            "456": "María Gómez",
        }
        assert index.username_to_nombre == {
            "jperez": "Juan Pérez",
            "mgomez": "María Gómez",
        }
        assert index.username_to_cedula == {
            "jperez": "123",
            "mgomez": "456",
        }

    def test_username_lowercased_in_lookups(self) -> None:
        df = _sample_kactus([("123", "JPEREZ", "Juan Pérez")])
        index = build_kactus_index(df)
        assert index.cedula_to_username["123"] == "jperez"
        assert "jperez" in index.username_to_nombre
        assert "JPEREZ" not in index.username_to_nombre

    def test_nombre_preserves_casing(self) -> None:
        df = _sample_kactus([("123", "jperez", "Juan PÉREZ")])
        index = build_kactus_index(df)
        assert index.cedula_to_nombre["123"] == "Juan PÉREZ"

    def test_strips_whitespace_from_cedula(self) -> None:
        df = _sample_kactus([("  123  ", "jperez", "Juan Pérez")])
        index = build_kactus_index(df)
        assert "123" in index.cedula_to_username
        assert "  123  " not in index.cedula_to_username

    def test_strips_whitespace_from_username(self) -> None:
        df = _sample_kactus([("123", "  jperez  ", "Juan Pérez")])
        index = build_kactus_index(df)
        assert index.cedula_to_username["123"] == "jperez"

    def test_duplicate_cedula_last_wins(self) -> None:
        df = _sample_kactus(
            [
                ("123", "primero", "Primero"),
                ("123", "segundo", "Segundo"),
            ]
        )
        index = build_kactus_index(df)
        assert index.cedula_to_username["123"] == "segundo"
        assert index.cedula_to_nombre["123"] == "Segundo"

    def test_empty_dataframe_yields_empty_index(self) -> None:
        df = _sample_kactus([])
        index = build_kactus_index(df)
        assert index.cedula_to_username == {}
        assert index.cedula_to_nombre == {}
        assert index.username_to_nombre == {}
        assert index.username_to_cedula == {}

    def test_kactus_index_is_frozen(self) -> None:
        df = _sample_kactus([("123", "jperez", "Juan Pérez")])
        index = build_kactus_index(df)
        import pytest

        with pytest.raises(Exception):  # noqa: B017
            index.cedula_to_username = {}  # type: ignore[misc]
