# HearMe — Análisis comparativo y decisiones técnicas

> Documento previo a la implementación. Cada elección está atada a un criterio medible
> y al hardware objetivo real, no a popularidad.

## 0. Hardware de referencia (perfil `laptop-cuda-4g`)

Medido en la máquina de desarrollo:

| Recurso | Valor |
|---|---|
| CPU | 16 cores x86_64 |
| RAM | 30 GB |
| GPU | NVIDIA T1200 Laptop — **4 GB VRAM**, CUDA 13.2 |
| Disco libre | 298 GB |
| SO | Ubuntu 26.04 |

**Consecuencia dura:** 4 GB de VRAM es el presupuesto que manda. Un modelo TTS de 2 GB +
un LLM de 4 GB + un traductor de 2.4 GB **no coexisten**. La arquitectura debe asumir
*residencia exclusiva*: un modelo pesado a la vez en GPU, el resto en CPU, con descarga
explícita entre etapas. Esto no es un detalle de tuning — define el diseño del pipeline.

---

## 1. Motor TTS — la decisión más importante

Criterio de peso, en orden: **naturalidad percibida > licencia > cobertura de idiomas >
velocidad > tamaño**. El usuario declaró calidad de voz como prioridad máxima.

| Motor | Params / tamaño | Licencia | Idiomas | Velocidad CPU (RTF*) | VRAM | Naturalidad |
|---|---|---|---|---|---|---|
| **Kokoro-82M** | 82 M / ~330 MB | **Apache-2.0** | 8 (en, es, fr, it, pt, hi, ja, zh) | ~0.03–0.08 | ~0.5 GB | **Muy alta** — top en arenas TTS pese al tamaño |
| **Piper** (VITS) | 5–30 M / 20–80 MB | **MIT** | **50+** | ~0.01–0.03 | n/a (ONNX CPU) | Media — inteligible y estable, prosodia plana |
| **Coqui XTTS-v2** | ~750 M / ~2 GB | **CPML — NO comercial** | 17 | ~1.5–4 (inusable) | ~2.5 GB | Alta + clonación de voz |
| Coqui VITS/Tacotron | 30–100 M | MPL-2.0 | varios | ~0.1 | ~1 GB | Media-baja, mantenimiento parado |

\* RTF = Real-Time Factor: segundos de cómputo por segundo de audio. Menor es mejor.

### Análisis

**Coqui XTTS-v2 queda descartado como motor por defecto**, por dos razones independientes
y cada una suficiente:

1. **Licencia CPML**, que prohíbe uso comercial. Meter eso en el camino por defecto de un
   proyecto que se anuncia "Open Source y gratuito" contamina el entregable y limita a
   quien lo adopte. Va como plugin *opt-in* con advertencia explícita de licencia.
2. **RTF > 1 en CPU** y 2.5 GB de VRAM. En la máquina objetivo, un libro de 8 horas de
   audio tardaría más de 8 horas. Inviable como default.

**Piper es el más rápido y el de mayor cobertura**, pero su prosodia es notoriamente plana:
no modula bien las pausas largas ni el énfasis, que es justo lo que separa "TTS" de
"audiolibro". Es el motor correcto para los 40+ idiomas que Kokoro no cubre, y para el
modo borrador rápido.

**Kokoro-82M es la elección por defecto.** Es el único punto del espacio que da calidad
cercana a comercial con licencia Apache-2.0 y RTF ~0.05 **en CPU pura** — con 16 cores,
un libro de 8 h se sintetiza en ~25 min sin tocar la GPU. Que quepa en CPU es
estratégico: **libera los 4 GB de VRAM para el traductor o el LLM**, que es exactamente
la restricción del punto 0.

### Decisión

> **Selección automática por idioma mediante matriz de capacidades**, no un motor fijo:
>
> - Idioma ∈ Kokoro → **Kokoro** (calidad)
> - Idioma ∉ Kokoro pero ∈ Piper → **Piper** (cobertura)
> - `quality=draft` solicitado → **Piper** (velocidad)
> - XTTS-v2 → solo si el usuario lo activa explícitamente (clonación de voz)
>
> Implementado como `TTSEngine` (Protocol) + `EngineSelector` que puntúa candidatos.
> Añadir un motor = registrar un plugin, sin tocar el núcleo.

