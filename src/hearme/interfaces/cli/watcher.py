"""Carpetas vigiladas: automatización por lotes.

Se sondea en vez de usar inotify a propósito — inotify no funciona en montajes de
red ni en volúmenes de Docker en macOS/Windows, que es justo donde la gente deja
su carpeta de libros.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from rich.console import Console

from hearme.application.jobs import JobQueue, WorkerPool
from hearme.application.pipeline import ConversionRequest
from hearme.application.plugins import plugins
from hearme.config import settings
from hearme.infrastructure.persistence.database import dispose, init_db

logger = logging.getLogger(__name__)
console = Console()

#: Un archivo debe mantener su tamaño este tiempo antes de procesarse; evita
#: leer una copia a medias.
STABLE_SECONDS = 3.0


async def run_watcher(directories: list[Path], formats: list[str], interval: float = 5.0) -> None:
    plugins.load()
    settings.ensure_dirs()
    await init_db()

    queue = JobQueue()
    pool = WorkerPool(size=1, queue=queue)
    await pool.start()

    seen: dict[Path, tuple[int, float]] = {}
    enqueued: set[Path] = set()
    valid = [d.resolve() for d in directories if d.is_dir()]
    if not valid:
        console.print("[red]Ninguna de las carpetas indicadas existe.[/]")
        await pool.stop()
        await dispose()
        return

    for directory in valid:
        console.print(f"[cyan]vigilando[/] {directory}")
    console.print("[dim]Ctrl-C para salir[/]\n")

    try:
        while True:
            for directory in valid:
                await _scan(directory, seen, enqueued, queue, formats)
            await asyncio.sleep(interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[dim]deteniendo…[/]")
    finally:
        await pool.stop()
        await dispose()


async def _scan(
    directory: Path,
    seen: dict[Path, tuple[int, float]],
    enqueued: set[Path],
    queue: JobQueue,
    formats: list[str],
) -> None:
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if plugins.parser_for(path.suffix) is None:
            continue
        if path in enqueued:
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue

        now = asyncio.get_event_loop().time()
        previous = seen.get(path)
        if previous is None or previous[0] != size:
            seen[path] = (size, now)
            continue

        stable_since = previous[1]
        if now - stable_since < STABLE_SECONDS:
            continue

        enqueued.add(path)
        del seen[path]
        job_id = await queue.enqueue(ConversionRequest(source=path, formats=formats))
        console.print(f"[green]+[/] encolado {path.name} [dim]({job_id[:8]})[/]")
