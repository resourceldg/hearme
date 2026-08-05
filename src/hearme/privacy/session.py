"""Sesión privada: leer sin dejar rastro.

Alguien consulta un informe médico, un expediente judicial, un texto sobre su
orientación o su fe. Terminada la escucha, no debe quedar nada: ni el documento,
ni el audio, ni una entrada en el historial, ni el título en un registro.

## Cómo se consigue de verdad

La clave de una sesión privada **se genera en memoria y no se escribe jamás**.
Todo lo que la sesión produce —temporales, audio intermedio, texto extraído— se
cifra con ella. Al cerrar, la clave se olvida.

Eso convierte el borrado en instantáneo y fiable: los restos que el SSD no haya
liberado son ruido sin la clave. No dependemos de que sobrescribir funcione,
porque sabemos que en almacenamiento moderno no funciona (ver `shredder`).

## Lo que no puede evitar

Conviene decirlo antes de que alguien confíe de más:

- **Memoria paginada.** Si el sistema envía memoria a swap, la clave puede tocar
  el disco. Se mitiga con swap cifrado, que es cosa del despliegue.
- **Quien controla la máquina.** Un administrador con acceso al proceso puede
  leer la clave mientras la sesión está abierta. Esto protege frente a análisis
  posterior, no frente a vigilancia en directo.
- **Caídas.** Si el proceso muere de golpe, los temporales cifrados quedan; sin
  la clave son ilegibles, pero ocupan sitio hasta la limpieza siguiente.

Un modo privado que prometa más que esto está mintiendo.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hearme.privacy.crypto import (
    Envelope,
    generate_key,
    random_token,
    seal,
    unseal,
    wipe,
)
from hearme.privacy.shredder import ShredReport, shred_tree, summarize

logger = logging.getLogger(__name__)


class SessionClosed(Exception):
    """Se usó una sesión ya cerrada. Su clave ya no existe."""


@dataclass(slots=True)
class SessionTrace:
    """Lo único que sobrevive a una sesión privada: que existió y cuánto duró.

    Ni el documento, ni el título, ni el idioma, ni el tamaño. Se conserva porque
    un servicio necesita saber que procesó algo —para cuotas, para detectar
    abuso, para depurar—, y porque negar la existencia misma de la sesión sería
    una promesa que el registro del sistema desmentiría igualmente.
    """

    session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    artifacts_destroyed: int = 0
    #: Nunca contiene nombres ni rutas. Ver `shredder.summarize`.
    shred_summary: str = ""

    @property
    def duration_s(self) -> float:
        if self.ended_at is None:
            return 0.0
        return (self.ended_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_s": round(self.duration_s, 1),
            "artifacts_destroyed": self.artifacts_destroyed,
            "shred_summary": self.shred_summary,
        }


@dataclass(slots=True)
class PrivateSession:
    """Sesión efímera con su propia clave, que nunca se persiste."""

    session_id: str = field(default_factory=lambda: random_token(16))
    root: Path | None = None
    _key: bytearray | None = field(default=None, repr=False)
    _started: datetime = field(default_factory=lambda: datetime.now(UTC))
    _artifacts: list[Path] = field(default_factory=list)
    _closed: bool = False

    def __post_init__(self) -> None:
        if self._key is None:
            self._key = bytearray(generate_key())
        if self.root is None:
            # Directorio propio: al cerrar se arrasa entero sin tocar nada ajeno.
            self.root = Path(tempfile.mkdtemp(prefix=f"hearme-priv-{self.session_id[:8]}-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    # --- uso ----------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return not self._closed

    def _require_open(self) -> bytes:
        if self._closed or self._key is None:
            raise SessionClosed("la sesión está cerrada; su clave ya no existe")
        return bytes(self._key)

    def write(self, name: str, data: bytes) -> Path:
        """Escribe un temporal **ya cifrado**. Es la única forma de escribir aquí.

        No existe un `write_plaintext`: si la sesión pudiera escribir en claro,
        la garantía dependería de que nadie se olvide de usar el método correcto,
        y ese olvido ocurre siempre.
        """
        key = self._require_open()
        assert self.root is not None
        destino = self.root / f"{name}.sealed"
        sobre = seal(key, data, context=f"hearme:session:{self.session_id}:{name}")
        destino.write_bytes(sobre.to_bytes())
        destino.chmod(0o600)
        self._artifacts.append(destino)
        return destino

    def read(self, name: str) -> bytes:
        key = self._require_open()
        assert self.root is not None
        origen = self.root / f"{name}.sealed"
        if not origen.exists():
            raise FileNotFoundError(f"no hay artefacto '{name}' en la sesión")
        return unseal(
            key,
            Envelope.from_bytes(origen.read_bytes()),
            context=f"hearme:session:{self.session_id}:{name}",
        )

    def close(self) -> SessionTrace:
        """Destruye la clave y arrasa el directorio. Idempotente.

        El orden importa: primero se olvida la clave —lo que ya inutiliza todo lo
        escrito— y después se sobrescribe. Si el proceso muriera entre ambos
        pasos, lo que queda en disco sigue siendo indescifrable.
        """
        if self._closed:
            return SessionTrace(
                session_id=self.session_id, started_at=self._started, ended_at=datetime.now(UTC)
            )

        total = len(self._artifacts)
        if self._key is not None:
            wipe(self._key)
        self._key = None
        self._closed = True

        informes: list[ShredReport] = []
        if self.root is not None and self.root.exists():
            informes = shred_tree(self.root)

        rastro = SessionTrace(
            session_id=self.session_id,
            started_at=self._started,
            ended_at=datetime.now(UTC),
            artifacts_destroyed=total,
            shred_summary=summarize(informes),
        )
        logger.info(
            "sesión privada %s cerrada: %d artefacto(s) destruidos",
            self.session_id[:8],
            total,
        )
        return rastro

    def __enter__(self) -> PrivateSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
