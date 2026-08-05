# Licencia del corpus de narración

El **corpus de narración de HearMe** —las anotaciones de prosodia aportadas,
revisadas y validadas por la comunidad— se publica bajo

## CC0 1.0 Universal (dedicación al dominio público)

Texto completo: https://creativecommons.org/publicdomain/zero/1.0/legalcode.es

Esto significa que cualquiera puede copiar, modificar, distribuir y utilizar el
corpus, incluso con fines comerciales, sin pedir permiso y sin atribución.

## Por qué CC0 y no una licencia con atribución o recíproca

Porque el corpus solo es infraestructura pública si sirve a todo el mundo.

Una licencia recíproca protegería al proyecto, pero convertiría el corpus en un
foso: quien quisiera usarlo tendría que aceptar nuestras condiciones. Una
licencia con atribución añadiría fricción legal a cada uso derivado, que es
justo lo que impide que estas cosas se adopten en la administración pública y en
la educación.

Si dentro de cinco años otro proyecto usa este corpus para hacer algo mejor que
HearMe, **habremos ganado**. El objetivo no es que gane HearMe: es que alguien
que no puede leer pueda escuchar.

Agradecemos la citación, pero no la exigimos.

## Qué contiene exactamente el corpus

- Anotaciones de prosodia: pausas, énfasis, ritmo, tono y roles narrativos,
  ancladas a tramos de texto.
- La huella SHA-256 del texto normalizado al que corresponden.
- Metadatos de procedencia: si la marca viene de una regla, de un modelo, de una
  corrección humana o de una lectura de referencia.
- Metadatos agregados de validación.

## Qué NO contiene

- **Las obras.** El corpus indexa por huella criptográfica; no almacena ni
  redistribuye los textos anotados. Permite anotar material con derechos sin
  vulnerarlos.
- **Grabaciones de voz.** Las lecturas de referencia aportan la prosodia
  extraída, no el audio. Publicar una grabación exige una cesión adicional y
  específica de quien narró.
- **Datos personales.** Las aportaciones se publican con identificadores
  seudónimos y estables, nunca con datos de contacto ni demográficos
  individuales.

## Excepciones

Las **lecturas de referencia** cuyo audio se haya cedido expresamente se rigen
por los términos de esa cesión, siempre más restrictivos que CC0 y **siempre
revocables**. Se distribuyen por separado y con su licencia indicada.

> **Todavía no existen esos términos**, y hasta que estén escritos y publicados
> **no se recoge ninguna grabación**. Decirlo aquí evita que alguien done su voz
> confiando en un marco que aún no se ha redactado. Ver
> [docs/LICENSING.md](docs/LICENSING.md#lo-que-todavía-no-está-cerrado).

Revocar el consentimiento elimina las marcas derivadas en la siguiente
publicación trimestral, y queda constancia en el registro de cambios.

## Garantías sobre esta licencia

Cambiar la licencia del corpus exige, según [GOVERNANCE.md](GOVERNANCE.md):

1. Una ADR pública con las alternativas y sus contras.
2. Consenso de quienes mantienen el proyecto.
3. Un periodo público de objeciones de treinta días como mínimo.

Además, cada publicación trimestral se deposita en al menos dos réplicas que no
controla el proyecto. Aunque alguien intentara cerrar el corpus en el futuro, lo
ya publicado seguiría siendo de dominio público de forma irrevocable.

## Cómo aportar

Al aportar al corpus, aceptas que tu aportación se publique bajo CC0. Si aportas
una lectura de referencia, se te pedirá además un consentimiento explícito,
informado y revocable, separado del alta.

Detalles del proceso: [CONTRIBUTING.md](CONTRIBUTING.md) y
[docs/COMMUNITY-NARRATION-TRAINING.md](docs/COMMUNITY-NARRATION-TRAINING.md).
