# Motor de optimización de inferencia — revisión del estado del arte (agosto 2026)

> Revisión previa a escribir código, verificada con fuentes de 2026 y no con memoria.
> Decisiones al final de cada sección.

## 0. La objeción que hay que resolver antes de elegir nada

El conjunto de técnicas del encargo —*continuous batching, paged attention, prefix
caching, speculative decoding, KV cache compression*— **no es genérico de "IA": es
específico de transformers autorregresivos de decodificación**. Todas existen para
resolver un problema concreto: generar el token N+1 requiere los N anteriores, y la
caché KV crece sin parar.

La ruta caliente de HearMe **no es un LLM**:

| Carga | Modelo | ¿Autorregresivo? | ¿Le aplican esas técnicas? |
|---|---|---|---|
| **TTS** (Kokoro, Piper) | 82 M / 20 M | **No** (VITS/flow, una pasada) | **No.** No hay caché KV que paginar |
| **Traducción** (Marian) | 75 M seq2seq | Sí, pero secuencias de ~50 tokens | Solo *batching*. Lo demás no amortiza |
| **Modo estudio** (LLM) | 3-4 B | **Sí** | **Sí, todas** |
| **Clonación de voz** | 0.5-1.7 B | Parcial (Qwen3-TTS sí) | Batching, cuantización, KV cache |

Aplicar *paged attention* a Kokoro no es una optimización: es un sinsentido. Un
subsistema que lo intentara sería complejidad pura sin ganancia.

**Consecuencia de diseño:** el subsistema no impone un conjunto fijo de técnicas.
Cada backend **declara sus capacidades** y el planificador aplica solo la
intersección de lo que la técnica requiere y lo que el backend ofrece. Esa
negociación de capacidades *es* el mecanismo que permite añadir técnicas futuras
sin tocar el resto — que era el requisito real del encargo.

---

## 1. Motores de inferencia LLM — comparativa 2026

| Motor | Licencia | Fuerte en | VRAM mínima realista | Estado ago-2026 |
|---|---|---|---|---|
| **llama.cpp** | MIT | CPU y GPU pequeñas, GGUF, offload por capas | **~0** (corre en CPU pura) | Muy activo |
| **Ollama** | MIT | Envoltorio de llama.cpp, gestión de modelos | ~0 | Muy activo |
| **vLLM** | Apache-2.0 | Throughput por lotes, PagedAttention | **~6-8 GB** útiles | Muy activo |
| **SGLang** | Apache-2.0 | RadixAttention (prefix caching), agentes, RAG | **~6-8 GB** útiles | Muy activo |
| **TensorRT-LLM** | Apache-2.0 | Máximo throughput absoluto | 8 GB+ | Activo, NVIDIA-only |
| **MLX** | MIT | Apple Silicon, memoria unificada | n/a (unificada) | Activo |
| **TGI** | Apache-2.0 | — | — | **Mantenimiento desde 2026-03-21** ❌ |

### Datos medidos que importan

- **SGLang supera a vLLM ~29 %** en throughput agregado en H100, y hasta **6×** en
  escenarios RAG gracias a RadixAttention sobre prefijos compartidos. En modelos
  pequeños (Llama 3.1 8B) la ventaja es ~16 200 vs ~12 500 tok/s.
- **vLLM es 15-20 % más rápido en lotes grandes**; SGLang gana en latencia
  percibida para petición única.
- **llama.cpp escala linealmente con núcleos** (65-75 % de eficiencia): 16 núcleos
  ≈ 3× el throughput de 4.
- **Coste fijo antes de cargar pesos:** vLLM/SGLang/TensorRT reservan **500 MB-2 GB**
  solo de contexto CUDA, asignador y runtime.
- **En 4 GB de VRAM** entran modelos de **3-4 B en Q4_K_M con ~4k de contexto**.
  Un 7B Q4_K_M son ~4 GB solo de pesos, más 1-2 GB de caché KV: **no cabe**.

### Lectura para nuestro hardware (T1200, 4 GB)

vLLM y SGLang son motores de centro de datos. Con 4 GB, entre 0,5-2 GB se van en
overhead del runtime **antes** de cargar un solo peso — quedan ~2 GB para un modelo
que ya de por sí necesita 2,5 GB. **No es que rindan peor: es que no arrancan.**

