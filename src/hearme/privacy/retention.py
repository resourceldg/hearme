"""Retención: el servidor orquesta, no almacena.

## El problema, medido

Antes de este módulo el servidor guardaba, por cada libro convertido:

| Qué | Dónde | Tamaño (libro real de 274 min) |
|---|---|---|
| El documento subido | `uploads/` | 2,4 MB |
| El texto completo del documento | columna `payload` de la BD | 0,45 MB |
| El audio generado | `output/` | 131,5 MB |
| **Total** | | **134 MB** |

Una biblioteca con 5000 títulos: **672 GB**. Y el 98% de eso es audio que el
cliente ya tiene descargado.

No es solo una factura de disco. Es superficie de exposición: cada byte
conservado es un byte que se puede filtrar, que hay que cifrar, respaldar,
migrar y borrar cuando alguien ejerza su derecho de supresión. **Lo que no se
guarda no hay que protegerlo.**

## La política

Tres modos, y el que manda por defecto es el más estricto:

- **`EPHEMERAL`** (por defecto): el documento se borra en cuanto se ha parseado;
  el audio, en cuanto se ha descargado o al vencer su plazo. Del texto no queda
  nada. El servidor conserva metadatos degradados y el conocimiento narrativo.
- **`SESSION`**: se conserva mientras dure la sesión de trabajo. Útil para
  reconvertir con otra voz sin volver a subir.
- **`RETAINED`**: se conserva hasta que alguien lo borre. Es lo que hacía el
  sistema antes, ahora como decisión consciente de quien despliega y no como
  comportamiento por omisión.

El cambio de valor por defecto es el punto: pasar de «guardarlo todo salvo que
alguien lo impida» a «no guardar nada salvo que alguien lo pida».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from hearme.privacy.shredder import ShredReport, shred, shred_tree

logger = logging.getLogger(__name__)


class Retention(StrEnum):
    """Cuánto vive un artefacto en el servidor."""

    EPHEMERAL = "ephemeral"
    SESSION = "session"
    RETAINED = "retained"


class Artifact(StrEnum):
    """Qué se puede conservar. Cada uno con su propio plazo."""

    #: El archivo que subió la persona.
    SOURCE = "source"
    #: El texto extraído del documento.
    TEXT = "text"
    #: El audio generado.
    AUDIO = "audio"
    #: Modelos y muestras de voz. No son de nadie: se comparten y se cachean.
    CACHE = "cache"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Qué se conserva, cuánto y por qué.

    Los valores por defecto son los estrictos. Quien quiera un servidor que
    acumule tiene que decirlo, y al decirlo asume las consecuencias.
    """

    source: Retention = Retention.EPHEMERAL
    text: Retention = Retention.EPHEMERAL
    audio: Retention = Retention.SESSION
    cache: Retention = Retention.RETAINED

    #: Plazo del modo SESSION. Pasado esto, se borra aunque nadie lo pida.
    session_hours: int = 24

    def for_artifact(self, artifact: Artifact) -> Retention:
        return {
            Artifact.SOURCE: self.source,
            Artifact.TEXT: self.text,
            Artifact.AUDIO: self.audio,
            Artifact.CACHE: self.cache,
        }[artifact]

    def keeps(self, artifact: Artifact) -> bool:
        """¿Sobrevive este artefacto al final del trabajo?"""
        return self.for_artifact(artifact) is not Retention.EPHEMERAL

    def expires_at(self, artifact: Artifact, *, since: datetime | None = None) -> datetime | None:
        """Cuándo caduca, o None si no caduca solo."""
        modo = self.for_artifact(artifact)
        if modo is Retention.EPHEMERAL:
            return since or datetime.now(UTC)
        if modo is Retention.SESSION:
            return (since or datetime.now(UTC)) + timedelta(hours=self.session_hours)
        return None

    def explain(self) -> str:
        """Frase para la interfaz. Quien sube algo merece saber qué pasa con ello."""
        partes = []
        if not self.keeps(Artifact.SOURCE):
            partes.append("tu documento se borra en cuanto se ha leído")
        if not self.keeps(Artifact.TEXT):
            partes.append("su texto no se guarda")
        if self.for_artifact(Artifact.AUDIO) is Retention.SESSION:
            partes.append(f"el audio se borra a las {self.session_hours} h")
        elif not self.keeps(Artifact.AUDIO):
            partes.append("el audio se borra tras descargarlo")
        return "En este servicio, " + ", ".join(partes) + "." if partes else "Se conserva todo."

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "text": self.text.value,
            "audio": self.audio.value,
            "cache": self.cache.value,
            "session_hours": self.session_hours,
            "summary": self.explain(),
        }


