"""Event bus asíncrono en proceso.

El transporte es un detalle: hoy es una lista de callbacks, mañana puede ser Redis
Streams. Los emisores solo conocen `publish()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

from hearme.domain.events import Event

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)
        # Colas por job para el streaming SSE hacia la UI.
        self._streams: dict[str, set[asyncio.Queue[Event | None]]] = defaultdict(set)

    def subscribe(self, event_type: type[E], handler: Handler) -> Callable[[], None]:
        """Registra un handler. Devuelve la función para darse de baja."""
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._handlers[event_type].remove(handler)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        # Un handler que falla no puede tumbar el pipeline ni a sus pares.
        for etype, handlers in self._handlers.items():
            if not isinstance(event, etype):
                continue
            for handler in handlers:
                try:
                    await handler(event)
                except Exception:
                    logger.exception("handler de evento falló: %s", type(event).__name__)

        for queue in tuple(self._streams.get(event.job_id, ())):
            queue.put_nowait(event)

    async def stream(self, job_id: str) -> AsyncIterator[Event]:
        """Consume los eventos de un job. Alimenta el endpoint SSE."""
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._streams[job_id].add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            self._streams[job_id].discard(queue)
            if not self._streams[job_id]:
                self._streams.pop(job_id, None)

    def close_stream(self, job_id: str) -> None:
        """Señala fin de emisión a los consumidores SSE de un job."""
        for queue in tuple(self._streams.get(job_id, ())):
            queue.put_nowait(None)


#: Bus por defecto de la aplicación. Inyectable/sustituible en tests.
bus = EventBus()
