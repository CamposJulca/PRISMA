#!/usr/bin/env python3
"""
Diagnóstico 06 — iterrows() anidado vs vectorización con .map()/merge

Objetivo:
    Replicar empíricamente el patrón problemático del notebook (Bloque 18)
    sobre datos sintéticos del mismo orden de magnitud, para medir cuánto
    se gana con la migración a operaciones vectorizadas.

    Este es el segundo cuello de botella más importante identificado en la
    Fase 1 — siete bucles `iterrows()` anidados con complejidad O(N·M).

Qué hace:
    Genera un dataset sintético de tamaño realista (configurable) y compara:
      A) Patrón actual: doble for con iterrows() + .loc[]
      B) Optimizado: .map() con diccionario precomputado
      C) Optimizado: pd.merge

    Reporta tiempos y verifica que ambos producen el mismo resultado.

Importante:
    No lee ni escribe nada externo. Todo es sintético en memoria.

Uso:
    python diagnostics/06_iterrows_vs_vectorizado.py [N] [M]

    N = filas del dataframe principal (default 5000)
    M = filas del dataframe de lookup (default 1000)
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
    conclusion,
    formato_tiempo,
    guardar_resultado,
    header,
    metrica,
    ok,
    seccion,
    warn,
)


def generar_datos_sinteticos(n: int, m: int):
    """
    Genera dos DataFrames sintéticos que reproducen el patrón del notebook:
    - df_principal con columna username_ufinal donde algunos valores son
      cédulas (sólo dígitos) que necesitan resolverse contra lookup.
    - df_lookup (simula kactus) con columnas cedula y username.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)

    # df_lookup (Kactus simulado)
    lookup = pd.DataFrame({
        "cedula": [str(10000000 + i) for i in range(m)],
        "username": [f"user_{i}" for i in range(m)],
        "NombreCompleto": [f"Usuario Apellido {i}" for i in range(m)],
    })

    # df_principal: 70% tienen username válido, 30% tienen cédula
    n_cedulas = int(n * 0.3)
    n_validos = n - n_cedulas

    cedulas_existentes = rng.choice(lookup["cedula"].values, size=n_cedulas, replace=True)
    usernames_validos = [f"existing_user_{i}" for i in range(n_validos)]

    valores = list(cedulas_existentes) + usernames_validos
    rng.shuffle(valores)

    principal = pd.DataFrame({
        "numero_caso": range(n),
        "username_ufinal": valores,
        "usuariofinal": [None] * n,
    })

    return principal, lookup


def estrategia_a_iterrows(df_principal, df_lookup):
    """A) Patrón actual del notebook: doble loop iterrows()."""
    import pandas as pd

    df = df_principal.copy()

    with Cronometro() as t:
        for i, _fila in df.iterrows():
            valor = df.loc[i, "username_ufinal"]
            if str(valor).isdigit():
                for j, _f in df_lookup.iterrows():
                    if df_lookup.loc[j, "cedula"] == valor:
                        df.loc[i, "username_ufinal"] = df_lookup.loc[j, "username"]
                        df.loc[i, "usuariofinal"] = df_lookup.loc[j, "NombreCompleto"]
                        break

    return t.duracion, df


def estrategia_b_map(df_principal, df_lookup):
    """B) Optimizado con .map() + diccionario precomputado."""
    df = df_principal.copy()

    with Cronometro() as t:
        # Precompute dicts
        ced_to_user = dict(zip(df_lookup["cedula"], df_lookup["username"]))
        ced_to_nombre = dict(zip(df_lookup["cedula"], df_lookup["NombreCompleto"]))

        # Mascara: filas cuyo username_ufinal es solo dígitos
        es_cedula = df["username_ufinal"].astype(str).str.isdigit()

        # Aplicar el mapeo
        df.loc[es_cedula, "usuariofinal"] = df.loc[es_cedula, "username_ufinal"].map(ced_to_nombre)
        df.loc[es_cedula, "username_ufinal"] = df.loc[es_cedula, "username_ufinal"].map(
            ced_to_user
        ).fillna(df.loc[es_cedula, "username_ufinal"])

    return t.duracion, df


def estrategia_c_merge(df_principal, df_lookup):
    """C) Optimizado con pd.merge."""
    import pandas as pd

    df = df_principal.copy()

    with Cronometro() as t:
        # Hacer merge contra todo df, manteniendo el índice original
        merged = df.merge(
            df_lookup[["cedula", "username", "NombreCompleto"]],
            left_on="username_ufinal",
            right_on="cedula",
            how="left",
        )
        # merged tiene los mismos índices que df (left merge preserva orden)
        merged.index = df.index

        # Solo actualizar donde el merge encontró match (es decir, donde
        # username_ufinal era una cédula presente en lookup)
        mask_match = merged["username"].notna()
        df.loc[mask_match, "usuariofinal"] = merged.loc[mask_match, "NombreCompleto"]
        df.loc[mask_match, "username_ufinal"] = merged.loc[mask_match, "username"]

    return t.duracion, df


