# Reconocimiento de voz (ASR) — revisión del estado del arte (agosto 2026)

> Revisión previa a escribir código, verificada con fuentes de 2026 y no con memoria.
> Mismo método que [el análisis de inferencia](ANALISIS-INFERENCIA.md): decisiones al
> final de cada sección.

## 0. ¿Para qué necesita ASR un conversor de documentos a audio?

La pregunta no es retórica. HearMe va de texto a voz, así que meter voz a
texto exige justificar por qué. Hay dos usos reales, y **son trabajos distintos con
modelos óptimos distintos**:

| Uso | Duración | Idiomas | Texto esperado | Exigencia |
|---|---|---|---|---|
| **Verificar la frase de consentimiento** al clonar voz | 3 s | el del usuario | **conocido de antemano** | latencia, no precisión |
| **Audio como formato de entrada** (charla, pódcast) | horas | cualquiera | desconocido | precisión y RTF |

El primero **no es una función nueva: es una deuda ya contraída**. El análisis de
inferencia §5 fijó como salvaguarda que la muestra de enrolamiento "debe contener
una frase concreta, no vale un audio cualquiera de un tercero". Esa salvaguarda
**hoy es inaplicable**, porque nada en el proyecto sabe comprobar qué se dijo. Un
clonador de voz sin ese control es un motor de suplantación con un cartel de
advertencia.

Verificar una frase conocida es un problema mucho más fácil que transcribir: no hay
que acertar el texto, hay que comparar contra uno dado. Tolera un WER alto.

**Consecuencia de diseño:** el ASR entra al proyecto por la puerta de la salvaguarda,
no por la de la funcionalidad. Si solo se implementara una cosa, es esa.

---

## 1. Modelos de ASR abiertos — comparativa 2026

| Modelo | Licencia | Params | Idiomas | WER medio | Notas |
|---|---|---|---|---|---|
| **Qwen3-ASR-0.6B** | **Apache-2.0** | ~0,6 B | **52** | **5,83 %** | RTF 0,064; ~2 GB fp16, ~0,5 GB int4 |
| Qwen3-ASR-1.7B | Apache-2.0 | 1,7 B | 52 | 5,34 % | Mejor, pero 3x memoria |
| **Whisper large-v3** | **MIT** | 1,55 B | **99** | 7,44 % | El estándar de facto; ~10 GB |
| Whisper small / base | MIT | 244 M / 74 M | 99 | — | ~95 % de large-v3 al 6x de velocidad |
| **Parakeet TDT 0.6B v3** | CC-BY-4.0 | 0,6 B | **25** | **6,32 %** | El más rápido con diferencia; exige NeMo |
| NVIDIA Canary | CC-BY-4.0 | — | pocos | 6,67 % | Máxima precisión absoluta |
| **Moonshine** | MIT | 27 M / 62 M | **solo inglés** | — | 190-400 MB; imbatible en el borde |
| Vosk | Apache-2.0 | pequeño | varios | alto | Muy ligero, precisión de otra época |

### Datos medidos que importan

- **Parakeet es 40-50x más rápido por unidad de cómputo que Whisper large-v3**, y no
  alucina en los silencios. Pero cubre 25 idiomas europeos frente a los 99 de Whisper.
- **En CPU pura, Whisper es viable hasta `small`**; en `large-v3` un i9 transcribe
  **2,5 veces más lento que el tiempo real**, o sea inservible para horas de audio.
- **faster-whisper con int8 va a ~20x tiempo real en CPU**, algo por delante de
  whisper.cpp (~15x), y es la vía práctica en 4-6 GB de VRAM.
- **Qwen3-ASR-0.6B baja a ~0,5 GB en int4** y da RTF 0,064. Es el único de la lista
  que combina precisión de cabeza, 52 idiomas y una huella que cabe holgadamente en
  la máquina objetivo.

### Lectura para nuestro hardware y nuestra licencia

Whisper large-v3 son ~10 GB: **no entra en 4 GB**, igual que le pasaba a vLLM. Los
modelos de NVIDIA (Parakeet, Canary) son CC-BY-4.0, que permite uso comercial pero
**obliga a atribuir**, y arrastran NeMo, un framework pesado y atado a NVIDIA.

### Decisión

