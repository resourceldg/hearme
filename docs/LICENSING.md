# Licencias

Mapa completo de qué está licenciado cómo, y de las preguntas que suelen quedar
sin responder. Es la fuente canónica: si algo se contradice con otro documento,
manda este.

---

## Resumen

| Qué | Licencia | Dónde |
| --- | --- | --- |
| Código fuente | Apache-2.0 | [`LICENSE`](../LICENSE) |
| Documentación | Apache-2.0 | este repositorio |
| Corpus de narración | CC0 1.0 (dominio público) | [`LICENSE-CORPUS.md`](../LICENSE-CORPUS.md) |
| Benchmark de narración | CC0 1.0 | [`LICENSE-CORPUS.md`](../LICENSE-CORPUS.md) |
| Nombre y logotipo | No licenciados | [§ Nombre](#el-nombre-no-va-en-la-licencia) |
| Lecturas de referencia (audio) | Cesión específica, revocable | [§ Pendiente](#lo-que-todavía-no-está-cerrado) |
| Modelos opcionales de terceros | Las suyas, algunas no comerciales | [`NOTICE`](../NOTICE) |

Dos licencias distintas y no una por descuido: el código permite uso comercial
con atribución y concesión de patentes; el corpus renuncia a todo para que sirva
a cualquiera, **incluidos proyectos que compitan con este**. Un corpus que solo
sirviera a HearMe no sería un bien común, sería un foso.

## Si contribuyes código o documentación

Tu aportación queda bajo **Apache-2.0**, igual que el resto. No hace falta que
firmes nada: es la propia licencia la que lo dice, en su cláusula 5.

> «Salvo que declares expresamente lo contrario, toda contribución que envíes
> intencionadamente para su inclusión en la Obra quedará sujeta a los términos y
> condiciones de esta Licencia.»

**No hay CLA.** No se pide ceder la titularidad ni firmar un acuerdo aparte.
Conservas el copyright de lo que escribes; el proyecto solo obtiene la licencia
para usarlo. Es deliberado: un CLA permitiría a quien mantiene relicenciar el
trabajo ajeno más adelante, y eso es justo el tipo de puerta trasera que un
proyecto de infraestructura pública no debería dejar abierta.

## Si contribuyes al corpus

Las anotaciones de prosodia se publican bajo **CC0**: renuncias a los derechos
que pudieras tener sobre ellas para que pasen al dominio público.

Es un paso más fuerte que Apache-2.0 y por eso se pide explícitamente al
aportar, no por omisión. Detalles y garantías en
[`LICENSE-CORPUS.md`](../LICENSE-CORPUS.md).

## Las donaciones no dan ningún derecho

Este proyecto **no recauda ni gestiona dinero**. Las donaciones, cuando las hay,
van directamente de una persona a otra y el proyecto no interviene (ver
[GOVERNANCE.md § Dinero](../GOVERNANCE.md#dinero)).

Aun así conviene dejarlo escrito sin ambigüedad:

- Donar **no otorga** licencia, propiedad ni derecho alguno sobre el software,
  el corpus ni el nombre.
- Donar **no crea** relación contractual, laboral ni de encargo con nadie.
- Donar **no da** prioridad, voto, influencia sobre la hoja de ruta ni acceso
  anticipado a nada.
- No donar **no quita** absolutamente nada: todo lo que produce este proyecto
  está disponible para todo el mundo en los mismos términos.
- Una donación a una persona concreta es **suya**, no del proyecto, y el
  proyecto no responde de ella ni lleva su cuenta.

Nada de lo que produce este proyecto está ni estará detrás de un pago: ni el
software, ni el corpus, ni la atención a una incidencia.

## El nombre no va en la licencia

Apache-2.0 concede derechos sobre el código pero **excluye expresamente las
marcas** (cláusula 6). El nombre «HearMe» y su identidad visual no se licencian
con el software.

Qué significa en la práctica:

- **Puedes** hacer un fork, modificarlo y distribuirlo, incluso comercialmente.
  Eso es lo que garantiza la licencia y nadie va a discutirlo.
- **Puedes** decir que tu proyecto «está basado en HearMe» o «es compatible con
  HearMe». Describir un hecho no es usar una marca.
- **No llames HearMe a tu fork**, porque quien lo instale creerá que es este
  proyecto y sus problemas volverán aquí. Ponle otro nombre y quédate el código.

No hay registro de marca ni intención de perseguir a nadie. Es una petición de
cortesía entre proyectos libres, no una amenaza legal.

## Sin garantía

Tanto Apache-2.0 como CC0 se distribuyen **sin garantía de ningún tipo**. Este
software convierte documentos y genera voz; no es un producto sanitario ni
asistencial certificado, y no sustituye a los apoyos que una persona necesite.

Quien lo despliegue en una institución es responsable de comprobar que sirve
para su caso, incluidas las obligaciones de accesibilidad que le apliquen.

## Componentes de terceros

El núcleo solo admite dependencias con licencia permisiva (MIT, Apache-2.0,
BSD). Nada de GPL ni AGPL en el camino de ejecución.

No es purismo: una biblioteca pública tiene que poder desplegar esto sin pasar
por su departamento jurídico.

Algunos modelos opcionales llevan licencias no comerciales (XTTS-v2 bajo CPML,
NLLB bajo CC-BY-NC) y PyMuPDF es AGPL. **No se instalan ni se usan** salvo
activación consciente con `HEARME_ALLOW_NON_COMMERCIAL_MODELS=true`. El detalle
y el razonamiento por dependencia están en [`NOTICE`](../NOTICE) y en
[ANALISIS-COMPARATIVO.md](ANALISIS-COMPARATIVO.md).

## Lo que todavía no está cerrado

Se enumera porque un mapa de licencias con huecos sin señalar es peor que no
tenerlo:

- **Cesión de las lecturas de referencia.** Cuando alguien narre un pasaje, la
  prosodia extraída irá a CC0, pero el audio necesita una cesión propia,
  revocable y separada del alta. **Esos términos no están escritos todavía**, y
  hasta que lo estén no se recogerá ninguna grabación.
- **Titular del copyright.** Hoy figura «HearMe contributors» en el
  [`NOTICE`](../NOTICE). Si el proyecto llega a constituir una entidad, habrá
  que decidir si la titularidad se traslada —y esa decisión exige una ADR y
  periodo público de objeciones, porque afecta a todo el mundo que ha aportado.
- **Traducción de estos documentos.** Solo existen en español, lo que limita
  quién puede revisarlos de verdad.
