"""Capacidad de cómputo del nodo y elección de perfil de ejecución.

HearMe se despliega en sitios muy distintos —un servidor de una biblioteca, un
contenedor en la nube, el equipo compartido de una asociación— y en todos debe
narrar bien. Este módulo mide de qué dispone *el nodo que ejecuta el servicio*
para que el planificador elija en consecuencia, sin que nadie tenga que
configurar nada a mano ni saber qué es un acelerador.

No asume que torch esté instalado: el núcleo debe poder describir su capacidad
antes de que exista ninguna dependencia de ML.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from functools import cache


class Accelerator(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    ROCM = "rocm"
    MPS = "mps"  # Apple Silicon


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    accelerator: Accelerator
    device_name: str
    vram_mb: int
    cpu_cores: int
    ram_mb: int
    arch: str
    system: str

    @property
    def can_run_on_gpu(self) -> bool:
        return self.accelerator is not Accelerator.CPU

    def fits_in_vram(self, model_mb: int, *, headroom: float = 1.25) -> bool:
        """¿Cabe el modelo en VRAM dejando margen para activaciones y contexto?"""
        return self.can_run_on_gpu and model_mb * headroom <= self.vram_mb

    @property
    def tts_workers(self) -> int:
        """Paralelismo de síntesis en CPU.

        La síntesis es un proceso corto y ligado a CPU; dejamos cores libres para
        ffmpeg y la API. Tope en 8 porque más allá domina la contención de memoria.
        """
        return max(1, min(self.cpu_cores - 2, 8))

    def describe(self) -> str:
        """Capacidad del nodo en términos de operación del servicio.

        Deliberadamente no menciona el modelo del equipo ni su memoria de vídeo.
        Quien opera un despliegue necesita saber cuántas narraciones puede hacer
        a la vez y si hay aceleración; el inventario del aparato no aporta nada y
        convierte un registro del servicio en la ficha técnica de una máquina.
        Los valores en crudo siguen disponibles en los campos del perfil para
        quien depure el planificador.
        """
        aceleracion = "con aceleración" if self.can_run_on_gpu else "solo CPU"
        return (
            f"{self.accelerator.value} ({aceleracion}) · {self.tts_workers} narraciones simultáneas"
        )


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _detect_cuda() -> tuple[str, int] | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out:
        return None
    name, _, mem = out.splitlines()[0].partition(",")
    try:
        return name.strip(), int(mem.strip())
    except ValueError:
        return None


def _detect_rocm() -> tuple[str, int] | None:
    if not shutil.which("rocm-smi"):
        return None
    out = _run(["rocm-smi", "--showmeminfo", "vram", "--csv"])
    if not out:
        return None
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and parts[-1].strip().isdigit():
            return "AMD ROCm GPU", int(parts[-1].strip()) // (1024 * 1024)
    return "AMD ROCm GPU", 0


def _detect_mps() -> tuple[str, int] | None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    # En Apple Silicon la memoria es unificada: la "VRAM" útil es una fracción de la RAM.
    return f"Apple Silicon ({platform.machine()})", _total_ram_mb() * 2 // 3


def _total_ram_mb() -> int:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * size // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 0


@cache
def detect() -> HardwareProfile:
    """Perfil del nodo. Cacheado: su capacidad no cambia en caliente."""
    forced = os.getenv("HEARME_FORCE_DEVICE", "").lower()

    detected: tuple[Accelerator, str, int] | None = None
    for accel, probe in (
        (Accelerator.CUDA, _detect_cuda),
        (Accelerator.ROCM, _detect_rocm),
        (Accelerator.MPS, _detect_mps),
    ):
        if forced and forced != accel.value:
            continue
        if (found := probe()) is not None:
            detected = (accel, found[0], found[1])
            break

    if forced == Accelerator.CPU.value or detected is None:
        accelerator, device_name, vram = Accelerator.CPU, platform.processor() or "CPU", 0
    else:
        accelerator, device_name, vram = detected

    return HardwareProfile(
        accelerator=accelerator,
        device_name=device_name,
        vram_mb=vram,
        cpu_cores=os.cpu_count() or 1,
        ram_mb=_total_ram_mb(),
        arch=platform.machine(),
        system=platform.system(),
    )
