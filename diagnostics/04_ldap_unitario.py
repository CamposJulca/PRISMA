#!/usr/bin/env python3
"""
Diagnóstico 04 — Costo unitario de una búsqueda LDAP

Objetivo:
    Medir el costo real de UNA búsqueda LDAP completa (conexión + bind +
    search + close), replicando exactamente el patrón del notebook actual.
    Este número multiplicado por la cantidad de cédulas a resolver nos da
    el costo total del cuello de botella #1.

Qué hace:
    - Ejecuta 5 búsquedas LDAP individuales (cada una con conexión nueva).
    - Reporta tiempo promedio, mínimo, máximo y desviación.
    - Compara contra el peor caso esperado.

Importante:
    Este script NO modifica nada en LDAP. Solo hace búsquedas read-only.
    Si una cédula no existe, no es un error — simplemente lo reporta.

Uso:
    python diagnostics/04_ldap_unitario.py [cedula1 cedula2 ...]

    Si no se pasan cédulas, usa una lista de cédulas de prueba ficticias.
"""

from __future__ import annotations

import statistics
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


def buscar_cedula_individual(cedula: str) -> tuple[float, str | None]:
    """
    Replica el patrón exacto del notebook actual:
    abre conexión, hace bind, busca, cierra.
    Retorna (duracion_segundos, sAMAccountName_encontrado).
    """
    from ldap3 import SIMPLE, Connection, Server

    server_address = env("LDAP_SERVER")
    base_dn = env("LDAP_BASE_DN")
    user = env("LDAP_USER")
    password = env("LDAP_PASSWORD")

    username_encontrado: str | None = None

    with Cronometro() as t:
        server = Server(server_address)
        with Connection(
            server, user=user, password=password, authentication=SIMPLE, raise_exceptions=False
        ) as conn:
            conn.bind()
            search_filter = f"(&(objectClass=user)(employeeID={cedula}))"
            conn.search(
                search_base=base_dn,
                search_filter=search_filter,
                search_scope="SUBTREE",
                attributes=["sAMAccountName"],
            )
            for entry in conn.entries:
                username_encontrado = (
                    entry.sAMAccountName.value if "sAMAccountName" in entry else None
                )

    return t.duracion, username_encontrado


def main() -> None:
    header("Costo unitario de una búsqueda LDAP", "04")

    print("  Replica el patrón del notebook: una conexión nueva por búsqueda.")
    print("  Mide tiempo promedio, mínimo, máximo de 5 búsquedas individuales.")
    print()

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 04 — Costo unitario de búsqueda LDAP\n\n")

    # Cédulas a probar — desde args o lista de prueba
    if len(sys.argv) > 1:
        cedulas = sys.argv[1:]
        seccion(f"Buscando {len(cedulas)} cédulas pasadas como argumentos")
    else:
        # Lista ficticia: probablemente no existirán, pero el tiempo se mide igual
        cedulas = ["12345678", "87654321", "11111111", "22222222", "33333333"]
        seccion(f"Buscando {len(cedulas)} cédulas de prueba (ficticias)")
        print("  Para usar cédulas reales: python diagnostics/04_ldap_unitario.py 12345 67890 ...")
        print()

    duraciones: list[float] = []
    encontrados = 0
    no_encontrados = 0

    try:
        for i, cedula in enumerate(cedulas, 1):
            try:
                duracion, username = buscar_cedula_individual(cedula)
                duraciones.append(duracion)
                if username:
                    encontrados += 1
                    metrica(f"  Búsqueda {i}/{len(cedulas)} (ced={cedula})", f"{formato_tiempo(duracion)} → {username}")
                else:
                    no_encontrados += 1
                    metrica(f"  Búsqueda {i}/{len(cedulas)} (ced={cedula})", f"{formato_tiempo(duracion)} → no encontrado")
            except Exception as e:
                warn(f"  Búsqueda {i} falló: {e}")
    except Exception as e:
        warn(f"Error general: {e}")
        sys.exit(1)

    # --- Estadísticas ---
    seccion("Estadísticas")
    if duraciones:
        promedio = statistics.mean(duraciones)
        minimo = min(duraciones)
        maximo = max(duraciones)
        desv = statistics.stdev(duraciones) if len(duraciones) > 1 else 0

        metrica("Búsquedas exitosas", f"{len(duraciones)}/{len(cedulas)}")
        metrica("  → Encontradas en AD", encontrados)
        metrica("  → No encontradas (cédula inexistente)", no_encontrados)
        print()
        metrica("Tiempo promedio por búsqueda", formato_tiempo(promedio))
        metrica("Tiempo mínimo", formato_tiempo(minimo))
        metrica("Tiempo máximo", formato_tiempo(maximo))
        metrica("Desviación estándar", formato_tiempo(desv))

        # Proyecciones
        seccion("Proyección a escala real")
        for n in [50, 100, 300, 500, 1000]:
            proyeccion = promedio * n
            metrica(f"Tiempo estimado para {n} cédulas (modo actual)", formato_tiempo(proyeccion))

        # Construir markdown
        buffer_md.write("## Estadísticas\n\n")
        buffer_md.write(f"- Búsquedas: {len(duraciones)}\n")
        buffer_md.write(f"- Promedio: {formato_tiempo(promedio)}\n")
        buffer_md.write(f"- Mínimo: {formato_tiempo(minimo)}\n")
        buffer_md.write(f"- Máximo: {formato_tiempo(maximo)}\n")
        buffer_md.write(f"- Desv. estándar: {formato_tiempo(desv)}\n\n")
        buffer_md.write("## Proyección\n\n")
        buffer_md.write("| N° cédulas | Tiempo estimado |\n|---|---|\n")
        for n in [50, 100, 300, 500, 1000]:
            buffer_md.write(f"| {n} | {formato_tiempo(promedio * n)} |\n")

        # Veredicto
        if promedio > 0.5:
            veredicto = (
                f"Cada búsqueda cuesta ~{formato_tiempo(promedio)}.\n"
                f"Es CARO. Una corrida con 300 cédulas son ~{formato_tiempo(promedio * 300)}.\n"
                f"Migrar a conexión persistente + búsqueda batch es PRIORIDAD ALTA.\n"
            )
        elif promedio > 0.1:
            veredicto = (
                f"Cada búsqueda cuesta ~{formato_tiempo(promedio)}.\n"
                f"Es un costo MODERADO pero significativo a escala.\n"
                f"La optimización a conexión persistente sigue valiendo la pena.\n"
            )
        else:
            veredicto = (
                f"Cada búsqueda cuesta ~{formato_tiempo(promedio)}.\n"
                f"Es BARATO en términos absolutos. La ganancia de optimizar LDAP\n"
                f"existe pero es menor que esperado. Otros cuellos serán dominantes.\n"
            )

        conclusion(
            f"{veredicto}\n"
            f"Próximo paso: ejecutar 05_ldap_batch.py para comparar empíricamente\n"
            f"el patrón actual vs conexión persistente con las mismas cédulas."
        )
    else:
        warn("No se pudo medir ninguna búsqueda. Revisar credenciales LDAP.")

    guardar_resultado("04_ldap_unitario", buffer_md.getvalue())


if __name__ == "__main__":
    main()