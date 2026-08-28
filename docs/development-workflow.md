# Preparación y cierre de trabajo de ingeniería

Esta guía organiza documentación y evidencia de una tarea; no amplía el
contrato ni la autoridad de Epistates. La tarjeta canónica es siempre
`epistates/task-card/v1`.

## Clasificación observable

Una tarea es **Bounded** sólo si cumple todas estas condiciones: cambia rutas
existentes, no añade dependencias, no crea ni modifica una interfaz pública,
schema o contrato, y no coordina varias tareas mediante un plan. Es
**Architectural** si cualquiera falla, si crea o extiende un plan, o si afecta
runtime, frontera de confianza, persistencia, concurrencia o consumidores no
controlados. Ante evidencia nueva, la clase sólo puede elevarse.

## Contrato de tarea

La preparación usa exclusivamente los campos de `task-card/v1`:

| Necesidad de la tarea | Campo canónico |
|---|---|
| Resultado único | `objective` |
| Repositorio, revisión y worktree | `target` |
| Perfil de trabajo | `role` |
| Alcance y efectos permitidos | `allowed_paths`, `allowed_actions` |
| Operaciones que no se harán | `forbidden_operations` |
| Grant correlacionado y nueva decisión | `authority`, `new_decision_required_for` |
| Entradas, checks y evidencia requerida | `inputs`, `checks`, `evidence` |
| Entrega y parada | `delivery`, `stop_condition` |

No se añade una “tarjeta operativa” paralela. Si hace falta expresar una
propiedad que no cabe en estos campos, se detiene la tarea y se propone una ADR
y una nueva versión de contrato.

## Planes de escala

Cuando hay varias tareas, crea un documento en [`plans/`](plans/) con una
referencia al artefacto que habilita el trabajo. Cada tarea declara qué consume,
qué produce, pasos verificables, DoD y condición de parada. El plan es dueño de
los pasos y DoD; la tarjeta de cada ejecución lo declara como entrada en
`inputs`, sin introducir un campo de schema nuevo.

## Evidencia y cierre

Cada línea de evidencia declara un resultado:

```text
- <comando o fuente> -> <resultado observado> [pass | fail | inconclusive]
```

- `pass`: la comprobación ocurrió y cumplió.
- `fail`: la comprobación ocurrió y no cumplió.
- `inconclusive`: no se pudo comprobar por una causa exógena, indicando qué
  evidencia faltaría. Nunca equivale a verde ni permite cerrar un gate.

El estado global sigue siendo `OK`, `PARCIAL` o `BLOQ`: describe el trabajo, no
el resultado individual de un comando. Antes de cerrar, revisa el diff, los
checks declarados y los riesgos residuales; los hitos reciben una ronda
adversarial fresca.