Esto no los descarta del proyecto, los descarta *de esta máquina*. Y es exactamente
lo que el subsistema debe descubrir solo, no lo que debe llevar cableado.

### Decisión

> **No hay un motor elegido. Hay un registro de motores con un puntuador.**
>
> - `llama.cpp` (MIT) — **elegido en esta máquina**: 16 núcleos con escalado lineal,
>   sin suelo de VRAM, GGUF Q4_K_M cabe en 4 GB con offload parcial.
> - `Ollama` (MIT) — preferido si ya está corriendo: cero fricción de gestión.
> - `vLLM` / `SGLang` (Apache-2.0) — registrados, se **autodescartan** por VRAM
>   insuficiente. Se activan solos en un servidor con GPU grande.
> - `MLX` (MIT) — se activa solo en Apple Silicon.
> - `TensorRT-LLM` — **no se incluye**: exige compilar el modelo a un formato
>   propietario por GPU. Coste de complejidad desproporcionado para un proyecto
>   local, y ata al usuario a NVIDIA.
> - `TGI` — **no se incluye**: en mantenimiento desde marzo de 2026. Integrar un
>   proyecto que sus propios autores desaconsejan sería deuda técnica de día cero.

---

## 2. Técnicas de optimización — cuáles aplican y a qué

| Técnica | Qué resuelve | Aplica a | Ganancia típica |
|---|---|---|---|
| **Cuantización Q4_K_M / AWQ** | Tamaño en memoria | LLM, TTS grande | 3-4× memoria, ~2× velocidad |
| **Continuous batching** | GPU ociosa entre peticiones | LLM multi-petición | 2-4× throughput |
| **Prefix caching / RadixAttention** | Recomputar prompts compartidos | LLM con prompt común | Hasta 6× en RAG |
| **Paged attention** | Fragmentación de la caché KV | LLM | ~2× peticiones concurrentes |
| **KV cache compression** | Caché que crece sin fin | LLM contexto largo | 2-8× contexto |
| **Speculative decoding** | Latencia por token | LLM con modelo borrador | 2-3× si aceptación alta |
| **Dynamic speculative decoding** | El anterior desperdicia si falla | LLM | Ajusta γ según tasa de aceptación |
| **Flash attention** | Ancho de banda de memoria | LLM, transformers | 2-4× en secuencias largas |
| **Sparse attention** | O(n²) de la atención | Contexto muy largo | Solo rentable >8k tokens |
| **Batching de párrafos** | — | **TTS y traducción** | **2-3× en nuestra ruta caliente** |

### Lo que importa de verdad aquí

En el modo estudio (único consumidor real de LLM) el patrón es: **un prompt de
sistema fijo + un capítulo distinto cada vez**. Eso hace que **prefix caching sea la
técnica de mayor retorno** de toda la lista para este proyecto — el prompt de
sistema se recomputa en cada capítulo si no está cacheado.

Y la técnica con mejor relación ganancia/esfuerzo del proyecto entero **no está en
la lista del encargo**: es el **batching de párrafos en TTS y traducción**, porque
ahí es donde se va el 95 % del tiempo de cómputo real.

### Decisión

> Las técnicas se modelan como **`Technique`** con `requires` (capacidades que
> exige) y `applies_to` (clases de carga). El planificador las activa por
> intersección con lo que el backend declara. Añadir una técnica de 2027 = registrar
> un objeto más; ni el pipeline ni los backends cambian.

### Corolario que apareció al implementarlo

El batching se filtraba por "¿hay peticiones concurrentes?", y eso lo desactivaba
justo donde más rinde: **un capítulo ya llega troceado en párrafos independientes**,
así que hay lote que formar aunque no haya ni una segunda petición. La condición
correcta no es la concurrencia sino si la carga llega troceada
(`WorkloadClass.batches_offline`), y es propiedad de la carga, no de la técnica.

---

## 3. Métricas y adaptación

Se miden por petición: **TTFT**, **tokens/s**, **RTF** (para audio), **CPU %**,
**VRAM/RAM**, y **calidad percibida**.

La "calidad percibida" no se puede medir con un número objetivo sin un evaluador
humano. Fingir lo contrario sería el fallo de diseño más fácil de cometer aquí.
Se modela como una señal compuesta y **explícitamente declarada como estimación**:

