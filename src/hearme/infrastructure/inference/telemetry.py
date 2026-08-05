"""Telemetría en tiempo real: TTFT, tokens/s, RTF, CPU, RAM y VRAM.

Sin dependencias obligatorias: `psutil` mejora la lectura de CPU/RAM pero no es
necesario, y la VRAM se lee de `nvidia-smi` si está.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from statistics import mean, median

from hearme.domain.inference import Measurement, WorkloadClass

logger = logging.getLogger(__name__)


def _read_vram_mb() -> float:
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return float(out.stdout.strip().splitlines()[0]) if out.returncode == 0 else 0.0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0.0


def _read_process_stats() -> tuple[float, float]:
    """(cpu_percent, ram_mb) del proceso actual."""
    try:
        import psutil

        process = psutil.Process(os.getpid())
        return process.cpu_percent(interval=None), process.memory_info().rss / 1e6
    except ImportError:
        pass
    # Respaldo sin psutil: RSS desde /proc en Linux.
    try:
        with open(f"/proc/{os.getpid()}/statm") as handle:
            pages = int(handle.read().split()[1])
        return 0.0, pages * os.sysconf("SC_PAGE_SIZE") / 1e6
    except (OSError, ValueError, IndexError):
        return 0.0, 0.0


class Probe:
    """Acumula señales durante una petición y produce una `Measurement`."""

    __slots__ = ("_audio_s", "_first_token", "_start", "_tokens", "backend", "workload")

    def __init__(self, backend: str, workload: WorkloadClass) -> None:
        self.backend = backend
        self.workload = workload
        self._start = time.perf_counter()
        self._first_token: float | None = None
        self._tokens = 0
        self._audio_s = 0.0

    def mark_first_token(self) -> None:
        """Marca el TTFT. Idempotente: solo cuenta la primera llamada."""
        if self._first_token is None:
            self._first_token = time.perf_counter()

    def add_tokens(self, count: int = 1) -> None:
        if self._first_token is None:
            self.mark_first_token()
        self._tokens += count

    def add_audio(self, seconds: float) -> None:
        if self._first_token is None:
            self.mark_first_token()
        self._audio_s += seconds

    def finish(
        self,
        *,
        quality_estimate: float = 0.0,
        techniques: tuple[str, ...] = (),
        ok: bool = True,
        error: str = "",
    ) -> Measurement:
        now = time.perf_counter()
        total = (now - self._start) * 1000
        ttft = ((self._first_token or now) - self._start) * 1000

        # Los tokens/s se cuentan desde el primer token: incluir el TTFT en el
        # divisor mezcla dos métricas distintas y hace el número incomparable.
        generation_s = max(now - (self._first_token or now), 1e-9)
        cpu, ram = _read_process_stats()

        return Measurement(
            backend=self.backend,
            workload=self.workload,
            ttft_ms=round(ttft, 2),
            tokens_per_second=round(self._tokens / generation_s, 2) if self._tokens else 0.0,
            rtf=round((total / 1000) / self._audio_s, 4) if self._audio_s else 0.0,
            total_ms=round(total, 2),
            cpu_percent=round(cpu, 1),
            ram_mb=round(ram, 1),
            vram_mb=round(_read_vram_mb(), 1),
            quality_estimate=quality_estimate,
            techniques=techniques,
            ok=ok,
            error=error,
        )


@contextmanager
def measure(backend: str, workload: WorkloadClass) -> Iterator[Probe]:
    yield Probe(backend, workload)


@dataclass(slots=True)
class Stats:
    count: int
    ttft_p50: float
    ttft_p95: float
    tokens_per_second: float
    rtf: float
    failures: int


@dataclass(slots=True)
class TelemetryStore:
    """Ventana deslizante de mediciones por backend.

    Deliberadamente acotada: el objetivo es alimentar al tuner, no ser una base
    de datos de series temporales.
    """

    window: int = 200
    _by_backend: dict[str, deque[Measurement]] = field(default_factory=dict)

    def record(self, measurement: Measurement) -> None:
        bucket = self._by_backend.setdefault(measurement.backend, deque(maxlen=self.window))
        bucket.append(measurement)

    def stats(self, backend: str) -> Stats | None:
        samples = [m for m in self._by_backend.get(backend, ()) if m.ok]
        if not samples:
            return None

        ttfts = sorted(m.ttft_ms for m in samples)
        rates = [m.tokens_per_second for m in samples if m.tokens_per_second]
        rtfs = [m.rtf for m in samples if m.rtf]
        index95 = min(len(ttfts) - 1, int(len(ttfts) * 0.95))

        return Stats(
            count=len(samples),
            ttft_p50=round(median(ttfts), 2),
            ttft_p95=round(ttfts[index95], 2),
            tokens_per_second=round(mean(rates), 2) if rates else 0.0,
            rtf=round(mean(rtfs), 4) if rtfs else 0.0,
            failures=sum(1 for m in self._by_backend.get(backend, ()) if not m.ok),
        )

    def snapshot(self) -> dict[str, Stats]:
        return {
            backend: stats
            for backend in self._by_backend
            if (stats := self.stats(backend)) is not None
        }


#: Almacén por defecto de la aplicación.
telemetry = TelemetryStore()
