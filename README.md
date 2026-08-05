# HearMe

**Plataforma abierta para democratizar el acceso a lecturas en voz de alta calidad.**

Hay quien no puede leer un texto. No porque no sepa, sino porque la vista ya no
acompaña, porque las letras se le mueven en la página, porque nadie editó nunca
ese libro en audio, o porque el audiolibro cuesta lo que no tiene. HearMe existe
para que eso deje de ser una barrera.

[![Licencia](https://img.shields.io/badge/licencia-Apache--2.0-blue)](LICENSE)
[![Código de conducta](https://img.shields.io/badge/código%20de%20conducta-Contributor%20Covenant-ff69b4)](CODE_OF_CONDUCT.md)
[![Corpus](https://img.shields.io/badge/corpus-CC0-green)](docs/COMMUNITY-NARRATION-TRAINING.md)

---

## Misión

**Que cualquier persona pueda escuchar cualquier texto, con una voz que dé gusto
oír, sin pagar por ello y sin pedir permiso.**

No aspiramos a ser un producto. Aspiramos a ser infraestructura pública: algo que
una biblioteca municipal, una escuela o una asociación de personas ciegas puedan
levantar por su cuenta, adaptar a su idioma y a su comunidad, y mantener sin
depender de que una empresa siga interesada dentro de cinco años.

## Visión

Una biblioteca parlante abierta, sostenida por la comunidad, donde:

- **La calidad de la narración mejora con el uso.** Cada corrección de cada
  persona hace que el siguiente libro se lea un poco mejor, para todo el mundo.
- **El criterio narrativo es un bien común.** Cómo se lee un diálogo, dónde
  respira un párrafo: eso no debería ser propiedad de nadie. Se construye entre
  todos y se publica en abierto (CC0).
- **Ningún idioma es demasiado pequeño.** Si una comunidad quiere su lengua,
  tiene las herramientas para añadirla; no depende de que sea rentable.
- **La accesibilidad es el punto de partida, no una casilla.** El diseño arranca
  de quien tiene dislexia, de quien ve poco, de quien lleva escuchando seis horas
  y necesita que la voz no le canse.

## Para quién

| Quién | Qué gana |
| --- | --- |
| **Bibliotecas parlantes** | Convertir un fondo entero a audio con índice de capítulos, sin licencias por título |
| **Personas con dislexia** | Ritmo, pausas y énfasis ajustables; texto y voz sincronizados |
| **Personas mayores y con baja visión** | Escucha continua de larga duración, sin fatiga ni pantallas |
| **Estudiantes** | Apuntes, artículos y manuales convertidos en audio para estudiar en movimiento |
| **Docentes y logopedas** | Control fino de la narración para material didáctico adaptado |
| **Comunidades lingüísticas** | Añadir una lengua sin esperar a que interese a una empresa |

## Cómo suena distinto

La mayoría de los lectores automáticos suenan a robot no porque la voz sea mala,
sino porque **nadie los dirige**: leen todo igual, sin saber dónde respirar ni
qué palabra pesa.

HearMe separa las dos cosas. Un **director de narración** decide la
interpretación —pausas, énfasis, ritmo, tono— y la escribe en una *partitura*
neutra. El motor de voz solo pone el timbre. Así, cuando aparezca un motor mejor,
se cambia el motor y **el criterio acumulado por la comunidad se conserva
entero**.

Ese criterio es lo que la comunidad mejora, de forma continua y acumulativa:
👉 **[Community Narration Training](docs/COMMUNITY-NARRATION-TRAINING.md)**

## Tus datos no salen de aquí

Lo que alguien lee dice si le acaban de diagnosticar algo, qué cree o a quién
vota. Y quien más usa HearMe es quien más expuesto está.

Por eso el sistema **no promete no mirar: se organiza para no poder**. El
contenido va cifrado con una clave que solo tiene la persona; los metadatos se
degradan a propósito para que el tamaño de un archivo no lo identifique contra un
catálogo; la sesión privada guarda su clave solo en memoria y la olvida al
cerrar. Nada se envía a ningún tercero, porque no hay ningún tercero.

Y lo que se comparte con la comunidad no son datos, es **conocimiento**: reglas
como «tras un conector adversativo, la pausa sube un 30%», que no contienen
ninguna obra ni señalan a nadie.

👉 **[Privacidad, seguridad y confianza](docs/PRIVACY-SECURITY.md)** — modelo de
amenazas, cada decisión justificada y, con el mismo detalle, lo que **no** se
puede garantizar.

## Qué hace hoy

| Área | Estado actual |
| --- | --- |
| **Entrada** | PDF (con OCR si hace falta), EPUB, DOCX, ODT, Markdown, TXT, HTML, RTF, artículos web, RSS |
| **Modos** | lectura · audiolibro · estudio · traducción |
| **Voz** | Kokoro y Piper; 25+ idiomas, ampliable por plugin |
| **Salida** | `.m4b` con índice de capítulos, `.mp3`, `.epub`, `.md`, `.txt`, `.json` |
| **Interfaces** | Web · API REST · línea de comandos · carpeta vigilada |
| **Privacidad** | Todo local · almacén cifrado · sesión privada sin rastro · RGPD ejecutable |

Las decisiones técnicas —por qué Kokoro y no XTTS, por qué MarianMT y no NLLB—
están razonadas y medidas en [docs/ANALISIS-COMPARATIVO.md](docs/ANALISIS-COMPARATIVO.md).

## Instalación

Todo lo que sigue funciona igual en el servidor de una biblioteca, en un
contenedor gestionado o en una máquina de desarrollo. La ruta de datos y el
puerto se configuran; no hay nada codificado.

### Con contenedores (recomendado)

```bash
git clone https://github.com/resourceldg/hearme
cd hearme
cp .env.example .env      # revisa idioma de OCR, puerto y orígenes CORS
docker compose up -d
```

La API queda en `:8000` y su documentación interactiva en `/docs`.

La imagen trae parsers, voz con Piper y traducción. **Kokoro queda fuera por
defecto**: arrastra torch y multiplica por cinco el tamaño. Para incluirlo:

```bash
docker compose build --build-arg \
  HEARME_EXTRAS=documents,tts-piper,translate,tts-kokoro
```

Perfiles opcionales, que se activan solo si se piden:

```bash
docker compose --profile web up -d        # interfaz de lectura en :3000
docker compose --profile postgres up -d   # PostgreSQL en vez de SQLite
docker compose --profile ollama up -d     # modelo local para el modo estudio
```

> Si `docker compose` no responde, comprueba que tienes el plugin v2 instalado
> (paquete `docker-compose-v2` en Debian y Ubuntu) y que tu usuario pertenece al
> grupo `docker`.

### Como paquete

Requiere Python 3.12+ y `ffmpeg`. Para PDF escaneados, además `ocrmypdf` y
`tesseract-ocr` con los idiomas que se vayan a usar.

```bash
pip install "hearme[documents,tts-kokoro]"
hearme info          # capacidad del nodo, motores disponibles y avisos
hearme serve         # API y worker
```

Extras: `documents`, `tts-kokoro`, `tts-piper`, `translate`, `ocr`, `postgres`,
o `all` para todo lo que no arrastra licencias restrictivas.

### Configuración

Todas las variables llevan el prefijo `HEARME_`. Las esenciales:

| Variable | Para qué |
| --- | --- |
| `HEARME_DATA_DIR` | Dónde vive todo lo que produce el servicio |
| `HEARME_CORS_ORIGINS` | Orígenes que pueden llamar a la API desde el navegador |
| `HEARME_OCR_LANGUAGE` | Idiomas de OCR (`spa+eng`, `cat`…) |
| `HEARME_DATABASE_URL` | Vacío = SQLite; o una URL de PostgreSQL |

La lista completa está en [`.env.example`](.env.example).

## Uso rápido

```bash
hearme convert libro.epub -f m4b               # audiolibro con capítulos
hearme convert escaneado.pdf -f m4b -f md      # aplica OCR si lo necesita
hearme convert novela.epub -s novel            # registro narrativo
hearme convert paper.pdf --to es -f m4b        # traducir y narrar
hearme watch /ruta/vigilada -f m4b             # convertir lo que aparezca
hearme jobs                                    # historial
```

## Participar

Este proyecto necesita mucho más que gente que programe.

| Puedes aportar | Hace falta saber |
| --- | --- |
| Elegir cuál de dos lecturas suena mejor | Nada. Diez segundos |
| Corregir una pausa o un énfasis | Nada previo |
| Añadir o revisar un idioma | Hablarlo |
| Probar con lectores reales y contarlo | Escuchar y describir |
| Documentación, traducción de la interfaz | Escribir |
| Código, motores, formatos | Python o TypeScript |

Empieza por [CONTRIBUTING.md](CONTRIBUTING.md). Las decisiones se toman en
abierto según [GOVERNANCE.md](GOVERNANCE.md), y la convivencia se rige por el
[código de conducta](CODE_OF_CONDUCT.md).

## Hoja de ruta

Lo que viene y en qué orden: [ROADMAP.md](ROADMAP.md).

## Licencias

**Código y documentación** bajo [Apache-2.0](LICENSE): uso libre, incluido el
comercial, con concesión expresa de patentes. **El corpus de narración** bajo
CC0, para que sirva a cualquiera —incluidos proyectos que compitan con este—.
Si el corpus solo sirviera a HearMe no sería infraestructura pública, sería un
foso.

Contribuir no exige firmar ningún CLA y conservas tu copyright. El mapa
completo, con las preguntas que suelen quedar sin responder —contribuciones
entrantes, uso del nombre, modelos con cláusula no comercial— está en
**[docs/LICENSING.md](docs/LICENSING.md)**.

## Apoyar

El proyecto **no recauda ni gestiona dinero**. Quien aporta —incluido quien lo
mantiene— puede publicar su enlace de donación junto a su crédito, y el apoyo va
directamente de una persona a otra, con medios libres.

Nada de lo que produce este proyecto está detrás de un pago: **donar no da
prioridad ni influencia, y no donar no quita nada.** Reglas completas en
[GOVERNANCE.md § Dinero](GOVERNANCE.md#dinero).

## Documentación

| Documento | Contenido |
| --- | --- |
| [Community Narration Training](docs/COMMUNITY-NARRATION-TRAINING.md) | Cómo mejora la narración con la comunidad |
| [Privacidad, seguridad y confianza](docs/PRIVACY-SECURITY.md) | Modelo de amenazas y decisiones de diseño |
| [Assistive Technology First](docs/ASSISTIVE-TECHNOLOGY.md) | Lectores de pantalla, teclado y validación con personas |
| [Sistema de diseño](docs/DESIGN-SYSTEM.md) | Experiencia adaptativa y accesibilidad verificada |
| [Licencias](docs/LICENSING.md) | Qué está licenciado cómo, y qué no |
| [Análisis comparativo](docs/ANALISIS-COMPARATIVO.md) | Por qué cada dependencia y no otra |
| [Análisis de inferencia](docs/ANALISIS-INFERENCIA.md) | Cómo se planifica la ejecución |
| [Análisis de ASR](docs/ANALISIS-ASR.md) | Reconocimiento de voz y alineación |

Y en la raíz: [CONTRIBUTING](CONTRIBUTING.md) · [GOVERNANCE](GOVERNANCE.md) ·
[CODE_OF_CONDUCT](CODE_OF_CONDUCT.md) · [ROADMAP](ROADMAP.md)