#: Política del proyecto. Es la que hace verdad la frase «el servidor orquesta,
#: no almacena»; cambiarla es una decisión de despliegue, no un detalle.
DEFAULT_POLICY = RetentionPolicy()


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Qué se borró de verdad. Sin nombres de archivo: son contenido."""

    artifacts_removed: int = 0
    bytes_freed: int = 0
    failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "artifacts_removed": self.artifacts_removed,
            "bytes_freed": self.bytes_freed,
            "failures": self.failures,
        }


def _size_of(path: Path) -> int:
    try:
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return path.stat().st_size
    except OSError:
        return 0


def release(path: Path, artifact: Artifact, policy: RetentionPolicy | None = None) -> CleanupReport:
    """Suelta un artefacto según la política. Es el punto único de borrado.

    Que sea único importa: con varios sitios donde se borra, alguno se queda sin
    la política aplicada y el servidor empieza a acumular sin que nadie lo note.
    """
    policy = policy or DEFAULT_POLICY
    if policy.keeps(artifact) or not path.exists():
        return CleanupReport()

    tamaño = _size_of(path)
    informes: list[ShredReport] = shred_tree(path) if path.is_dir() else [shred(path)]
    fallos = sum(1 for r in informes if r.result.value == "failed")

    logger.info("liberado %s: %d artefacto(s), %d bytes", artifact.value, len(informes), tamaño)
    return CleanupReport(
        artifacts_removed=len(informes) - fallos, bytes_freed=tamaño, failures=fallos
    )


def expired(
    paths: list[Path], artifact: Artifact, policy: RetentionPolicy | None = None
) -> list[Path]:
    """Artefactos cuyo plazo ha vencido. Alimenta la limpieza periódica.

    Sin barrido periódico, el modo SESSION sería una promesa: los archivos de
    quien no vuelve a entrar se quedarían para siempre.
    """
    policy = policy or DEFAULT_POLICY
    modo = policy.for_artifact(artifact)
    if modo is Retention.RETAINED:
        return []

    ahora = datetime.now(UTC)
    vencidos = []
    for path in paths:
        if not path.exists():
            continue
        try:
            creado = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        limite = policy.expires_at(artifact, since=creado)
        if limite is not None and ahora >= limite:
            vencidos.append(path)
    return vencidos


def sweep(
    directory: Path, artifact: Artifact, policy: RetentionPolicy | None = None
) -> CleanupReport:
    """Barrido periódico de un directorio. Idempotente y seguro de repetir."""
    if not directory.exists():
        return CleanupReport()

    candidatos = [p for p in directory.iterdir()]
    total = CleanupReport()
    # Política forzada a efímera solo para este artefacto: `release` respeta la
    # política, y aquí ya se ha decidido que estos han vencido. Se construye
    # campo a campo en vez de con `**dict` porque desempaquetar borra los tipos.
    actual = policy or DEFAULT_POLICY
    efimero = Retention.EPHEMERAL
    forzada = replace(
        actual,
        source=efimero if artifact is Artifact.SOURCE else actual.source,
        text=efimero if artifact is Artifact.TEXT else actual.text,
        audio=efimero if artifact is Artifact.AUDIO else actual.audio,
        cache=efimero if artifact is Artifact.CACHE else actual.cache,
    )
    for path in expired(candidatos, artifact, policy):
        informe = release(path, artifact, forzada)
        total = CleanupReport(
            artifacts_removed=total.artifacts_removed + informe.artifacts_removed,
            bytes_freed=total.bytes_freed + informe.bytes_freed,
            failures=total.failures + informe.failures,
        )
    return total
