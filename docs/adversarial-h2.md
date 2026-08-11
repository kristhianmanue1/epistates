# Ronda adversarial — H2 auditoría y estados

**Fecha:** 2026-08-11. **Decisión final:** `proceed`.

## Alcance

Revisión independiente y read-only del ADR-0001, schema y validador de auditoría,
bindings, máquina de estados, CLI, fixtures y pruebas.

## Hallazgos corregidos

- bypass a `DONE` omitiendo un check declarado por la tarjeta;
- `run_id` y `attempt_id` autodeclarados sin contraste externo;
- incompatibilidad del formato `grant_id` entre H1 y H2;
- derivador público de estado que evitaba comprobar el estado actual;
- tracebacks ante UTF-8 inválido, surrogates y tipos hostiles;
- claves JSON duplicadas aceptadas silenciosamente;
- divergencia no documentada entre forma JSON Schema y semántica del CLI.

## Evidencia final

- `python -m unittest discover -s tests -p 'test_*.py'` → 37 tests, `OK`.
- auditoría + tarjeta + run + attempt exactos → `VALID`.
- auditoría sin bindings o con run incorrecto → `INVALID`.
- omitir evidencia de un check declarado impide `DONE`.
- `REVIEWING + block`, transición desconocida y eventos tras estados terminales
  fallan cerrados.

## Riesgo residual aceptado

JSON Schema expresa la forma portable, pero no puede imponer unicidad por
`evidence_id` cuando cambia el resto del objeto. El CLI es normativo para esa
restricción semántica y rechaza IDs duplicados.
