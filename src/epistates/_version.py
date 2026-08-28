"""Fuente única de la versión del paquete.

El valor de ``__version__`` es la única fuente práctica de la versión del
paquete Epistates. Tanto el atributo público ``epistates.__version__`` como los
metadatos de la distribución (campo ``Version`` del wheel) se derivan de este
módulo, por lo que runtime y metadata no pueden divergir silenciosamente:

- runtime: ``from epistates._version import __version__`` (ver ``__init__``);
- build: ``[tool.setuptools.dynamic] version = {attr = ...}`` en
  ``pyproject.toml`` lee este mismo atributo por AST, sin ejecutar el paquete.

La versión PEP 440 del paquete (``0.1.0a1``) es distinta del tag humano
(``v0.1.0-alpha.1``): el primero es el identificador de distribución Python, el
segundo es la etiqueta Git publicada para la prerelease de GitHub. Ambas cadenas
identifican el mismo corte, pero no son intercambiables literalmente.
"""

__version__ = "0.1.0a1"
