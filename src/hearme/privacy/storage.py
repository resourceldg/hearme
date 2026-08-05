"""Cuánto ocupa cada cosa, y cómo soltarlo.

## La corrección al principio anterior

«El servidor orquesta, no almacena» estaba **demasiado apretado**. La distinción
que importa no es guardar o no guardar, sino qué se guarda:

| Categoría | Ejemplo | ¿Rehacible? | Decisión |
|---|---|---|---|
| **Conocimiento** | reputación, reglas | **No** | Guardar siempre |
| **Artefacto** | el audio generado | Sí | Guardar, con cuenta y recolector |
| **Origen** | el documento subido | Lo tiene quien lo subió | No guardar |

Perder la reputación al reiniciar era lo contrario de lo que el proyecto quiere:
es justo lo que la comunidad ha construido y lo único que no se puede recuperar.

Lo que sí era un problema no es guardar, es **acumular en silencio**. Un servidor
que crece sin que nadie sepa cuánto ni de qué acaba lleno un domingo por la
noche, y entonces se borra a lo bruto lo primero que se encuentra.

## Las dos reglas que hacen honesto guardar

**Se ve lo que ocupa.** Siempre, desglosado por categoría, sin tener que entrar
por SSH a mirar. Un número a la vista se gestiona; uno escondido se ignora hasta
que estalla.

**Se puede soltar, y se dice antes qué se va a soltar.** El recolector calcula y
enseña qué borraría y cuánto liberaría **antes** de tocar nada. Un botón de
limpiar que no dice qué se lleva por delante no se pulsa, y con razón.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from hearme.privacy.shredder import shred, shred_tree

logger = logging.getLogger(__name__)


class Category(StrEnum):
    """En qué se va el espacio. El orden es de más a menos recuperable."""

    #: Audio generado. Grande y rehacible: es el primer candidato del recolector.
    AUDIO = "audio"
    #: Documentos subidos. No deberían estar aquí si la retención es efímera.
    SOURCE = "source"
    #: Modelos de voz y muestras. Grande pero compartido: borrarlo obliga a
    #: descargarlo otra vez y ralentiza a todo el mundo, no solo a quien limpia.
    MODELS = "models"
    #: Temporales de trabajos, WAVs intermedios, restos de conversiones caídas.
    TEMP = "temp"
    #: Base de datos: reputación, historial, metadatos. Es el conocimiento.
    KNOWLEDGE = "knowledge"


#: Qué se puede recolectar sin perder nada irrecuperable.
#:
#: `KNOWLEDGE` no está, y es el punto entero de este módulo: es lo único que la
#: comunidad no puede rehacer. `MODELS` tampoco por defecto —se vuelve a
#: descargar, pero cuesta minutos a todo el mundo.
COLLECTABLE = (Category.TEMP, Category.AUDIO, Category.SOURCE)


def human(size_bytes: int) -> str:
    """Tamaño legible. Se redondea porque nadie decide con los bytes exactos."""
    for unidad, umbral in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if size_bytes >= umbral:
            return f"{size_bytes / umbral:.1f} {unidad}"
    return f"{size_bytes} B"


def _measure(path: Path) -> tuple[int, int]:
    """(bytes, número de archivos) de una ruta. Tolerante a que no exista."""
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    total = archivos = 0
    for hijo in path.rglob("*"):
        try:
            if hijo.is_file():
                total += hijo.stat().st_size
                archivos += 1
        except OSError:
            continue
    return total, archivos


@dataclass(frozen=True, slots=True)
class CategoryUsage:
    category: Category
    bytes_used: int
    files: int
    collectable: bool
    #: Lo más antiguo que hay aquí. Da idea de si sobra o si se está usando.
    oldest: datetime | None = None

    @property
    def human_size(self) -> str:
        return human(self.bytes_used)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "bytes": self.bytes_used,
            "human": self.human_size,
            "files": self.files,
            "collectable": self.collectable,
            "oldest": self.oldest.isoformat() if self.oldest else None,
        }


@dataclass(slots=True)
class StorageReport:
    """Cuánto ocupa el servicio, desglosado. Es lo que se enseña en la interfaz."""

    categories: list[CategoryUsage] = field(default_factory=list)
    measured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_bytes(self) -> int:
        return sum(c.bytes_used for c in self.categories)

    @property
    def collectable_bytes(self) -> int:
        return sum(c.bytes_used for c in self.categories if c.collectable)

    @property
    def knowledge_bytes(self) -> int:
        return sum(c.bytes_used for c in self.categories if c.category is Category.KNOWLEDGE)

    def explain(self) -> str:
        """Una frase con lo que hace falta para decidir si limpiar."""
        if not self.total_bytes:
            return "El servicio no ocupa espacio todavía."

        base = f"El servicio ocupa {human(self.total_bytes)}."
        if self.collectable_bytes:
            base += (
                f" Se pueden liberar {human(self.collectable_bytes)} sin perder nada"
                " que no se pueda rehacer."
            )
        if self.knowledge_bytes:
            base += (
                f" De eso, {human(self.knowledge_bytes)} son conocimiento —reputación,"
                " reglas, historial— que no se borra: es lo único irrecuperable."
            )
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "total_human": human(self.total_bytes),
            "collectable_bytes": self.collectable_bytes,
            "collectable_human": human(self.collectable_bytes),
            "knowledge_bytes": self.knowledge_bytes,
            "categories": [c.to_dict() for c in self.categories],
            "measured_at": self.measured_at.isoformat(),
            "explanation": self.explain(),
        }


def measure(
    *,
    output_dir: Path,
    uploads_dir: Path,
    models_dir: Path,
    cache_dir: Path,
    database_path: Path | None = None,
) -> StorageReport:
    """Mide el espacio por categoría. Solo lee: no borra nada."""
    rutas: list[tuple[Category, Path]] = [
        (Category.AUDIO, output_dir),
        (Category.SOURCE, uploads_dir),
        (Category.MODELS, models_dir),
        (Category.TEMP, cache_dir),
    ]
    if database_path is not None:
        rutas.append((Category.KNOWLEDGE, database_path))

    categorias = []
    for categoria, ruta in rutas:
        tamaño, archivos = _measure(ruta)
        mas_antiguo = None
        if ruta.exists() and ruta.is_dir():
            marcas = [p.stat().st_mtime for p in ruta.iterdir() if p.exists()]
            if marcas:
                mas_antiguo = datetime.fromtimestamp(min(marcas), tz=UTC)
        categorias.append(
            CategoryUsage(
                category=categoria,
                bytes_used=tamaño,
                files=archivos,
                collectable=categoria in COLLECTABLE,
                oldest=mas_antiguo,
            )
        )
    return StorageReport(categories=categorias)


@dataclass(frozen=True, slots=True)
class CollectionPlan:
    """Qué se borraría y cuánto se liberaría. **Se calcula antes de borrar.**

    Existe para que el botón de limpiar pueda decir qué se lleva por delante. Un
    borrado que no se puede previsualizar no se pulsa, y con razón.
    """

    items: tuple[Path, ...] = ()
    bytes_to_free: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    #: Lo que se ha protegido y por qué. Tan importante como lo que se borra.
    protected: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def explain(self) -> str:
        if self.is_empty:
            return (
                "No hay nada que liberar: todo lo que ocupa espacio está en uso o es conocimiento."
            )
        detalle = ", ".join(f"{cat} {human(b)}" for cat, b in sorted(self.by_category.items()))
        return (
            f"Se liberarían {human(self.bytes_to_free)} en {len(self.items)} elemento(s)"
            f" ({detalle}). El conocimiento no se toca."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": len(self.items),
            "bytes_to_free": self.bytes_to_free,
            "human": human(self.bytes_to_free),
            "by_category": self.by_category,
            "protected": self.protected,
            "explanation": self.explain(),
        }


def plan_collection(
    *,
    output_dir: Path,
    uploads_dir: Path,
    cache_dir: Path,
    older_than_hours: int = 24,
    keep_recent: int = 5,
) -> CollectionPlan:
    """Decide qué soltar, **sin tocar nada**.

    Dos protecciones que evitan el arrepentimiento:

    - **Antigüedad**: no se toca nada reciente. Quien acaba de convertir algo lo
      va a descargar en los próximos minutos.
    - **Los últimos N**: aunque sean viejos, se conservan los más recientes. Un
      servidor poco usado tendría todo «antiguo» y una limpieza se lo llevaría
      entero, que no es lo que nadie espera al pulsar «liberar espacio».
    """
    limite = datetime.now(UTC) - timedelta(hours=older_than_hours)
    candidatos: list[tuple[Path, Category, float, int]] = []

    for categoria, directorio in (
        (Category.TEMP, cache_dir),
        (Category.AUDIO, output_dir),
        (Category.SOURCE, uploads_dir),
    ):
        if not directorio.exists():
            continue
        for hijo in directorio.iterdir():
            try:
                marca = hijo.stat().st_mtime
            except OSError:
                continue
            tamaño, _ = _measure(hijo)
            candidatos.append((hijo, categoria, marca, tamaño))

    # Los más recientes se protegen, sea cual sea su antigüedad.
    candidatos.sort(key=lambda c: c[2], reverse=True)
    protegidos_recientes = {c[0] for c in candidatos[:keep_recent]}

    seleccionados: list[Path] = []
    por_categoria: dict[str, int] = {}
    total = 0
    protegido: dict[str, str] = {}

    if protegidos_recientes:
        protegido["recientes"] = (
            f"{len(protegidos_recientes)} elemento(s) recientes se conservan siempre"
        )

    for ruta, categoria, marca, tamaño in candidatos:
        if ruta in protegidos_recientes:
            continue
        if datetime.fromtimestamp(marca, tz=UTC) > limite:
            protegido.setdefault("en uso", f"lo de las últimas {older_than_hours} h no se toca")
            continue
        seleccionados.append(ruta)
        por_categoria[categoria.value] = por_categoria.get(categoria.value, 0) + tamaño
        total += tamaño

    protegido["conocimiento"] = "la reputación, las reglas y el historial no se borran nunca"

    return CollectionPlan(
        items=tuple(seleccionados),
        bytes_to_free=total,
        by_category=por_categoria,
        protected=protegido,
    )


@dataclass(frozen=True, slots=True)
class CollectionResult:
    freed_bytes: int
    items_removed: int
    failures: int

    def explain(self) -> str:
        base = f"Liberados {human(self.freed_bytes)} en {self.items_removed} elemento(s)."
        if self.failures:
            base += f" {self.failures} no se pudieron borrar; se reintentarán."
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "freed_bytes": self.freed_bytes,
            "freed_human": human(self.freed_bytes),
            "items_removed": self.items_removed,
            "failures": self.failures,
            "explanation": self.explain(),
        }


def collect(plan: CollectionPlan) -> CollectionResult:
    """Ejecuta un plan. **Solo borra lo que el plan enumeró.**

    Recibir el plan en vez de recalcularlo no es un capricho: garantiza que se
    borra exactamente lo que se enseñó, aunque entre la previsualización y la
    confirmación haya aparecido algo nuevo.
    """
    liberados = elementos = fallos = 0

    for ruta in plan.items:
        if not ruta.exists():
            continue
        tamaño, _ = _measure(ruta)
        informes = shred_tree(ruta) if ruta.is_dir() else [shred(ruta)]
        if any(r.result.value == "failed" for r in informes):
            fallos += 1
            continue
        liberados += tamaño
        elementos += 1

    logger.info("recolección: %s liberados en %d elementos", human(liberados), elementos)
    return CollectionResult(freed_bytes=liberados, items_removed=elementos, failures=fallos)
