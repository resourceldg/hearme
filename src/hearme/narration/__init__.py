"""Narración: el cerebro de estilo, separado del motor que pone la voz.

Un motor TTS es un cartucho intercambiable. Lo que no queremos cambiar cada vez
que aparece uno mejor es *el criterio de cómo se lee un texto*: dónde respirar,
qué palabra pesa, cuándo bajar el ritmo porque el párrafo lo pide.

Ese criterio vive aquí, en tres piezas:

  - `score`     La partitura: anotaciones de pausa, énfasis, ritmo y tono sobre
                tramos de texto, en unidades que no pertenecen a ningún motor.
  - `director`  Quien escribe la partitura a partir del texto. Hoy son reglas;
                mañana, un modelo entrenado con lo que aporte la comunidad.
  - `adapters`  Quien traduce la partitura a los mandos de cada motor concreto,
                y dice con franqueza qué parte no ha podido respetar.

La partitura es el activo que perdura. Los motores pasan; el trabajo de la
comunidad se acumula en el formato de `score` y sobrevive a todos ellos.
"""

from hearme.narration.adapters import (
    KOKORO,
    PIPER,
    SSML_FULL,
    EngineCapabilities,
    RenderPlan,
    capabilities_for,
)
from hearme.narration.director import (
    NarrationDirector,
    RuleBasedDirector,
    default_director,
)
from hearme.narration.score import (
    SCHEMA_VERSION,
    MarkSource,
    NarrationScore,
    ProsodyMark,
    SpanRole,
)

__all__ = [
    "KOKORO",
    "PIPER",
    "SCHEMA_VERSION",
    "SSML_FULL",
    "EngineCapabilities",
    "MarkSource",
    "NarrationDirector",
    "NarrationScore",
    "ProsodyMark",
    "RenderPlan",
    "RuleBasedDirector",
    "SpanRole",
    "capabilities_for",
    "default_director",
]
