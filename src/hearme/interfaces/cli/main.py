"""CLI de HearMe."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from hearme import __version__
from hearme.application.event_bus import bus
from hearme.application.pipeline import ConversionPipeline, ConversionRequest
from hearme.application.plugins import plugins
from hearme.config import settings
from hearme.domain.events import Event, JobProgress
from hearme.domain.models import NarrationStyle, ReadingMode
from hearme.infrastructure.hardware import detect

app = typer.Typer(
    name="hearme",
    help="HearMe — plataforma abierta de narración en voz alta de alta calidad",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def info() -> None:
    """Muestra la capacidad del nodo, los plugins cargados y avisos de instalación."""
    plugins.load()
    profile = detect()

    console.print(f"[bold cyan]HearMe[/] {__version__}")
    console.print(f"[dim]{profile.describe()}[/]\n")

    table = Table(title="Motores TTS", show_lines=False)
    table.add_column("Motor", style="bold")
    table.add_column("Estado")
    table.add_column("Naturalidad", justify="right")
    table.add_column("RTF", justify="right")
    table.add_column("Idiomas")

    async def collect() -> list[tuple[str, str, str, str, str]]:
        rows = []
        for engine in plugins.tts:
            ok = await engine.is_available()
            rows.append(
                (
                    engine.name,
                    "[green]listo[/]" if ok else "[yellow]no instalado[/]",
                    f"{engine.naturalness:.2f}",
                    f"{engine.rtf:.3f}",
                    ", ".join(sorted(engine.languages)[:8])
                    + ("…" if len(engine.languages) > 8 else ""),
                )
            )
        return rows

    for row in asyncio.run(collect()):
        table.add_row(*row)
    console.print(table)

    console.print(f"\n[bold]Parsers:[/] {', '.join(plugins.parsers.names())}")
    console.print(f"[bold]Exportadores:[/] {', '.join(plugins.exporters.names())}")
    console.print(f"[bold]Traductores:[/] {', '.join(plugins.translators.names()) or '—'}")
    console.print(f"[bold]OCR:[/] {', '.join(plugins.ocr.names()) or '—'}")
    console.print(f"[bold]Datos:[/] {settings.data_dir}")


@app.command()
def convert(
    source: Annotated[Path, typer.Argument(help="Archivo a convertir")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Directorio de salida")] = None,
    formats: Annotated[
        list[str] | None, typer.Option("--format", "-f", help="Repetible: m4b, mp3, md, json…")
    ] = None,
    mode: Annotated[ReadingMode, typer.Option("--mode", "-m")] = ReadingMode.AUDIOBOOK,
    language: Annotated[str | None, typer.Option("--lang", "-l", help="Auto si se omite")] = None,
    to: Annotated[str | None, typer.Option("--to", help="Traducir a este idioma")] = None,
    engine: Annotated[str | None, typer.Option("--engine", "-e", help="auto|kokoro|piper")] = None,
    voice: Annotated[str | None, typer.Option("--voice")] = None,
    style: Annotated[NarrationStyle, typer.Option("--style", "-s")] = NarrationStyle.NEUTRAL,
    quality: Annotated[str, typer.Option("--quality", "-q", help="high|draft")] = "high",
    ocr: Annotated[bool | None, typer.Option("--ocr/--no-ocr", help="Auto si se omite")] = None,
    keep_wavs: Annotated[bool, typer.Option("--keep-wavs")] = False,
) -> None:
    """Convierte un documento a audiolibro y/o a formatos de texto."""
    if not source.exists():
        console.print(f"[red]No existe:[/] {source}")
        raise typer.Exit(1)

    request = ConversionRequest(
        source=source.resolve(),
        mode=mode,
        formats=list(formats) if formats else ["m4b"],
        language=language,
        target_language=to,
        engine=engine,
        voice=voice,
        style=style,
        quality=quality,
        out_dir=out.resolve() if out else None,
        ocr=ocr,
        keep_wavs=keep_wavs,
    )
    asyncio.run(_convert(request))


async def _convert(request: ConversionRequest) -> None:
    pipeline = ConversionPipeline()
    job_id = "cli"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("preparando…", total=None)

        async def on_progress(event: Event) -> None:
            if not isinstance(event, JobProgress):
                return
            label = {
                "ocr": "OCR",
                "parseo": "analizando documento",
                "traduccion": "traduciendo",
                "sintesis": "sintetizando voz",
            }.get(event.stage, event.stage)
            detail = f" · {event.detail}" if event.detail else ""
            progress.update(
                task,
                description=f"{label}{detail}",
                total=event.total or None,
                completed=event.current,
            )

        unsubscribe = bus.subscribe(JobProgress, on_progress)
        try:
            result = await pipeline.run(request, job_id=job_id)
        except Exception as exc:
            progress.stop()
            console.print(f"[red]Error:[/] {exc}")
            raise typer.Exit(1) from exc
        finally:
            unsubscribe()

    console.print(f"\n[green]✓[/] [bold]{result.document.meta.title}[/]")
    console.print(
        f"  {len(result.document.chapters)} capítulos · "
        f"{result.document.char_count:,} caracteres · idioma [cyan]{result.language}[/]"
    )
    if result.engine:
        console.print(
            f"  motor [cyan]{result.engine}[/]/{result.voice} — {result.selection_reason}"
        )
        console.print(f"  duración del audio: [cyan]{_hms(result.duration_s)}[/]")
    for path in result.outputs:
        size = path.stat().st_size / 1e6 if path.exists() else 0
        console.print(f"  [dim]→[/] {path}  [dim]({size:.1f} MB)[/]")


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "",
    port: Annotated[int, typer.Option("--port", "-p")] = 0,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Arranca la API REST y el worker."""
    import uvicorn

    uvicorn.run(
        "hearme.interfaces.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def watch(
    directories: Annotated[list[Path], typer.Argument(help="Carpetas a vigilar")],
    formats: Annotated[list[str] | None, typer.Option("--format", "-f")] = None,
    interval: Annotated[float, typer.Option("--interval", help="Segundos entre sondeos")] = 5.0,
) -> None:
    """Vigila carpetas y convierte automáticamente lo que aparezca."""
    from hearme.interfaces.cli.watcher import run_watcher

    asyncio.run(run_watcher(directories, list(formats) if formats else ["m4b"], interval))


@app.command()
def jobs(limit: Annotated[int, typer.Option("--limit", "-n")] = 20) -> None:
    """Lista el historial de trabajos."""

    async def run() -> None:
        from hearme.application.jobs import JobQueue
        from hearme.infrastructure.persistence.database import dispose, init_db

        await init_db()
        rows = await JobQueue().list(limit=limit)
        await dispose()

        if not rows:
            console.print("[dim]Sin trabajos registrados.[/]")
            return

        table = Table(title=f"Últimos {len(rows)} trabajos")
        for column in ("ID", "Estado", "Título", "Progreso", "Motor", "Creado"):
            table.add_column(column)
        colors = {
            "completed": "green",
            "failed": "red",
            "running": "yellow",
            "pending": "cyan",
            "cancelled": "dim",
        }
        for row in rows:
            table.add_row(
                row.id[:8],
                f"[{colors.get(row.status, 'white')}]{row.status}[/]",
                (row.title or "—")[:40],
                f"{row.progress * 100:.0f}%",
                row.engine or "—",
                row.created_at.strftime("%d/%m %H:%M") if row.created_at else "—",
            )
        console.print(table)

    asyncio.run(run())


def _hms(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:d}h {total % 3600 // 60:02d}m {total % 60:02d}s"


if __name__ == "__main__":
    app()
