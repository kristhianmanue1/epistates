"""API publica para las capabilities canonicas de adaptadores.

Este modulo es la **unica fuente normativa** de los IDs de capabilities de
``epistates/adapter-capabilities/v1``. Tanto el validador ``adapter`` como el
documento de descubrimiento la reutilizan: evita duplicacion manual y derivas
entre el validador y el catalogo publicado.

Describir una capability **no** concluye disponibilidad, observacion ni
autorizacion: los descriptors son metadata estatica sobre la superficie que una
capability implica, no una afirmacion de que este implementada, disponible en un
host concreto o autorizada para una tarea. La fuente interna es inmutable y el
acceso publico devuelve descriptores frescos.
"""

from typing import Any, Dict, List


# Fuente privada e inmutable. Los consumidores reciben diccionarios nuevos
# mediante ``capability_descriptors``; no pueden alterar este catalogo.
_CAPABILITY_ROWS = (
    (
        "dispatch_literal",
        (
            "LiteralDispatcher.send_literal_text, LiteralDispatcher.send_enter "
            "(tmux send-keys)"
        ),
        "terminal_write",
        True,
        True,
        "not_safe_indeterminate_or_partial",
        (
            "Entrega literal de texto al ejecutor via terminal. Transporte "
            "tecnico: no implica comprension. Requiere autoridad externa; un "
            "resultado indeterminado o parcial NO es seguro para reintento. "
            "La membresia declarada por el adaptador no se aplica como gate "
            "runtime en este corte; el control-plane debe comprobarla."
        ),
    ),
    (
        "observe_session",
        (
            "HostRunner.git_toplevel/git_head/git_branch/git_status, "
            "HostRunner.tmux_list_panes"
        ),
        "host_observation",
        True,
        False,
        "not_safe_single_shot",
        (
            "Observacion read-only del host (git + sesion tmux). Requiere "
            "autoridad externa por contacto con el host aunque sea read-only. "
            "La membresia declarada no es un gate runtime de la libreria."
        ),
    ),
    (
        "capture_once",
        "ReviewRunner.capture_once (tmux capture-pane)",
        "host_observation",
        True,
        False,
        "not_safe_single_shot",
        (
            "Captura unica acotada del scrollback. Read-only; el contenido no "
            "sale del runner. Requiere autoridad externa por contacto con host. "
            "La membresia declarada no es un gate runtime de la libreria."
        ),
    ),
)


CAPABILITY_IDS = frozenset(row[0] for row in _CAPABILITY_ROWS)


def capability_descriptors() -> List[Dict[str, Any]]:
    """Devuelve descriptors frescos; describir no concede ni aplica autoridad."""
    return [
        {
            "id": capability_id,
            "surface": surface,
            "effect_class": effect_class,
            "requires_external_authority": requires_authority,
            "may_mutate_host": may_mutate,
            "retry_safety": retry_safety,
            "runtime_enforced": False,
            "enforcement_owner": "external_control_plane",
            "library_authenticates_authority": False,
            "description": description,
        }
        for (
            capability_id, surface, effect_class, requires_authority,
            may_mutate, retry_safety, description,
        ) in _CAPABILITY_ROWS
    ]
