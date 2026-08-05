"""Tests de la API REST.

Usan una base de datos temporal: no tocan los datos reales del usuario.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data_dir = tmp_path_factory.mktemp("hearme-data")
    os.environ["HEARME_DATA_DIR"] = str(data_dir)
    os.environ["HEARME_DATABASE_URL"] = f"sqlite+aiosqlite:///{data_dir / 'test.db'}"
    return data_dir


@pytest.fixture
async def client(temp_data_dir: Path) -> AsyncIterator[AsyncClient]:
    # Import tardío: la configuración debe leerse ya con el directorio temporal.
    from hearme.config import settings
    from hearme.infrastructure.persistence import database
    from hearme.interfaces.api.app import app

    settings.data_dir = temp_data_dir
    settings.database_url = f"sqlite+aiosqlite:///{temp_data_dir / 'test.db'}"
    # El motor es global y cacheado: hay que soltarlo para que tome la URL nueva.
    await database.dispose()

    # ASGITransport no dispara el lifespan, así que se ejecuta a mano. Sin esto no
    # se crean las tablas ni se cargan los plugins, y los tests medirían otra cosa.
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
    ):
        yield http_client

    await database.dispose()


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_system_describe_capacidad_y_plugins(client: AsyncClient) -> None:
    payload = (await client.get("/api/system")).json()

    # La capacidad del nodo es información de operación: existe, pero no expone
    # nada del equipo de quien escucha.
    assert payload["runtime"]["synthesis_workers"] >= 1
    assert payload["runtime"]["accelerator"] in {"cpu", "cuda", "rocm", "mps"}
    assert isinstance(payload["runtime"]["languages"], list)
    assert "markdown" in payload["parsers"]
    assert "m4b" in payload["exporters"]
    assert isinstance(payload["warnings"], list)


async def test_convert_encola_y_devuelve_202(client: AsyncClient, tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Título\n\nUn párrafo de prueba.\n", encoding="utf-8")

    response = await client.post(
        "/api/convert",
        files={"file": ("doc.md", source.read_bytes(), "text/markdown")},
        data={"options": json.dumps({"mode": "read", "formats": ["md"]})},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    job_id = response.json()["job_id"]
    detail = (await client.get(f"/api/jobs/{job_id}")).json()
    assert detail["id"] == job_id


async def test_rechaza_formato_de_salida_desconocido(client: AsyncClient, tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Hola\n", encoding="utf-8")

    response = await client.post(
        "/api/convert",
        files={"file": ("doc.md", source.read_bytes(), "text/markdown")},
        data={"options": json.dumps({"formats": ["ogg"]})},
    )

    assert response.status_code == 400
    assert "ogg" in response.json()["detail"]


async def test_rechaza_extension_sin_parser(client: AsyncClient) -> None:
    response = await client.post(
        "/api/convert",
        files={"file": ("archivo.xyz", b"contenido", "application/octet-stream")},
        data={"options": "{}"},
    )
    assert response.status_code == 415


async def test_opciones_mal_formadas_dan_400(client: AsyncClient) -> None:
    response = await client.post(
        "/api/convert",
        files={"file": ("doc.md", b"# Hola", "text/markdown")},
        data={"options": "esto no es json"},
    )
    assert response.status_code == 400


async def test_trabajo_inexistente_da_404(client: AsyncClient) -> None:
    assert (await client.get("/api/jobs/noexiste")).status_code == 404


async def test_lista_de_trabajos_es_una_lista(client: AsyncClient) -> None:
    response = await client.get("/api/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.parametrize("origen", ["http://localhost:3000", "http://localhost:5173"])
async def test_cors_permite_los_origenes_de_la_interfaz(client: AsyncClient, origen: str) -> None:
    """La UI y la API viven en puertos distintos: sin CORS la interfaz carga vacía.

    5173 es el dev server de Vite; 3000 es adapter-node y el perfil `web` de
    Docker. Faltaba el segundo, así que la interfaz desplegada no podía hablar
    con su propio backend.
    """
    response = await client.get("/api/health", headers={"Origin": origen})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origen


async def test_el_formato_se_valida_antes_de_escribir_el_archivo(
    client: AsyncClient, temp_data_dir: Path
) -> None:
    """Copiar 300 MB al disco para rechazarlos después es tiempo tirado."""
    response = await client.post(
        "/api/convert",
        files={"file": ("libro.xyz", b"x" * 4096, "application/octet-stream")},
        data={"options": "{}"},
    )
    assert response.status_code == 415
    subidas = temp_data_dir / "uploads"
    assert not list(subidas.glob("libro.xyz")), "no debe quedar el archivo rechazado"
