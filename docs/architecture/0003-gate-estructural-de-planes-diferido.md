# ADR-0003 — Gate estructural de planes diferido

**Estado:** aceptado. **Fecha:** 2026-08-28. **Plan:**
[`EPI-SKEVI-001`](../plans/2026-08-28-adopcion-practicas-skevi.md).

## Contexto

EPI-SKEVI-001 produjo un plan real y evaluó sobre él el gate `check_plans.py`
de Skevi. La evaluación terminó en `BLOQ`, pero los cuatro hallazgos eran falsos
positivos: el gate trató comandos completos entre acentos como si fueran rutas
locales. También informó que una ruta de schema de repositorio no existe cuando
el recurso canónico está empaquetado bajo `src/epistates/data/schemas/`.

El resultado demuestra que copiar el gate no comprobaría con precisión los
planes de Epistates. Un gate estructural tampoco puede probar autoridad,
corrección semántica, aceptación humana ni cumplimiento del contrato de tarea.

## Decisión

No activar ni copiar un gate estructural de planes en este corte. La revisión
manual respaldada por el plan, el verificador de enlaces locales y las pruebas
focales permanece como evidencia documental suficiente.

Una propuesta futura de gate sólo podrá avanzar si parte de una sintaxis local
definida, distingue comandos de rutas, conoce los recursos canónicos
empaquetados y presenta fixtures válidos y adversariales sobre al menos dos
planes reales. Deberá ser opt-in, no ejecutar el proyecto ni leer secretos, y
declarar explícitamente que no concede autoridad.

## Alternativas descartadas

- **Copiar `check_plans.py` de Skevi:** los falsos positivos observados hacen
  que su señal no sea fiable para los planes actuales de Epistates.
- **Modificar el script copiado en este corte:** introduciría código y una
  política nueva antes de contar con evidencia de una segunda forma de plan.
- **No documentar la evaluación:** perdería la razón verificable de diferir el
  gate y permitiría que un futuro cambio reintroduzca la misma suposición.

## Consecuencias

- No se añade dependencia, script ni configuración de gate de planes.
- La decisión puede reconsiderarse sólo mediante una ADR nueva y pruebas
  focales; esta ADR no autoriza una implementación posterior.
- El plan EPI-SKEVI-001 queda cerrado respecto al gate: la mejora adoptada es
  la regla de no instalar un control sin señal local demostrada.
