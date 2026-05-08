# Diagnóstico 06 — iterrows vs vectorizado

## Configuración

- N: 5,000, M: 1,000

## Tiempos

| Estrategia | Tiempo |
|---|---|
| A — iterrows() anidado | 51.89 s |
| B — .map() con dict | 6.4 ms |
| C — pd.merge | 4.9 ms |

**Speedup A→B:** 8169.6x
**Speedup A→C:** 10502.3x
