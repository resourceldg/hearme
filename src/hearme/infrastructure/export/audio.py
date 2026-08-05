"""Exportadores de audio: MP3 y M4B con índice de capítulos.

Se apoya en ffmpeg por CLI en vez de en un binding de Python: es la dependencia
que ya está en cualquier sistema, evita compilar y no impone licencia al proyecto.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

from hearme.domain.models import AudioSegment, ChapterMark, Document

logger = logging.getLogger(__name__)


class FFmpegMissing(RuntimeError):
    pass


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise FFmpegMissing("ffmpeg no está instalado. En Debian/Ubuntu: sudo apt install ffmpeg")
    return path


async def _run(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló ({process.returncode}): {stderr.decode(errors='replace')[-800:]}"
        )


def _escape_concat(path: Path) -> str:
    """Escapa una ruta para la sintaxis del demuxer `concat` de ffmpeg.

    Las comillas simples se cierran, se escapan y se reabren: `'` -> `'\\''`.
    """
    return path.resolve().as_posix().replace("\n", "").replace("'", "'\\''")


def _concat_file(segments: Sequence[AudioSegment], work_dir: Path) -> Path:
    """Lista para el demuxer `concat`. Evita una línea de comando de 10 000 archivos."""
    listing = work_dir / "concat.txt"
    lines = [
        # Las comillas simples deben escaparse según la sintaxis del demuxer.
        f"file '{_escape_concat(segment.path)}'"
        for segment in sorted(segments, key=lambda s: s.order)
    ]
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


def _ffmetadata(document: Document, marks: Sequence[ChapterMark]) -> str:
    """Fichero FFMETADATA1 con los capítulos, en milisegundos."""
    lines = [";FFMETADATA1", f"title={_escape(document.meta.title)}"]
    if document.meta.authors:
        lines.append(f"artist={_escape(', '.join(document.meta.authors))}")
        lines.append(f"album_artist={_escape(document.meta.authors[0])}")
    lines.append(f"album={_escape(document.meta.title)}")
    lines.append("genre=Audiobook")

    for mark in marks:
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(mark.start_s * 1000)}",
            f"END={int(mark.end_s * 1000)}",
            f"title={_escape(mark.title)}",
        ]
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    for char in ("=", ";", "#", "\\", "\n"):
        value = value.replace(char, "\\" + char)
    return value


class _AudioExporterBase:
    needs_audio = True
    name: str
    codec: str = "libmp3lame"
    bitrate: str = "64k"

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path:
        if not segments:
            raise ValueError(f"El exportador '{self.name}' requiere audio sintetizado")

        ffmpeg = _require_ffmpeg()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = out_path.parent / f".{out_path.stem}.work"
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            listing = _concat_file(segments, work_dir)
            args = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
            ]

            metadata_path: Path | None = None
            if marks:
                metadata_path = work_dir / "chapters.txt"
                metadata_path.write_text(_ffmetadata(document, marks), encoding="utf-8")
                args += ["-i", str(metadata_path), "-map_metadata", "1"]

            args += [
                "-map",
                "0:a",
                "-c:a",
                self.codec,
                "-b:a",
                self.bitrate,
                # Mono a 22.05 kHz: la voz no gana nada por encima y el archivo
                # de un libro entero baja de gigabytes a decenas de megas.
                "-ac",
                "1",
                "-ar",
                "22050",
                *self.extra_args(),
                str(out_path),
            ]
            await _run(args)
            return out_path
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def extra_args(self) -> list[str]:
        return []


class MP3Exporter(_AudioExporterBase):
    name = "mp3"
    extension = ".mp3"
    codec = "libmp3lame"
    bitrate = "64k"


class M4BExporter(_AudioExporterBase):
    """M4B: contenedor MP4 con AAC e índice de capítulos — el estándar de audiolibro."""

    name = "m4b"
    extension = ".m4b"
    codec = "aac"
    bitrate = "64k"

    def extra_args(self) -> list[str]:
        # `mov_text`/faststart hacen que los reproductores lean el índice sin
        # descargar el archivo entero.
        return ["-movflags", "+faststart", "-f", "mp4"]


def build_chapter_marks(
    document: Document, segments: Sequence[AudioSegment], utterance_chapters: dict[str, str]
) -> list[ChapterMark]:
    """Convierte duraciones acumuladas en marcas de capítulo.

    `utterance_chapters` mapea utterance_id -> chapter_id.
    """
    titles = {chapter.id: chapter.title for chapter in document.chapters}
    marks: list[ChapterMark] = []
    elapsed = 0.0
    current_id: str | None = None
    start = 0.0

    for segment in sorted(segments, key=lambda s: s.order):
        chapter_id = utterance_chapters.get(segment.utterance_id)
        if chapter_id != current_id:
            if current_id is not None:
                marks.append(
                    ChapterMark(
                        title=titles.get(current_id, f"Capítulo {len(marks) + 1}"),
                        start_s=start,
                        end_s=elapsed,
                    )
                )
            current_id = chapter_id
            start = elapsed
        elapsed += segment.duration_s

    if current_id is not None:
        marks.append(
            ChapterMark(
                title=titles.get(current_id, f"Capítulo {len(marks) + 1}"),
                start_s=start,
                end_s=elapsed,
            )
        )
    return marks
