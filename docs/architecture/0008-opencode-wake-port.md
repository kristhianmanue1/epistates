# ADR-0008 — Puerto de wake OpenCode con modelo Z.ai/GLM

**Estado:** aceptado para adaptador simulado; activación bloqueada. **Fecha:** 2026-08-28. **Depende de:** ADR-0007.

Epistates selecciona el API HTTP público local de OpenCode, no el API de Z.ai. OpenCode conserva su propia configuración y credenciales para `zai/glm-*`; Epistates sólo declara `providerID=zai` y el modelo requerido al solicitar el prompt permitido.

El adaptador acepta únicamente loopback HTTP y permite `GET /global/health`, `GET /agent` y `POST /session/:id/prompt_async`. Rechaza TUI, shell, config, MCP, endpoints remotos y modelos no GLM. El mensaje es fijo y pide sólo estado read-only. Ninguna prueba inicia servidor ni envía HTTP real.

Una activación posterior requerirá un servidor OpenCode configurado con el agente `epistates-inspect`, autenticación, validación del OpenAPI/versión y unión atómica con `WakeGuardStore` y el recibo E3.
