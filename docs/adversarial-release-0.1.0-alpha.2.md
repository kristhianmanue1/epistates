# Ronda adversarial — candidata 0.1.0-alpha.2

Fecha: 2026-08-28

Tarjeta: `release-alpha2-preparation`

Artefacto revisado: `epistates-0.1.0a2-py3-none-any.whl`, construido desde
`0858c6c5abbd7070cb9863cfd3e77e31a77c54ad`.

Estado inicial: **PENDIENTE DEL GATE FINAL**.

## Ataques obligatorios

- version skew entre runtime, metadata, nombre del wheel, README y changelog;
- gate alpha.1 reutilizado como si certificara el `HEAD` actual;
- inventario obsoleto de módulos o package-data;
- wheel único presentado como reproducible;
- import accidental desde checkout/PYTHONPATH durante smoke;
- diferencias Python 3.9/3.12 no evidenciadas o Linux presentado como verificado
  pese a que la cuota impidió iniciar los jobs GitHub;
- documentación empaquetada obsoleta o digest inconsistente;
- E4 interno presentado como wake activo;
- tag/release/PyPI inferidos de tests verdes;
- secretos, credenciales o artefactos de build añadidos al repositorio.

## Veredicto

### Resultados de ataque

- **Version skew:** refutado. Runtime, metadata y nombre del wheel coinciden en
  `0.1.0a2`; README y changelog lo presentan como no publicado.
- **Evidencia histórica reutilizada:** refutado. Alpha.2 tiene gate, SHA, epoch,
  builds y smoke propios; alpha.1 sólo queda como referencia histórica.
- **Falsa reproducibilidad:** refutada. Dos exportaciones independientes y dos
  builds con el mismo epoch dieron el mismo tamaño y SHA-256; `cmp` fue `0`.
- **Import desde checkout:** refutado. Ambos smoke usaron venvs nuevos, cwd fuera
  del repositorio y `PYTHONPATH` eliminado.
- **Inventario/package-data:** refutado. El wheel contiene 29 módulos, 7 schemas
  y 2 archivos de onboarding; el runtime declara 45 símbolos, 7 schemas y 3
  entradas de onboarding. El digest de la guía coincide.
- **Contaminación:** refutada. No hay rutas de tests/docs/fixtures/repo ni
  patrones obvios de secretos dentro del wheel.
- **E4 presentado como activo:** refutado. README/gate declaran que es interno e
  inactivo; no hay daemon, wiring automático ni wake habilitado.
- **Plataformas sobrerreportadas:** hallazgo corregido antes del build. El gate
  ahora registra macOS arm64 y Linux arm64 sobre Python 3.9/3.12 por separado.
  No infiere x86_64. El workflow conserva la matriz sólo para ejecución manual.
- **Suite no colectable en Linux:** hallazgo corregido. El mock de kqueue ahora
  crea explícitamente los símbolos Darwin ausentes en `select` de Linux; la
  corrección está limitada a tests y la matriz completa volvió a verde.
- **GitHub rojo interpretado como fallo:** refutado. El run `33225053925` no
  ejecutó steps por límite de uso/facturación; no es evidencia del código.
- **Release inferido:** refutado. No existe autorización en esta tarjeta para
  tag, GitHub Release ni PyPI y ninguna de esas operaciones se ejecutó.

### Riesgos residuales

- macOS/Linux se verificaron sólo sobre arm64; x86_64 no tiene evidencia fresca.
- La reproducibilidad está demostrada con el toolchain local actual, no entre
  toolchains o sistemas operativos distintos.
- E4 sigue siendo superficie interna experimental; superar el gate de paquete
  no autoriza conectarlo a un runtime ni despertar agentes.

**PROCEED técnico para la candidata local. El mantenedor autorizó publicación,
pero el preflight no encontró credencial PyPI. BLOCKED para tag, GitHub Release
y PyPI hasta disponer de `UV_PUBLISH_TOKEN`, evitando un release parcial. E4
permanece inactivo.**