1. **Calidad declarada del backend** (naturalidad del motor, bits de cuantización).
2. **Penalización por degradación** cuando el tuner baja la calidad para ganar
   velocidad.
3. **Realimentación del usuario** (pulgar arriba/abajo en la UI), que es la única
   señal de verdad y pesa más que las anteriores según se acumula.

### El tuner

Bucle de control simple sobre un objetivo declarado (`latency` | `balanced` |
`quality`). Sube o baja un nivel discreto de calidad según si se cumple el
presupuesto de latencia. Se eligió **histéresis con niveles discretos** en vez de un
controlador continuo por una razón práctica: un PID sobre parámetros de inferencia
oscila de forma audible en TTS, y una voz que cambia de timbre a mitad de capítulo
es peor que una voz uniformemente algo peor.

---

## 4. Resumen de decisiones

| Punto | Decisión | Razón dominante |
|---|---|---|
| Motor LLM en esta máquina | **llama.cpp** | Sin suelo de VRAM; escala lineal en 16 núcleos |
| Motor si hay GPU grande | **SGLang** > vLLM | +29 % throughput y RadixAttention |
| Descubrimiento | **Benchmark + puntuador** | vLLM/SGLang se autodescartan por VRAM |
| TensorRT-LLM | **Excluido** | Compilación por GPU; ata a NVIDIA |
| TGI | **Excluido** | En mantenimiento desde 2026-03 |
| Técnicas | **Negociación de capacidades** | Permite añadir sin tocar el núcleo |
| Prioridad real | **Prefix caching + batching TTS** | Donde está el tiempo de verdad |
| Calidad percibida | **Estimación + feedback humano** | No se puede medir objetivamente |
| Alcance del registro | **También TTS y traducción** | Ahí está el 95 % del cómputo (§2) |
| Quién elige motor TTS | **`tts.selector`, no el planificador** | Dos criterios distintos = contradicción |
| Peso de la CPU al puntuar | **Amortiguado si hay GPU** | Sin eso llama.cpp ganaba en una H100 |
| Qué gira el tuner | **Memoria en vuelo, no el timbre** | Degradar suele responder a un OOM |
| Degradar cambiando de motor | **Descartado** | La voz no puede cambiar sola |

---

### Qué gira exactamente el bucle de adaptación

El pipeline mide (RTF real por fragmento), la medición alimenta a la vez al
histórico —que corrige la puntuación de motores entre ejecuciones— y al tuner, y
el nivel del tuner entra en el siguiente plan. El bucle está cerrado.

La pregunta difícil era **qué perilla girar**, porque ningún motor TTS expone hoy
un parámetro de fidelidad: `KokoroEngine` y `PiperEngine` solo aceptan voz y
velocidad. Había dos salidas y la primera es una trampa:

1. **Cambiar de motor al degradar** (Kokoro → Piper). Se descarta: el nivel del
   tuner acabaría decidiendo con qué voz se narra un libro según lo cargada que
   estuviera la máquina el día anterior. Para una herramienta de accesibilidad,
   que la voz cambie sola es un defecto, no una optimización.
2. **Degradar la memoria en vuelo**, que es lo elegido: cada nivel parte por dos
   el lote y el paralelismo.

La segunda es además la respuesta *correcta al motivo real*, porque el tuner sube
de nivel sobre todo tras un fallo, y un fallo de síntesis es casi siempre falta de
memoria. Sobre 16 núcleos: lote 32/hilos 8 → 16/4 → 8/2 → 4/1. Y no altera ni un
decibelio de cómo suena la voz.

Queda una limitación honesta: en cargas *feedforward* no hay ninguna técnica con
`quality_delta` negativo que el nivel pueda habilitar, así que ahí el nivel solo
mueve memoria. Donde sí hará más es en clonación de voz y modo estudio, que tienen
caché KV que cuantizar.

Por el mismo principio, un perfil solo declara las capacidades que su adaptador
**ejerce de verdad**: Marian corre en fp32 y las voces `medium` de Piper no están
cuantizadas, así que ninguno declara int8 aunque el motor subyacente pudiera.

---