> **Qwen3-ASR-0.6B (Apache-2.0) como motor principal.**
>
> El argumento decisivo no es el WER, que es el mejor de los que caben, sino que
> **el proyecto ya eligió Qwen3-TTS (Apache-2.0) para clonación de voz**. Son la
> misma familia, la misma licencia y la misma pila de `transformers`. El enrolamiento
> de voz necesita ambos en la misma pantalla —grabar 3 s, verificar la frase,
> clonar—, así que elegir otro motor de ASR significaría mantener dos stacks para
> completar **una sola** función.
>
> - `whisper.cpp` / `faster-whisper` (**MIT**) — **fallback sin suelo de VRAM**, igual
>   papel que llama.cpp en el análisis de inferencia: en `small` o `base` corre en
>   CPU pura donde Qwen no tenga GPU. Cubre además los 99 idiomas, incluidos los que
>   Qwen3-ASR no alcanza.
> - `Parakeet` / `Canary` — **no se incluyen**. NeMo es un framework pesado solo para
>   NVIDIA, cubren menos idiomas, y CC-BY-4.0 añade una obligación de atribución que
>   Apache-2.0 no impone. Es el mismo criterio que excluyó a TensorRT-LLM: velocidad
>   real a cambio de atar el proyecto a un fabricante.
> - `Moonshine` (MIT) — **no se incluye**. 27 MB y excelente en el borde, pero los
>   modelos publicados son **solo inglés**. En un proyecto escrito en español y
>   pensado para audiolibros multilingües, eso lo descarta pese a ser técnicamente
>   precioso para el caso de la frase de consentimiento.
> - `Vosk` (Apache-2.0) — **no se incluye**: su precisión pertenece a otra generación
>   y hoy no compensa frente a un Qwen3-ASR en int4.

---

## 2. Por qué un solo motor y no uno por trabajo

La tentación es usar un modelo minúsculo para la frase de consentimiento (basta) y
uno grande para transcribir. Se rechaza: **`Qwen3-ASR-0.6B` en int4 ocupa ~0,5 GB**,
lo mismo que costaría el modelo "pequeño" especializado, y mantener dos motores
significa dos descargas, dos formatos y dos rutas de fallo para el usuario.

El tamaño del trabajo se refleja donde debe, que es en el plan de ejecución: la
verificación de 3 segundos no necesita lote ni paralelismo; la transcripción de una
charla de una hora sí. Eso ya lo resuelve el planificador existente sin duplicar
motores.

## 3. Encaje con el subsistema de inferencia

`WorkloadClass.ASR` ya existía sin un solo perfil detrás. Con esta decisión:

- **El decodificador de ASR es autorregresivo** y tiene caché KV, igual que un
  seq2seq. Se le reclasifica como tal — antes estaba fuera del grupo, lo que era
  sencillamente incorrecto. Sus secuencias son cortas, así que, igual que en
  traducción, **solo el batching amortiza**: ni paginar ni comprimir una caché de
  unos pocos cientos de tokens.
- Los perfiles se registran con `adapter_available=False` hasta que exista el
  adaptador. El planificador los rechaza diciendo "adaptador aún no implementado"
  en vez de fingir que puede usarlos.

## 4. Resumen de decisiones

| Punto | Decisión | Razón dominante |
|---|---|---|
| Motivo de entrada del ASR | **La salvaguarda de clonación** | Ya comprometida y hoy inaplicable |
| Motor principal | **Qwen3-ASR-0.6B** | Apache-2.0 y misma familia que Qwen3-TTS |
| Fallback sin GPU | **whisper.cpp / faster-whisper** | Sin suelo de VRAM; 99 idiomas |
| Whisper large-v3 | **Registrado, se autodescarta** | ~10 GB no entran en 4 GB |
| Parakeet / Canary | **Excluidos** | NeMo, NVIDIA-only, CC-BY-4.0 |
| Moonshine | **Excluido** | Solo inglés en los pesos publicados |
| Uno o dos motores | **Uno** | int4 lo hace tan barato como el pequeño |
| Clase de carga | **ASR es autorregresiva** | Tiene caché KV; solo le amortiza el lote |

## Fuentes

- [Mejores modelos de STT open source 2026, con benchmarks (Northflank)](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)
- [Alternativas a Whisper en 2026 (Gladia)](https://www.gladia.io/blog/best-whisper-alternatives-2026)
- [Parakeet vs Whisper vs Nemotron: mejor STT local en 2026 (OpenWhispr)](https://openwhispr.com/blog/parakeet-vs-whisper-vs-nemotron)
- [Qwen3-ASR, repositorio oficial y licencia Apache-2.0](https://github.com/QwenLM/Qwen3-ASR)
- [Qwen3-ASR Technical Report (arXiv 2601.21337)](https://arxiv.org/html/2601.21337v1)
- [Qwen3-ASR-0.6B: requisitos de VRAM (Spheron)](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen3-ASR-0.6B)
- [faster-whisper vs whisper.cpp 2026 (Codersera)](https://codersera.com/blog/faster-whisper-vs-whisper-cpp-speech-to-text-2026/)
- [Tamaños de modelo Whisper 2026 (Spokenly)](https://spokenly.app/blog/whisper-model-sizes)
- [Moonshine: modelos ASR diminutos para el borde (arXiv 2509.02523)](https://arxiv.org/pdf/2509.02523)
- [Moonshine-base, tarjeta del modelo y licencia MIT](https://huggingface.co/UsefulSensors/moonshine-base)