---

## 2. Motor de traducción — NLLB vs MarianMT

| Motor | Tamaño | Licencia | Cobertura | Calidad es↔en | CPU int8 |
|---|---|---|---|---|---|
| **MarianMT** (Helsinki opus-mt) | ~75 M por par | **Apache-2.0** | ~1 400 pares | **Muy alta** en pares de alto recurso | Excelente |
| **NLLB-200-distilled-600M** | 600 M (~2.4 GB fp32) | **CC-BY-NC — NO comercial** | **200 idiomas** | Alta | Aceptable |
| NLLB-200-1.3B | 1.3 B | CC-BY-NC | 200 | Más alta | Lento |

### Análisis

Aquí el resultado es contraintuitivo respecto a la moda. NLLB es el modelo "grande y
moderno", pero:

- Su ventaja real está en **idiomas de bajo recurso** (suajili, yoruba, quechua). Para
  `en↔es`, `en↔fr`, `en↔de` — que serán >90 % del uso real de un lector de documentos —
  MarianMT iguala o supera en BLEU con **1/8 del tamaño**.
- **NLLB es CC-BY-NC.** Mismo problema de licencia que XTTS. No puede ser el default de
  un proyecto Apache-2.0.
- Un modelo Marian de 75 M cuantizado a int8 con CTranslate2 ocupa **~40 MB** y traduce
  en CPU a cientos de palabras/segundo. Mantiene la GPU libre.

### Decisión

> **MarianMT + CTranslate2 (int8) como motor por defecto**, con descarga perezosa del par
> concreto. **NLLB-600M como fallback automático** cuando el par solicitado no existe en
> Marian, marcado en la UI y en los metadatos con su licencia no comercial.
>
> Granularidad de traducción: **por párrafo**, nunca por documento completo — permite
> alineación 1:1 original↔traducción para la vista comparada y hace el trabajo reanudable.

---

## 3. Extracción de PDF

| Librería | Licencia | Layout / fuentes | TOC | Tablas | Velocidad |
|---|---|---|---|---|---|
| **pypdfium2** | **Apache-2.0 / BSD-3** | Básico | Sí | No | **Muy rápida** |
| **pdfminer.six** | **MIT** | **Completo** (tamaño, fuente, bbox) | No | Débil | Lenta |
| PyMuPDF (fitz) | **AGPL-3.0** | Completo | Sí | Sí | Muy rápida |
| pdfplumber | MIT | Bueno | No | **Muy buena** | Lenta |

### Análisis

PyMuPDF es técnicamente el mejor de la tabla — y es una trampa de licencia. **AGPL-3.0**
obliga a que cualquiera que exponga HearMe como servicio en red libere todo su
código. Para una librería que solo extrae texto, ese coste es desproporcionado.

La detección de capítulos necesita **tamaño y peso de fuente** (un H1 es texto grande y
en negrita) — eso lo da pdfminer.six, no pypdfium2.

### Decisión

> **pypdfium2** para render, conteo de páginas y TOC nativo (rápido, permisivo) +
> **pdfminer.six** para extracción con atributos tipográficos que alimentan el detector de
> encabezados. **PyMuPDF como extra opcional** (`pip install hearme[pymupdf]`) para
> quien acepte AGPL y quiera extracción de tablas superior. El núcleo nunca lo importa.

---

## 4. OCR y detección automática

`OCRmyPDF` (MPL-2.0, sobre Tesseract) — confirmado como pedido. La parte no trivial es
**cuándo dispararlo**. Heurística implementada:

```
cobertura = caracteres_extraídos / páginas
si cobertura < 100 car/pág  → PDF escaneado      → OCR completo
si 100 ≤ cobertura < 500    → capa parcial       → OCR con --redo-ocr
si cobertura ≥ 500          → capa de texto sana → sin OCR
```

