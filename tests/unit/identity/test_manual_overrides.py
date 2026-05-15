"""Tests unitarios de :mod:`prisma_gti.identity.manual_overrides` y de
``IdentityResolver.apply_manual_overrides``.

Incluye los tests de regresión de las decisiones funcionales de Fabián
(12-may-2026): ``fabian_alean``, ``Maryluz Olarte`` (sin ``Cortes``),
``camilo estrada`` (sin ``pelaez``).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from prisma_gti.core import ConfigurationError
from prisma_gti.identity.kactus_index import KactusIndex
from prisma_gti.identity.manual_overrides import (
    ManualOverrides,
    NombrePorUsername,
    load_manual_overrides,
)
from prisma_gti.identity.resolver import IdentityResolver


def _empty_kactus_index() -> KactusIndex:
    return KactusIndex(
        cedula_to_username={},
        cedula_to_nombre={},
        username_to_nombre={},
        username_to_cedula={},
    )


def _build_overrides(
    *,
    patrones_especiales: dict[str, str] | None = None,
    por_numero_caso: dict[int, str] | None = None,
    por_username_alias: dict[str, str] | None = None,
    nombres_por_username: tuple[NombrePorUsername, ...] = (),
    por_responsable: dict[str, tuple[str, str]] | None = None,
    por_usuariofinal: dict[str, tuple[str, str]] | None = None,
) -> ManualOverrides:
    return ManualOverrides(
        patrones_especiales=patrones_especiales or {},
        por_numero_caso=por_numero_caso or {},
        por_username_alias=por_username_alias or {},
        nombres_por_username=nombres_por_username,
        por_responsable=por_responsable or {},
        por_usuariofinal=por_usuariofinal or {},
    )


def _resolver_with(overrides: ManualOverrides) -> IdentityResolver:
    """Crea un resolver con kactus vacío y LDAP no usado.

    ``apply_manual_overrides`` no usa ``self._kactus`` ni ``self._ldap``,
    así que pasar ``None`` como LDAP es seguro para estos tests.
    """
    return IdentityResolver(
        kactus_index=_empty_kactus_index(),
        ldap_resolver=None,  # type: ignore[arg-type]
        manual_overrides=overrides,
    )


# ---- load_manual_overrides ----------------------------------------------


class TestLoadManualOverrides:
    def test_loads_all_six_sections(self, tmp_path: Path) -> None:
        yaml = tmp_path / "overrides.yaml"
        yaml.write_text(
            """
patrones_especiales:
  - {match: "192.168.1.1", username_ufinal: "jperez"}
por_numero_caso:
  - {numero_caso: 100, username_ufinal: "jperez"}
por_username_alias:
  - {from: "j_perez", to: "jperez"}
nombres_por_username:
  - {username: "jperez", nombre: "Juan Pérez", aplica_a: ["responsable"]}
por_responsable:
  - {match: "Juan P", responsable_canonico: "Juan Pérez", username_resp: "jperez"}
por_usuariofinal:
  - {match: "María G", usuariofinal_canonico: "María Gómez", username_ufinal: "mgomez"}
""",
            encoding="utf-8",
        )
        ov = load_manual_overrides(yaml)
        assert ov.patrones_especiales == {"192.168.1.1": "jperez"}
        assert ov.por_numero_caso == {100: "jperez"}
        assert ov.por_username_alias == {"j_perez": "jperez"}
        assert len(ov.nombres_por_username) == 1
        assert ov.nombres_por_username[0].username == "jperez"
        # Las claves de match son normalizadas a strip().lower().
        assert ov.por_responsable == {
            "juan p": ("Juan Pérez", "jperez")
        }
        assert ov.por_usuariofinal == {
            "maría g": ("María Gómez", "mgomez")
        }

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError):
            load_manual_overrides(tmp_path / "no_existe.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("por_numero_caso: [\n  - {numero_caso:", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_manual_overrides(bad)

    def test_aplica_a_invalido_raises(self, tmp_path: Path) -> None:
        yaml = tmp_path / "overrides.yaml"
        yaml.write_text(
            """
nombres_por_username:
  - {username: x, nombre: y, aplica_a: ["columna_invalida"]}
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError):
            load_manual_overrides(yaml)

    def test_empty_yaml_yields_empty_overrides(
        self, tmp_path: Path
    ) -> None:
        yaml = tmp_path / "overrides.yaml"
        yaml.write_text("", encoding="utf-8")
        ov = load_manual_overrides(yaml)
        assert ov.patrones_especiales == {}
        assert ov.por_numero_caso == {}


# ---- IdentityResolver.apply_manual_overrides ----------------------------


