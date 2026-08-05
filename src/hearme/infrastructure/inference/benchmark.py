"""Benchmark inicial: mide la máquina en vez de suponerla.

Se ejecuta una vez y se cachea en disco. Deliberadamente barato (segundos, no
minutos): su objetivo es ordenar candidatos, no publicar cifras.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from hearme.config import settings
from hearme.domain.inference import WorkloadClass
from hearme.infrastructure.hardware import detect
from hearme.infrastructure.inference.backends import PROFILES, detect_available
from hearme.infrastructure.inference.planner import evaluate_backends

logger = logging.getLogger(__name__)

CACHE_VERSION = 1


@dataclass(slots=True)
class BenchmarkResult:
    version: int
    hardware: str
    cpu_cores: int
    vram_mb: int
    #: GFLOPS aproximados en CPU. Ordena máquinas, no compite con LINPACK.
    cpu_score: float
    memory_bandwidth_mb_s: float
    available_backends: dict[str, bool]
    ranking: list[dict[str, object]]
    timestamp: float

    def summary(self) -> str:
        viable = [r for r in self.ranking if r["viable"]]
        best = viable[0]["backend"] if viable else "ninguno"
        return (
            f"{self.hardware} · CPU {self.cpu_score:.1f} GFLOPS · "
            f"memoria {self.memory_bandwidth_mb_s / 1000:.1f} GB/s · mejor motor: {best}"
        )


def _cache_path() -> Path:
    return settings.cache_dir / "benchmark.json"


def _bench_cpu(seconds: float = 0.35) -> float:
    """GFLOPS aproximados con multiplicación de matrices.

    Usa numpy si está (mide BLAS real, que es lo que usarán los modelos); si no,
    cae a Python puro, cuyo número no es comparable pero sí ordena.
    """
    try:
        import numpy as np
    except ImportError:
        start = time.perf_counter()
        total = 0.0
        operations = 0
        while time.perf_counter() - start < seconds:
            total += sum(i * 1.000001 for i in range(1000))
            operations += 2000
        return operations / (time.perf_counter() - start) / 1e9

    size = 512
    a = np.random.rand(size, size).astype(np.float32)
    b = np.random.rand(size, size).astype(np.float32)
    a @ b  # descarta la primera: incluye la inicialización de BLAS

    start = time.perf_counter()
    iterations = 0
    while time.perf_counter() - start < seconds:
        a @ b
        iterations += 1
    elapsed = time.perf_counter() - start

    # Una multiplicación nxn son 2n³ operaciones en coma flotante.
    return (2 * size**3 * iterations) / elapsed / 1e9


def _bench_memory(seconds: float = 0.25) -> float:
    """Ancho de banda de memoria en MB/s."""
    try:
        import numpy as np
    except ImportError:
        return 0.0

    buffer = np.zeros(8 * 1024 * 1024, dtype=np.uint8)  # 8 MB
    start = time.perf_counter()
    copied = 0
    while time.perf_counter() - start < seconds:
        buffer.copy()
        copied += buffer.nbytes
    return copied / (time.perf_counter() - start) / 1e6


def run(*, workload: WorkloadClass = WorkloadClass.LLM_DECODE) -> BenchmarkResult:
    """Ejecuta el benchmark y devuelve el resultado (sin cachear)."""
    hardware = detect()
    available = detect_available()

    logger.info("ejecutando benchmark inicial…")
    cpu_score = _bench_cpu()
    bandwidth = _bench_memory()

    ranking = [
        {
            "backend": candidate.profile.name,
            "score": candidate.score,
            "viable": candidate.viable,
            "license": candidate.profile.license,
            "reason": candidate.reason,
        }
        for candidate in evaluate_backends(workload, hardware=hardware, available=available)
    ]

    return BenchmarkResult(
        version=CACHE_VERSION,
        hardware=hardware.describe(),
        cpu_cores=hardware.cpu_cores,
        vram_mb=hardware.vram_mb,
        cpu_score=round(cpu_score, 2),
        memory_bandwidth_mb_s=round(bandwidth, 1),
        available_backends=available,
        ranking=ranking,
        timestamp=time.time(),
    )


def load_or_run(*, force: bool = False) -> BenchmarkResult:
    """Resultado cacheado, o lo calcula. El hardware no cambia entre arranques."""
    path = _cache_path()

    if not force and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION:
                cached = BenchmarkResult(**data)
                # Si la capacidad del nodo cambió, la medición se rehace.
                if cached.hardware == detect().describe():
                    return cached
        except (OSError, ValueError, TypeError):
            logger.debug("caché de benchmark ilegible; se rehace", exc_info=True)

    result = run()
    try:
        settings.ensure_dirs()
        path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    except OSError:
        logger.warning("no se pudo escribir la caché del benchmark", exc_info=True)
    return result


def list_backends() -> list[dict[str, object]]:
    """Inventario declarado de todos los motores, instalados o no."""
    available = detect_available()
    return [
        {
            "name": profile.name,
            "installed": available.get(name, False),
            "license": profile.license,
            "min_vram_mb": profile.min_vram_mb,
            "runtime_overhead_mb": profile.runtime_overhead_mb,
            "capabilities": sorted(c.value for c in profile.capabilities),
            "notes": profile.notes,
        }
        for name, profile in PROFILES.items()
    ]