Con muestreo sobre las primeras/últimas/medias páginas, no sobre el documento entero.

---

## 5. Persistencia

| Opción | Zero-config | Concurrencia | Multi-usuario |
|---|---|---|---|
| **SQLite (WAL)** | ✅ | Escritor único | ❌ |
| PostgreSQL | ❌ (requiere servidor) | ✅ | ✅ |

**Decisión:** **SQLAlchemy 2.0 async** como capa única; **SQLite+WAL por defecto**
(coherente con "desplegable sin fricción"), **PostgreSQL activable con una variable de
entorno** para el despliegue en Docker. Cero cambios de código entre ambos.

---

## 6. Cola de trabajos

Celery y ARQ **exigen Redis**. Imponer un servidor Redis a alguien que solo quiere
convertir un PDF en su portátil es un fallo de diseño de producto.

**Decisión:** cola **respaldada por la propia base de datos** (tabla `jobs` con
`SELECT ... FOR UPDATE SKIP LOCKED` / transacción inmediata en SQLite) + pool de workers
`asyncio` en proceso. Se recupera sola tras un reinicio, no añade dependencias, y el
`JobQueue` es un puerto — cambiar a Redis/ARQ en el perfil Docker es sustituir el adaptador.

---

## 7. Arquitectura de plugins y event bus

- **Contratos como `typing.Protocol`**, no herencia. Un plugin no importa el núcleo para
  cumplir la interfaz; solo respeta la forma. Evita el acoplamiento que mata a los
  sistemas de plugins.
- **Descubrimiento por `entry_points`** (`hearme.plugins`) + registro manual para
  los internos. Instalar un paquete de terceros lo activa, sin editar configuración.
- **Event bus asíncrono en proceso** con eventos tipados (`DocumentParsed`,
  `ChunkSynthesized`, `JobFailed`…). El transporte es un puerto → Redis Streams o NATS
  más adelante sin tocar emisores.
- **MCP**: los casos de uso de la capa `application` no conocen HTTP. FastAPI y el futuro
  servidor MCP son dos adaptadores del *mismo* caso de uso. Exponer MCP será escribir un
  adaptador, no reescribir lógica.

---

## 8. Resumen de decisiones

| Área | Elección | Razón dominante |
|---|---|---|
| TTS por defecto | **Kokoro-82M** | Calidad casi comercial, Apache-2.0, RTF 0.05 en CPU |
| TTS cobertura | **Piper** | 50+ idiomas, MIT, ultrarrápido |
| TTS clonación | XTTS-v2 *opt-in* | Licencia CPML no comercial |
| Traducción | **MarianMT + CTranslate2 int8** | Apache-2.0, mejor en pares de alto recurso |
| Traducción fallback | NLLB-600M | Cobertura 200 idiomas (CC-BY-NC, marcado) |
| PDF | **pypdfium2 + pdfminer.six** | Licencias permisivas + atributos de fuente |
| OCR | **OCRmyPDF** | Pedido; heurística por cobertura de caracteres |
| DB | **SQLite WAL → PostgreSQL** | Zero-config local, escalable en Docker |
| Colas | **Cola en DB + workers asyncio** | Sin dependencia de Redis |
| LLM estudio | **Ollama** (degradación elegante) | Local; con 4 GB VRAM → modelos 3B/4B q4 |
| Licencia proyecto | **Apache-2.0** | Compatible con todo el camino por defecto |

### Nota sobre el modo estudio y los 4 GB de VRAM

Ollama no está instalado en esta máquina. El modo estudio se implementa contra un puerto
`LLMProvider`; si no hay backend disponible, la función se marca *unavailable* y el resto
del pipeline sigue funcionando. Con 4 GB de VRAM, el modelo recomendado es de la clase
**3B–4B cuantizado a q4** (~2.5 GB); un 7B q4 (~4.5 GB) **no cabe** junto al contexto y
provocaría descarga a CPU.