def main() -> None:
    header("iterrows() anidado vs vectorización", "06")

    print("  Compara el patrón del Bloque 18 del notebook contra dos versiones")
    print("  vectorizadas. Mide tiempos sobre datos sintéticos comparables a")
    print("  los volúmenes reales del proceso.")
    print()

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    m = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 06 — iterrows vs vectorizado\n\n")

    seccion("Configuración")
    metrica("N (filas df_principal)", f"{n:,}")
    metrica("M (filas df_lookup)", f"{m:,}")
    metrica("Iteraciones nominales (peor caso)", f"{n * m:,}")

    seccion("Generando datos sintéticos")
    df_principal, df_lookup = generar_datos_sinteticos(n, m)
    metrica("df_principal", f"{len(df_principal):,} filas")
    metrica("df_lookup", f"{len(df_lookup):,} filas")
    n_cedulas = df_principal["username_ufinal"].astype(str).str.isdigit().sum()
    metrica("Filas que requieren resolución", f"{n_cedulas:,}")

    # --- Estrategia A: solo si N no es enorme (de lo contrario tarda demasiado) ---
    seccion("Estrategia A — iterrows() anidado (patrón notebook)")
    if n * m > 50_000_000:
        warn(f"N*M = {n * m:,} es muy grande. Saltando estrategia A para no esperar minutos.")
        warn("Re-ejecutar con valores más pequeños si se desea medir esta estrategia.")
        t_a = None
        df_a = None
    else:
        try:
            t_a, df_a = estrategia_a_iterrows(df_principal, df_lookup)
            ok(f"A completada en {formato_tiempo(t_a)}")
        except Exception as e:
            warn(f"A falló: {e}")
            t_a, df_a = None, None

    # --- Estrategia B ---
    seccion("Estrategia B — .map() con diccionario precomputado")
    t_b, df_b = estrategia_b_map(df_principal, df_lookup)
    ok(f"B completada en {formato_tiempo(t_b)}")

    # --- Estrategia C ---
    seccion("Estrategia C — pd.merge")
    t_c, df_c = estrategia_c_merge(df_principal, df_lookup)
    ok(f"C completada en {formato_tiempo(t_c)}")

    # --- Validación de equivalencia ---
    seccion("Validación: ¿producen el mismo resultado?")
    if df_a is not None:
        equivalente_ab = df_a["username_ufinal"].equals(df_b["username_ufinal"])
        ok(f"A ≡ B: {equivalente_ab}")
    equivalente_bc = df_b["username_ufinal"].equals(df_c["username_ufinal"])
    ok(f"B ≡ C: {equivalente_bc}")

    # --- Resumen ---
    seccion("Resumen comparativo")
    if t_a:
        metrica("A — iterrows() anidado", formato_tiempo(t_a))
    metrica("B — .map() con dict", formato_tiempo(t_b))
    metrica("C — pd.merge", formato_tiempo(t_c))

    if t_a:
        print()
        speedup_b = t_a / t_b if t_b > 0 else 0
        speedup_c = t_a / t_c if t_c > 0 else 0
        metrica("Speedup A→B", f"{speedup_b:.1f}x")
        metrica("Speedup A→C", f"{speedup_c:.1f}x")

    # Construir markdown
    buffer_md.write(f"## Configuración\n\n- N: {n:,}, M: {m:,}\n\n")
    buffer_md.write("## Tiempos\n\n")
    buffer_md.write("| Estrategia | Tiempo |\n|---|---|\n")
    if t_a:
        buffer_md.write(f"| A — iterrows() anidado | {formato_tiempo(t_a)} |\n")
    buffer_md.write(f"| B — .map() con dict | {formato_tiempo(t_b)} |\n")
    buffer_md.write(f"| C — pd.merge | {formato_tiempo(t_c)} |\n")

    if t_a:
        buffer_md.write(f"\n**Speedup A→B:** {t_a / t_b:.1f}x\n")
        buffer_md.write(f"**Speedup A→C:** {t_a / t_c:.1f}x\n")

    # Veredicto
    if t_a:
        speedup = t_a / t_c
        veredicto = (
            f"Para N={n:,} M={m:,}, iterrows() tarda {formato_tiempo(t_a)},\n"
            f"vectorizado tarda {formato_tiempo(t_c)}. Speedup ~{speedup:.0f}x.\n"
            f"\n"
            f"En el notebook real hay 7 bucles similares. Si cada uno tarda en\n"
            f"promedio {formato_tiempo(t_a)}, la suma de los 7 son ~{formato_tiempo(t_a * 7)},\n"
            f"y vectorizando se reduce a ~{formato_tiempo(t_c * 7)}.\n"
            f"\n"
            f"Migración a operaciones vectorizadas es PRIORIDAD ALTA.\n"
        )
    else:
        veredicto = (
            f"Vectorizado tarda {formato_tiempo(t_c)}. Para confirmar el speedup,\n"
            f"re-ejecutar con N y M más pequeños para que la estrategia A complete.\n"
        )

    conclusion(
        f"{veredicto}\n"
        f"Próximo paso: ejecutar 07_excel_vs_parquet.py para medir el cuello\n"
        f"de las escrituras intermedias."
    )

    guardar_resultado("06_iterrows_vs_vectorizado", buffer_md.getvalue())


if __name__ == "__main__":
    main()