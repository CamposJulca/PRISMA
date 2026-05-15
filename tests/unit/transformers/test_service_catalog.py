"""Tests unitarios de :mod:`prisma_gti.transformers.service_catalog`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from prisma_gti.core import ConfigurationError
from prisma_gti.transformers.service_catalog import (
    ServiceCatalog,
    apply_asms_overrides,
    apply_indicadores_overrides,
    apply_proyecto_overrides,
    load_service_catalog,
)


def _catalog(
    indicadores: dict[str, str] | None = None,
    asms: dict[str, str] | None = None,
    proyecto: dict[str, str] | None = None,
) -> ServiceCatalog:
    return ServiceCatalog(
        indicadores_mapping=indicadores or {},
        asms_mapping=asms or {},
        proyecto_mapping=proyecto or {},
    )


class TestApplyIndicadoresOverrides:
    def test_typical_mapping_applied(self) -> None:
        df = pd.DataFrame(
            {"servicio": ["VIEJO", "PASAR_IGUAL", "VIEJO_2"]}
        )
        catalog = _catalog(
            indicadores={"VIEJO": "NUEVO", "VIEJO_2": "NUEVO_2"}
        )
        out = apply_indicadores_overrides(df, catalog)
        assert out["servicio"].tolist() == [
            "NUEVO",
            "PASAR_IGUAL",
            "NUEVO_2",
        ]

    def test_case_sensitive_match(self) -> None:
        df = pd.DataFrame({"servicio": ["viejo", "VIEJO"]})
        catalog = _catalog(indicadores={"VIEJO": "NUEVO"})
        out = apply_indicadores_overrides(df, catalog)
        assert out["servicio"].tolist() == ["viejo", "NUEVO"]

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame({"servicio": ["VIEJO"]})
        catalog = _catalog(indicadores={"VIEJO": "NUEVO"})
        _ = apply_indicadores_overrides(df, catalog)
        assert df["servicio"].iloc[0] == "VIEJO"

    def test_missing_servicio_column_returns_copy(self) -> None:
        df = pd.DataFrame({"otra": [1, 2]})
        catalog = _catalog(indicadores={"VIEJO": "NUEVO"})
        out = apply_indicadores_overrides(df, catalog)
        assert "otra" in out.columns
        assert out is not df

    def test_empty_mapping_is_noop(self) -> None:
        df = pd.DataFrame({"servicio": ["A", "B"]})
        catalog = _catalog()
        out = apply_indicadores_overrides(df, catalog)
        assert out["servicio"].tolist() == ["A", "B"]

    def test_preserves_nan(self) -> None:
        df = pd.DataFrame({"servicio": ["VIEJO", None]})
        catalog = _catalog(indicadores={"VIEJO": "NUEVO"})
        out = apply_indicadores_overrides(df, catalog)
        assert out["servicio"].iloc[0] == "NUEVO"
        assert pd.isna(out["servicio"].iloc[1])


class TestApplyAsmsOverrides:
    def test_typical_mapping_applied(self) -> None:
        df = pd.DataFrame({"servicio": ["ASMS_VIEJO", "OTRO"]})
        catalog = _catalog(asms={"ASMS_VIEJO": "ASMS_NUEVO"})
        out = apply_asms_overrides(df, catalog)
        assert out["servicio"].tolist() == ["ASMS_NUEVO", "OTRO"]

    def test_uses_asms_section_not_indicadores(self) -> None:
        df = pd.DataFrame({"servicio": ["X"]})
        catalog = _catalog(
            indicadores={"X": "X_IND"}, asms={"X": "X_ASMS"}
        )
        out = apply_asms_overrides(df, catalog)
        assert out["servicio"].iloc[0] == "X_ASMS"


class TestApplyProyectoOverrides:
    def test_writes_to_proyecto_when_servicio_matches(self) -> None:
        df = pd.DataFrame(
            {
                "servicio": ["MATCH", "OTRO"],
                "proyecto": ["P_VIEJO", "P_VIEJO_2"],
            }
        )
        catalog = _catalog(proyecto={"MATCH": "P_NUEVO"})
        out = apply_proyecto_overrides(df, catalog)
        assert out["proyecto"].tolist() == ["P_NUEVO", "P_VIEJO_2"]

    def test_no_match_leaves_proyecto_untouched(self) -> None:
        df = pd.DataFrame(
            {"servicio": ["A"], "proyecto": ["ORIGINAL"]}
        )
        catalog = _catalog(proyecto={"OTRO_DISTINTO": "X"})
        out = apply_proyecto_overrides(df, catalog)
        assert out["proyecto"].iloc[0] == "ORIGINAL"

    def test_missing_proyecto_column_returns_copy(self) -> None:
        df = pd.DataFrame({"servicio": ["MATCH"]})
        catalog = _catalog(proyecto={"MATCH": "P_NUEVO"})
        out = apply_proyecto_overrides(df, catalog)
        assert "proyecto" not in out.columns

    def test_empty_mapping_is_noop(self) -> None:
        df = pd.DataFrame(
            {"servicio": ["A"], "proyecto": ["P"]}
        )
        out = apply_proyecto_overrides(df, _catalog())
        assert out["proyecto"].iloc[0] == "P"


class TestLoadServiceCatalog:
    def test_loads_three_sections(self, tmp_path: Path) -> None:
        yaml = tmp_path / "cat.yaml"
        yaml.write_text(
            """
indicadores_overrides:
  - {from: A, to: B}
  - {from: C, to: D}
asms_overrides:
  - {from: X, to: Y}
proyecto_overrides:
  - {match_servicio: SVC, proyecto: PRJ}
""",
            encoding="utf-8",
        )
        catalog = load_service_catalog(yaml)
        assert catalog.indicadores_mapping == {"A": "B", "C": "D"}
        assert catalog.asms_mapping == {"X": "Y"}
        assert catalog.proyecto_mapping == {"SVC": "PRJ"}

    def test_missing_file_raises_configuration_error(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ConfigurationError):
            load_service_catalog(tmp_path / "no_existe.yaml")

    def test_invalid_yaml_raises_configuration_error(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("indicadores_overrides: [\n  - {from: A", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_service_catalog(bad)

    def test_entry_missing_from_key_raises(self, tmp_path: Path) -> None:
        yaml = tmp_path / "cat.yaml"
        yaml.write_text(
            """
indicadores_overrides:
  - {to: Sin_From}
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError):
            load_service_catalog(yaml)

    def test_empty_yaml_yields_empty_catalog(
        self, tmp_path: Path
    ) -> None:
        yaml = tmp_path / "cat.yaml"
        yaml.write_text("", encoding="utf-8")
        catalog = load_service_catalog(yaml)
        assert catalog.indicadores_mapping == {}
        assert catalog.asms_mapping == {}
        assert catalog.proyecto_mapping == {}