## 5. Corrección a una decisión anterior: clonación de voz

El [análisis original](ANALISIS-COMPARATIVO.md) concluyó que la clonación de voz
obligaba a XTTS-v2 y por tanto a una **licencia CPML no comercial**, relegándola a
*opt-in*. **Esa conclusión ha quedado obsoleta** y la corrijo:

| Modelo | Licencia | Referencia necesaria | VRAM | Veredicto |
|---|---|---|---|---|
| **Qwen3-TTS** (Alibaba, 11-2025 → 01-2026) | **Apache-2.0** | **3 s** | **4 GB** | **Elegido** |
| **Chatterbox** (Resemble AI) | **MIT** | ~5 s | ~5 GB | Alternativa de calidad |
| **Chatterbox-Turbo** (350 M) | MIT | ~5 s | baja | Alternativa rápida |
| OpenVoice v2 | MIT | ~10 s | baja | Solo transferencia de estilo |
| F5-TTS | **CC-BY-NC** (pesos) | ~10 s | media | Descartado |
| XTTS-v2 | **CPML** | ~6 s | 2,5 GB | Descartado |

**Qwen3-TTS es la elección**, y por motivos que importan especialmente al enfoque
filantrópico del proyecto:

1. **Apache-2.0 puro.** La clonación deja de ser una función de segunda con
   asterisco legal y pasa al camino principal.
2. **3 segundos de referencia.** Para una persona ciega, grabar 3 s frente a 10 s
   no es un detalle de comodidad: es la diferencia entre una función usable y una
   barrera. Es el requisito de enrolamiento más bajo del mercado abierto.
3. **Cabe en 4 GB de VRAM**, el hardware objetivo.
4. 10 idiomas y *voice design* por descripción textual, útil para quien no quiera
   usar su propia voz pero sí elegir una que le represente.

**Chatterbox (MIT)** queda como alternativa cuando hay más VRAM y se busca máxima
naturalidad o control emocional.

### Salvaguardas (parte del diseño, no un añadido)

Un clonador de voz es, sin más, un motor de suplantación. Para un proyecto de
accesibilidad la respuesta correcta no es no construirlo, sino construirlo con
procedencia:

- **Frase de consentimiento hablada** obligatoria en el enrolamiento: la muestra
  debe contener una frase concreta, no vale un audio cualquiera de un tercero.
- **Marca de procedencia** en los metadatos de todo audio generado con voz clonada.
- **Perfiles locales**, nunca subidos a ningún servicio.

## Fuentes

- [Guía completa de herramientas de inferencia local, julio 2026 (DEV)](https://dev.to/sreeraj-sreenivasan/the-complete-guide-to-local-llm-inference-tools-in-july-2026-llamacpp-ollama-vllm-sglang-and-4mh1)
- [Mejores motores de inferencia LLM 2026: vLLM vs SGLang vs TGI vs llama.cpp (DeployBase)](https://deploybase.ai/articles/best-llm-inference-engine)
- [Comparativa de motores de inferencia local 2026 (Sesame Disk)](https://sesamedisk.com/local-ai-inference-engines-2026-comparison/)
- [vLLM, Ollama, LM Studio, llama.cpp: elegir motor en 2026 (BIZON)](https://bizon-tech.com/blog/best-llm-inference-engines)
- [Requisitos de VRAM de llama.cpp, 2026 (LocalLLM.in)](https://localllm.in/blog/llamacpp-vram-requirements-for-local-llms)
- [VRAM mínima para LLM locales en 2026 por niveles de GPU](https://www.kunalganglani.com/blog/running-local-llms-2026-hardware-setup-guide)
- [Qwen3-TTS: guía completa 2026 de clonación de voz open source (DEV)](https://dev.to/czmilo/qwen3-tts-the-complete-2026-guide-to-open-source-voice-cloning-and-ai-speech-generation-1in6)
- [Chatterbox TTS: MIT, 2026 (Local AI Master)](https://localaimaster.com/blog/chatterbox-tts-setup-guide)
- [Clonación de voz local: 5 modelos abiertos probados, 2026](https://localaimaster.com/blog/local-ai-voice-clone)
- [Mejor TTS open source 2026 (FindSkill)](https://findskill.ai/blog/best-open-source-tts-2026/)
