"""Configuración de la aplicación. Todo sobrescribible por entorno con prefijo `HEARME_`."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from hearme.domain.models import NarrationStyle


def _default_data_dir() -> Path:
    """Directorio de datos del despliegue.

    Se fija con `HEARME_DATA_DIR`, que es lo que usan la imagen de contenedor (un
    volumen montado) y cualquier instalación gestionada. El valor por defecto
    sigue la especificación XDG solo para que un despliegue de desarrollo
    arranque sin configurar nada: ninguna ruta está grabada en el código.
    """
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "hearme"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HEARME_", env_file=".env", extra="ignore")

    # --- Rutas ---
    data_dir: Path = Field(default_factory=_default_data_dir)
    models_dir: Path | None = None
    watch_dirs: list[Path] = Field(default_factory=list)

    # --- Base de datos ---
    #: SQLite por defecto (local, sin servidor). PostgreSQL con
    #: HEARME_DATABASE_URL=postgresql+asyncpg://...
    database_url: str = ""

    # --- TTS ---
    tts_engine: str = "auto"  # "auto" -> selector por idioma
    tts_voice: str | None = None
    tts_quality: str = "high"  # "high" | "draft"
    narration_style: NarrationStyle = NarrationStyle.NEUTRAL
    allow_non_commercial_models: bool = True

    # --- Traducción ---
    translator: str = "auto"
    target_language: str | None = None

    # --- OCR ---
    ocr_enabled: bool = True
    ocr_language: str = "spa+eng"
    #: Umbral de caracteres por página bajo el cual se considera PDF escaneado.
    ocr_char_threshold: int = 100

    # --- LLM / modo estudio ---
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"  # 3B cuantizado: modesto en recursos, suficiente

    # --- Almacenamiento ---
    #: Espacio máximo para artefactos (audio y subidas), en MB. 0 = sin límite.
    #:
    #: HearMe fabrica bibliotecas, no las guarda: el audio vive aquí de paso
    #: hasta que quien lo pidió se lo lleva. Este presupuesto es el tamaño de ese
    #: buffer, y lo fija quien despliega, no quien dona: repartir capacidad por
    #: capacidad de pago daría menos a quien más lo necesita.
    #:
    #: El conocimiento —reputación, reglas, historial— NO cuenta aquí y nunca se
    #: recolecta. Ocupa kilobytes y es lo único irrecuperable.
    storage_budget_mb: int = 2048

    # --- Ejecución ---
    max_workers: int = 0  # 0 -> derivado del hardware
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    #: Orígenes permitidos por CORS, separados por comas. La UI de SvelteKit corre
    #: en 5173 en desarrollo y en 3000 servida por adapter-node (o por Docker), y
    #: el navegador la trata como origen distinto al de la API. Sin los dos, la
    #: interfaz carga pero todas sus llamadas fallan.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def resolved_models_dir(self) -> Path:
        return self.models_dir or (self.data_dir / "models")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'hearme.db'}"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.uploads_dir,
            self.output_dir,
            self.cache_dir,
            self.resolved_models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
