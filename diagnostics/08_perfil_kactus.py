#!/usr/bin/env python3
"""
Diagnóstico 08 — Perfil de Kactus para resolución de identidades

Objetivo:
    Entender qué porcentaje de las cédulas que aparecen en Discovery se pueden
    resolver consultando Kactus, sin necesidad de ir a LDAP. Esto permite
    diseñar la estrategia óptima del módulo identity/resolver.py:
    "Kactus primero, LDAP solo para residuales."

Qué hace:
    - Carga las cédulas que aparecen en Discovery (campo username_ufinal con
      valores que son sólo dígitos).
    - Las cruza contra Kactus.
    - Reporta cuántas se resuelven con Kactus, cuántas necesitan LDAP, y el
      ratio de "rescate" que aporta Kactus.

Importante:
    Solo lectura SQL. No transforma ni escribe nada en las BDs.

Uso:
    python diagnostics/08_perfil_kactus.py
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
    conclusion,
    env,
    formato_tiempo,
    guardar_resultado,
    header,
    metrica,
    ok,
    seccion,
    warn,
)


def cargar_cedulas_discovery() -> set[str]:
    """Extrae las cédulas únicas del campo username_ufinal del SP de Discovery."""
    import pyodbc

    conn_str = (
        f"DRIVER={{{env('DISCOVERY_DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
        f"SERVER={env('DISCOVERY_DB_SERVER')};"
        f"DATABASE={env('DISCOVERY_DB_NAME')};"
        f"UID={env('DISCOVERY_DB_USER')};"
        f"PWD={env('DISCOVERY_DB_PASSWORD')};"
    )

    cedulas: set[str] = set()
    with Cronometro("Lectura SP Discovery"):
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()
        cursor.execute("EXEC SP_CASOS_DISCOVERYGTI_V1")

        # Encontrar índice de username_ufinal
        idx = next(
            (i for i, col in enumerate(cursor.description) if col[0] == "username_ufinal"),
            None,
        )
        if idx is None:
            raise RuntimeError("Columna username_ufinal no encontrada en el SP.")

        for fila in cursor.fetchall():
            valor = fila[idx]
            if valor and str(valor).strip().isdigit():
                cedulas.add(str(valor).strip())

        cursor.close()
        conn.close()

    return cedulas


def cargar_cedulas_kactus() -> set[str]:
    """Extrae el set de cédulas conocidas en Kactus."""
    import pyodbc

    conn_str = (
        f"DRIVER={{{env('KACTUS_DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
        f"SERVER={env('KACTUS_DB_SERVER')};"
        f"DATABASE={env('KACTUS_DB_NAME')};"
        f"UID={env('KACTUS_DB_USER')};"
        f"PWD={env('KACTUS_DB_PASSWORD')};"
    )

    query = (
        "select distinct cast(emp.cod_empl as varchar(50)) as cedula "
        "from gn_accaj gn inner join bi_emple emp on gn.COD_EMPL = emp.cod_empl "
        "where CHARINDEX('@', emp.box_mail) > 0"
    )

    cedulas: set[str] = set()
    with Cronometro("Lectura Kactus"):
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()
        cursor.execute(query)
        for fila in cursor.fetchall():
            if fila[0]:
                cedulas.add(str(fila[0]).strip())
        cursor.close()
        conn.close()

    return cedulas


def main() -> None:
    header("Perfil de Kactus — % de identidades resolubles sin LDAP", "08")

    print("  Cruza cédulas que aparecen en Discovery contra Kactus.")
    print("  Determina qué % se resuelve con Kactus y qué % requiere LDAP.")
    print()

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 08 — Perfil de Kactus\n\n")

    seccion("Cargando cédulas de Discovery")
    try:
        cedulas_discovery = cargar_cedulas_discovery()
        ok(f"Discovery: {len(cedulas_discovery):,} cédulas únicas")
    except Exception as e:
        warn(f"No se pudo cargar Discovery: {e}")
        sys.exit(1)

    seccion("Cargando cédulas de Kactus")
    try:
        cedulas_kactus = cargar_cedulas_kactus()
        ok(f"Kactus: {len(cedulas_kactus):,} cédulas únicas")
    except Exception as e:
        warn(f"No se pudo cargar Kactus: {e}")
        sys.exit(1)

    # --- Cruce ---
    seccion("Análisis de cobertura")

    en_ambas = cedulas_discovery & cedulas_kactus
    solo_discovery = cedulas_discovery - cedulas_kactus

    n_total = len(cedulas_discovery)
    n_en_kactus = len(en_ambas)
    n_solo_discovery = len(solo_discovery)

    cobertura_kactus = n_en_kactus / n_total * 100 if n_total > 0 else 0
    necesidad_ldap = n_solo_discovery / n_total * 100 if n_total > 0 else 0

    metrica("Total cédulas en Discovery", f"{n_total:,}")
    metrica("  → Resolubles con Kactus", f"{n_en_kactus:,} ({cobertura_kactus:.1f}%)")
    metrica("  → Necesitan LDAP (no están en Kactus)", f"{n_solo_discovery:,} ({necesidad_ldap:.1f}%)")

    # Construir markdown
    buffer_md.write("## Cobertura de identidades\n\n")
    buffer_md.write(f"- **Total cédulas en Discovery:** {n_total:,}\n")
    buffer_md.write(f"- **En Kactus (resoluble sin LDAP):** {n_en_kactus:,} ({cobertura_kactus:.1f}%)\n")
    buffer_md.write(f"- **Solo en Discovery (requieren LDAP):** {n_solo_discovery:,} ({necesidad_ldap:.1f}%)\n\n")

    # Ejemplos de las que necesitan LDAP
    if solo_discovery:
        ejemplos = list(solo_discovery)[:5]
        buffer_md.write(f"\nEjemplos de cédulas que necesitarían LDAP: {', '.join(ejemplos)}\n")

    # Veredicto
    if cobertura_kactus > 90:
        veredicto = (
            f"Kactus cubre el {cobertura_kactus:.1f}% de las cédulas que aparecen en\n"
            f"Discovery. La estrategia óptima es:\n"
            f"  1. Construir el dict cédula→username desde Kactus al inicio.\n"
            f"  2. Aplicar el dict con .map() a todo Discovery (vectorizado).\n"
            f"  3. Solo las {n_solo_discovery:,} cédulas residuales van a LDAP.\n"
            f"Eso reduce drásticamente la presión sobre LDAP.\n"
        )
    elif cobertura_kactus > 50:
        veredicto = (
            f"Kactus cubre solo el {cobertura_kactus:.1f}%. Una buena parte\n"
            f"({n_solo_discovery:,} cédulas) sigue requiriendo LDAP.\n"
            f"La optimización LDAP (batch + persistente) sigue siendo crítica.\n"
        )
    else:
        veredicto = (
            f"Kactus cubre solo el {cobertura_kactus:.1f}%. La mayoría de cédulas\n"
            f"({n_solo_discovery:,}) requieren LDAP. La optimización del cliente\n"
            f"LDAP es absolutamente prioritaria — no se puede evitar pasando por Kactus.\n"
        )

    conclusion(
        f"{veredicto}\n"
        f"Este es el último diagnóstico. Con los resultados de los 8 scripts\n"
        f"ya tenemos evidencia empírica para diseñar la Fase 2."
    )

    guardar_resultado("08_perfil_kactus", buffer_md.getvalue())


if __name__ == "__main__":
    main()