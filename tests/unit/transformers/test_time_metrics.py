"""Tests unitarios de :mod:`prisma_gti.transformers.time_metrics`.

Cubre los casos críticos identificados como bugs históricos:

- ``compute_cumple_ans_atencion`` debe mapear ``NaN > 0`` → ``'NO'``.
- ``compute_tiempo_atencion`` resta ``estimada - atencion``, no
  ``creacion - atencion`` (slack hasta el SLA).
- ``normalize_cumple_ans(invert=True)`` invierte SI ↔ NO sin caer en
  el bug del legacy donde la inversión naive terminaba mapeando todo
  a 'SI'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from prisma_gti.core import TransformerError
from prisma_gti.transformers.time_metrics import (
    GEUS_FIXED_TIME_MINUTES,
    apply_geus_fixed_time,
    compute_cumple_ans_atencion,
    compute_cumple_ans_tareas,
    compute_tiempo_atencion,
    compute_tiempo_transcurrido,
    normalize_cumple_ans,
    parse_glpi_duration_string,
    set_cumple_ans_geus,
)


class TestComputeTiempoTranscurrido:
    def test_basic_difference_in_minutes(self) -> None:
        df = pd.DataFrame(
            {
                "inicio": pd.to_datetime(["2026-01-01 10:00:00"]),
                "fin": pd.to_datetime(["2026-01-01 10:30:00"]),
            }
        )
        out = compute_tiempo_transcurrido(df, "inicio", "fin")
        assert out["tiempoTranscurrido"].iloc[0] == 30.0

    def test_nat_propagates_as_nan(self) -> None:
        df = pd.DataFrame(
            {
                "inicio": pd.to_datetime([None, "2026-01-01 10:00:00"]),
                "fin": pd.to_datetime(
                    ["2026-01-01 10:30:00", "2026-01-01 10:30:00"]
                ),
            }
        )
        out = compute_tiempo_transcurrido(df, "inicio", "fin")
        assert pd.isna(out["tiempoTranscurrido"].iloc[0])
        assert out["tiempoTranscurrido"].iloc[1] == 30.0

    def test_non_datetime_column_raises(self) -> None:
        df = pd.DataFrame({"inicio": ["2026-01-01"], "fin": ["2026-01-02"]})
        with pytest.raises(TransformerError):
            compute_tiempo_transcurrido(df, "inicio", "fin")

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame(
            {
                "inicio": pd.to_datetime(["2026-01-01 10:00:00"]),
                "fin": pd.to_datetime(["2026-01-01 10:30:00"]),
            }
        )
        _ = compute_tiempo_transcurrido(df, "inicio", "fin")
        assert "tiempoTranscurrido" not in df.columns


class TestComputeTiempoAtencion:
    """Regresión clave: la fórmula es (estimada - atencion), NO (creacion - atencion)."""

    def test_estimada_mayor_que_atencion_da_positivo(self) -> None:
        # Atendieron antes del SLA → slack positivo.
        df = pd.DataFrame(
            {
                "estimada": pd.to_datetime(["2026-01-01 11:00:00"]),
                "atencion": pd.to_datetime(["2026-01-01 10:30:00"]),
            }
        )
        out = compute_tiempo_atencion(df, "estimada", "atencion")
        assert out["tiempoTranscurridoAtencion"].iloc[0] == 30.0

    def test_estimada_menor_que_atencion_da_negativo(self) -> None:
        # Atendieron después del SLA → slack negativo.
        df = pd.DataFrame(
            {
                "estimada": pd.to_datetime(["2026-01-01 10:00:00"]),
                "atencion": pd.to_datetime(["2026-01-01 10:30:00"]),
            }
        )
        out = compute_tiempo_atencion(df, "estimada", "atencion")
        assert out["tiempoTranscurridoAtencion"].iloc[0] == -30.0

    def test_nat_propagates_as_nan(self) -> None:
        df = pd.DataFrame(
            {
                "estimada": pd.to_datetime([None]),
                "atencion": pd.to_datetime(["2026-01-01 10:30:00"]),
            }
        )
        out = compute_tiempo_atencion(df, "estimada", "atencion")
        assert pd.isna(out["tiempoTranscurridoAtencion"].iloc[0])


class TestNormalizeCumpleAns:
    def test_cumple_to_si(self) -> None:
        df = pd.DataFrame({"CUMPLE_ANS": ["Cumple", "No cumple"]})
        out = normalize_cumple_ans(df)
        assert out["CUMPLE_ANS"].tolist() == ["SI", "NO"]

    def test_invert_true_inverts_si_and_no(self) -> None:
        """Regresión: invert=True intercambia SI↔NO sin colapsar todo a un valor."""
        df = pd.DataFrame({"CUMPLE_ANS": ["SI", "NO", "SI", "NO"]})
        out = normalize_cumple_ans(df, invert=True)
        assert out["CUMPLE_ANS"].tolist() == ["NO", "SI", "NO", "SI"]

    def test_invert_with_cumple_no_cumple_input(self) -> None:
        df = pd.DataFrame({"CUMPLE_ANS": ["Cumple", "No cumple"]})
        out = normalize_cumple_ans(df, invert=True)
        # Cumple → SI → NO; No cumple → NO → SI.
        assert out["CUMPLE_ANS"].tolist() == ["NO", "SI"]

    def test_missing_column_returns_copy(self) -> None:
        df = pd.DataFrame({"otra": [1]})
        out = normalize_cumple_ans(df)
        assert out is not df

    def test_unknown_values_preserved(self) -> None:
        df = pd.DataFrame({"CUMPLE_ANS": ["VALOR_RARO"]})
        out = normalize_cumple_ans(df)
        assert out["CUMPLE_ANS"].iloc[0] == "VALOR_RARO"

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame({"CUMPLE_ANS": ["Cumple"]})
        _ = normalize_cumple_ans(df)
        assert df["CUMPLE_ANS"].iloc[0] == "Cumple"


class TestComputeCumpleAnsAtencion:
    """Regresión crítica: NaN debe mapear a 'NO', no a NaN (paridad con np.where legacy)."""

    def test_positivo_da_si(self) -> None:
        df = pd.DataFrame({"tiempoTranscurridoAtencion": [10.0]})
        out = compute_cumple_ans_atencion(df)
        assert out["CUMPLE_ANS_ATENCION"].iloc[0] == "SI"

    def test_negativo_da_no(self) -> None:
        df = pd.DataFrame({"tiempoTranscurridoAtencion": [-10.0]})
        out = compute_cumple_ans_atencion(df)
        assert out["CUMPLE_ANS_ATENCION"].iloc[0] == "NO"

    def test_cero_da_no(self) -> None:
        df = pd.DataFrame({"tiempoTranscurridoAtencion": [0.0]})
        out = compute_cumple_ans_atencion(df)
        assert out["CUMPLE_ANS_ATENCION"].iloc[0] == "NO"

    def test_nan_da_no_no_nan(self) -> None:
        """np.where(NaN > 0, 'SI', 'NO') == 'NO' — paridad con legacy."""
        df = pd.DataFrame({"tiempoTranscurridoAtencion": [float("nan")]})
        out = compute_cumple_ans_atencion(df)
        result = out["CUMPLE_ANS_ATENCION"].iloc[0]
        assert result == "NO"
        assert not pd.isna(result)

    def test_mixed_values(self) -> None:
        df = pd.DataFrame(
            {"tiempoTranscurridoAtencion": [10.0, -5.0, float("nan"), 0.0]}
        )
        out = compute_cumple_ans_atencion(df)
        assert out["CUMPLE_ANS_ATENCION"].tolist() == [
            "SI",
            "NO",
            "NO",
            "NO",
        ]

    def test_missing_column_raises(self) -> None:
        with pytest.raises(TransformerError):
            compute_cumple_ans_atencion(pd.DataFrame({"otra": [1]}))


class TestApplyGeusFixedTime:
    def test_assigns_default_300(self) -> None:
        df = pd.DataFrame({"otra": [1, 2, 3]})
        out = apply_geus_fixed_time(df)
        assert (out["tiempoTranscurrido"] == GEUS_FIXED_TIME_MINUTES).all()

    def test_custom_value(self) -> None:
        df = pd.DataFrame({"otra": [1]})
        out = apply_geus_fixed_time(df, value=600)
        assert out["tiempoTranscurrido"].iloc[0] == 600

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame({"otra": []})
        out = apply_geus_fixed_time(df)
        assert len(out) == 0


class TestSetCumpleAnsGeus:
    def test_assigns_si_to_all_rows(self) -> None:
        df = pd.DataFrame({"otra": [1, 2, 3]})
        out = set_cumple_ans_geus(df)
        assert (out["CUMPLE_ANS"] == "SI").all()

    def test_custom_value(self) -> None:
        df = pd.DataFrame({"otra": [1]})
        out = set_cumple_ans_geus(df, value="NO")
        assert out["CUMPLE_ANS"].iloc[0] == "NO"


class TestComputeCumpleAnsTareas:
    def test_negativo_da_si(self) -> None:
        df = pd.DataFrame({"TIEMPO REAL TAREA": [-10.0]})
        out = compute_cumple_ans_tareas(df)
        assert out["CUMPLE_ANS"].iloc[0] == "SI"

    def test_positivo_da_no(self) -> None:
        df = pd.DataFrame({"TIEMPO REAL TAREA": [5.0]})
        out = compute_cumple_ans_tareas(df)
        assert out["CUMPLE_ANS"].iloc[0] == "NO"

    def test_nan_da_no(self) -> None:
        df = pd.DataFrame({"TIEMPO REAL TAREA": [float("nan")]})
        out = compute_cumple_ans_tareas(df)
        assert out["CUMPLE_ANS"].iloc[0] == "NO"

    def test_missing_column_raises(self) -> None:
        with pytest.raises(TransformerError):
            compute_cumple_ans_tareas(pd.DataFrame({"otra": [1]}))


class TestParseGlpiDurationString:
    def test_horas_y_minutos(self) -> None:
        series = pd.Series(["5 horas 30 minutos"])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 5 * 60 + 30

    def test_solo_horas(self) -> None:
        series = pd.Series(["3 horas"])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 180

    def test_solo_minutos(self) -> None:
        series = pd.Series(["45 minutos"])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 45

    def test_singular_hora(self) -> None:
        series = pd.Series(["1 hora 15 minutos"])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 75

    def test_min_abreviado(self) -> None:
        series = pd.Series(["2 horas 10 min"])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 130

    def test_string_vacio_da_cero(self) -> None:
        series = pd.Series([""])
        result = parse_glpi_duration_string(series)
        assert result.iloc[0] == 0

    def test_nan_preserva_nan(self) -> None:
        series = pd.Series([np.nan, "5 horas"])
        result = parse_glpi_duration_string(series)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == 300
