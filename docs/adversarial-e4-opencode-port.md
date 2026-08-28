# Ronda adversarial — puerto OpenCode E4

**Decisión:** `proceed-for-simulated-port-only`.

- URL remota, HTTPS externo o path adicional: rechazados.
- Health inválido, agente ausente o error de transporte: `unsupported`, sin POST.
- Session ID inválido: `rejected`, sin POST.
- Sólo se permite `prompt_async` con mensaje fijo; no hay shell, TUI, config ni MCP.
- El modelo GLM es configuración de OpenCode; no se lee ni persiste credencial Z.ai.

No se audita un servidor real ni el vínculo transaccional con guard/recibo. Por ello no se autoriza tráfico, wake real ni activación automática.
