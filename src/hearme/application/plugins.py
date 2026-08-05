"""Registro de plugins.

Dos vías de alta, mismo registro:
  1. `entry_points` del grupo `hearme.plugins` — instalar un paquete lo activa.
  2. Registro manual — usado por los adaptadores internos y por los tests.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from importlib.metadata import entry_points

from hearme.domain.ports import (
    DocumentParser,
    Exporter,
    LLMProvider,
    OCREngine,
    Translator,
    TTSEngine,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "hearme.plugins"


class Registry[T]:
    """Colección de implementaciones de un puerto, indexadas por nombre."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, T] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self, name: str, impl: T, *, aliases: tuple[str, ...] = (), override: bool = False
    ) -> None:
        if name in self._items and not override:
            raise ValueError(f"{self.kind} '{name}' ya está registrado")
        self._items[name] = impl
        for alias in aliases:
            self._aliases[alias] = name
        logger.debug("registrado %s: %s", self.kind, name)

    def get(self, name: str) -> T:
        key = self._aliases.get(name, name)
        try:
            return self._items[key]
        except KeyError:
            raise LookupError(
                f"{self.kind} '{name}' no encontrado. Disponibles: "
                f"{sorted({*self._items, *self._aliases})}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, name: object) -> bool:
        return name in self._items or name in self._aliases


class PluginManager:
    def __init__(self) -> None:
        self.parsers: Registry[DocumentParser] = Registry("parser")
        self.tts: Registry[TTSEngine] = Registry("tts")
        self.translators: Registry[Translator] = Registry("translator")
        self.ocr: Registry[OCREngine] = Registry("ocr")
        self.exporters: Registry[Exporter] = Registry("exporter")
        self.llm: Registry[LLMProvider] = Registry("llm")
        self._loaded = False

    def load(self) -> None:
        """Descubre y carga plugins. Idempotente."""
        if self._loaded:
            return
        self._loaded = True
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                ep.load()(self)
            except Exception:
                # Un plugin roto degrada su función, no arranca menos la app.
                logger.exception("no se pudo cargar el plugin '%s'", ep.name)

    def parser_for(self, path_suffix: str) -> DocumentParser | None:
        suffix = path_suffix.lower().lstrip(".")
        for parser in self.parsers:
            if any(fmt.value == suffix for fmt in parser.formats):
                return parser
        return None


#: Manager por defecto de la aplicación.
plugins = PluginManager()