class TestApplyManualOverridesPorResponsable:
    """Tests de regresión: reglas de ``por_responsable`` confirmadas por
    Fabián el 12-may-2026.
    """

    def test_fabian_alean_canonical_username(self) -> None:
        """fabian javier alean pena → username_resp = 'fabian_alean'."""
        overrides = _build_overrides(
            por_responsable={
                "fabian javier alean pena": (
                    "fabian javier alean pena",
                    "fabian_alean",
                )
            }
        )
        df = pd.DataFrame(
            {
                "responsable": ["Fabian Javier Alean Pena"],
                "username_resp": ["fjpena"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["username_resp"].iloc[0] == "fabian_alean"
        assert (
            out["username_resp"].iloc[0] != "fjpena"
        )  # regresión: no usa el username viejo
        assert out["responsable"].iloc[0] == "fabian javier alean pena"

    def test_case_insensitive_match_on_responsable(self) -> None:
        overrides = _build_overrides(
            por_responsable={
                "fabian javier alean pena": (
                    "Fabian Alean",
                    "fabian_alean",
                )
            }
        )
        df = pd.DataFrame(
            {
                "responsable": ["FABIAN JAVIER ALEAN PENA"],
                "username_resp": ["fjpena"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["username_resp"].iloc[0] == "fabian_alean"


class TestApplyManualOverridesPorUsuariofinal:
    """Tests de regresión: reglas de ``por_usuariofinal`` confirmadas
    por Fabián el 12-may-2026.
    """

    def test_maryluz_drops_cortes_apellido(self) -> None:
        """Maryluz Cortes Olarte → Maryluz Olarte (sin Cortes).

        El notebook legacy bloque 88 tenía un bug que la mapeaba como
        ``Jenny Borbon``; PRISMA produce el nombre correcto.
        """
        overrides = _build_overrides(
            por_usuariofinal={
                "maryluz cortes olarte": ("Maryluz Olarte", "molarte")
            }
        )
        df = pd.DataFrame(
            {
                "usuariofinal": ["Maryluz Cortes Olarte"],
                "username_ufinal": ["mcortes"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["usuariofinal"].iloc[0] == "Maryluz Olarte"
        assert "Cortes" not in out["usuariofinal"].iloc[0]
        assert out["username_ufinal"].iloc[0] == "molarte"

    def test_camilo_drops_pelaez_apellido(self) -> None:
        """camilo estrada pelaez → camilo estrada (sin pelaez)."""
        overrides = _build_overrides(
            por_usuariofinal={
                "camilo estrada pelaez": ("camilo estrada", "cestrada")
            }
        )
        df = pd.DataFrame(
            {
                "usuariofinal": ["Camilo Estrada Pelaez"],
                "username_ufinal": ["cpelaez"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["usuariofinal"].iloc[0] == "camilo estrada"
        assert "pelaez" not in out["usuariofinal"].iloc[0].lower()
        assert out["username_ufinal"].iloc[0] == "cestrada"


class TestApplyManualOverridesPatrones:
    def test_patron_especial_replaces_ip_with_username(self) -> None:
        overrides = _build_overrides(
            patrones_especiales={"192.168.1.1": "jperez"}
        )
        df = pd.DataFrame({"username_ufinal": ["192.168.1.1", "otro"]})
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["username_ufinal"].tolist() == ["jperez", "otro"]

    def test_patron_especial_case_sensitive(self) -> None:
        overrides = _build_overrides(
            patrones_especiales={"VALOR": "user"}
        )
        df = pd.DataFrame({"username_ufinal": ["valor", "VALOR"]})
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["username_ufinal"].tolist() == ["valor", "user"]


class TestApplyManualOverridesPorNumeroCaso:
    def test_overrides_username_by_numero_caso(self) -> None:
        overrides = _build_overrides(
            por_numero_caso={100: "jperez", 200: "mgomez"}
        )
        df = pd.DataFrame(
            {
                "numero_caso": [100, 200, 300],
                "username_ufinal": ["x", "y", "z"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["username_ufinal"].tolist() == ["jperez", "mgomez", "z"]


class TestApplyManualOverridesNombresPorUsername:
    def test_aplica_solo_a_columnas_listadas(self) -> None:
        rule = NombrePorUsername(
            username="jperez",
            nombre="Juan Pérez Completo",
            aplica_a=("responsable",),
        )
        overrides = _build_overrides(nombres_por_username=(rule,))
        df = pd.DataFrame(
            {
                "responsable": ["X"],
                "usuariofinal": ["Y"],
                "username_resp": ["jperez"],
                "username_ufinal": ["jperez"],
            }
        )
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["responsable"].iloc[0] == "Juan Pérez Completo"
        assert out["usuariofinal"].iloc[0] == "Y"  # no fue listado en aplica_a


class TestApplyManualOverridesEdgeCases:
    def test_empty_overrides_returns_copy(self) -> None:
        overrides = _build_overrides()
        df = pd.DataFrame({"responsable": ["X"]})
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert out["responsable"].iloc[0] == "X"
        assert out is not df

    def test_does_not_mutate_input(self) -> None:
        overrides = _build_overrides(
            por_responsable={"x": ("X CANONICAL", "xuser")}
        )
        df = pd.DataFrame(
            {"responsable": ["X"], "username_resp": ["original"]}
        )
        _ = _resolver_with(overrides).apply_manual_overrides(df)
        assert df["responsable"].iloc[0] == "X"
        assert df["username_resp"].iloc[0] == "original"

    def test_missing_columns_skipped_gracefully(self) -> None:
        overrides = _build_overrides(
            por_responsable={"x": ("X CANONICAL", "xuser")}
        )
        df = pd.DataFrame({"otra": ["dato"]})
        out = _resolver_with(overrides).apply_manual_overrides(df)
        assert "otra" in out.columns
