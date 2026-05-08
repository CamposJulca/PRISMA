# Diagnóstico 06 — iterrows vs vectorizado

## Configuración

- N: 5,000, M: 1,000

## Tiempos

| Estrategia | Tiempo |
|---|---|
| A — iterrows() anidado | 50.67 s |
| B — .map() con dict | 6.5 ms |
| C — pd.merge | 5.1 ms |

**Speedup A→B:** 7848.8x
**Speedup A→C:** 9860.5x
