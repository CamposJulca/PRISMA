# Diagnóstico 06 — iterrows vs vectorizado

## Configuración

- N: 5,000, M: 1,000

## Tiempos

| Estrategia | Tiempo |
|---|---|
| A — iterrows() anidado | 50.91 s |
| B — .map() con dict | 6.5 ms |
| C — pd.merge | 5.0 ms |

**Speedup A→B:** 7802.3x
**Speedup A→C:** 10114.9x
