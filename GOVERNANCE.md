# Gobernanza de HearMe

Este documento describe quién decide qué, cómo se resuelven los desacuerdos y
qué garantías tiene la comunidad de que el proyecto no se le escape de las manos.

Está escrito para la fase en la que el proyecto está de verdad —joven y pequeño—
y no para la que nos gustaría aparentar. Incluye el compromiso explícito de
revisarlo cuando eso cambie.

## Principios

Estos cuatro no se negocian en una discusión de diseño. Cualquier decisión que
choque con ellos está mal, por buenos que sean sus argumentos técnicos.

1. **Las personas usuarias primero, y en concreto las que tienen más difícil el
   acceso.** Cuando haya que elegir entre una función atractiva y una mejora de
   accesibilidad, gana la accesibilidad. Y no basta con cumplir la norma: hay que
   funcionar con las tecnologías de asistencia que la gente **ya usa**, y
   comprobarlo con ella. Nada sobre nosotros sin nosotros.
2. **El bien común por delante del proyecto.** El corpus se publica en CC0 para
   que sirva a cualquiera, incluidos proyectos rivales. Un bien común que solo
   sirve a quien lo creó no es un bien común.
3. **Sin capturas.** Ninguna organización, financiadora o no, obtiene control
   sobre la dirección técnica a cambio de dinero, cómputo o visibilidad.
4. **En abierto por defecto.** Las decisiones se toman en espacios públicos y
   archivados. Lo que se habla en privado se resume en público.

## Roles

| Rol | Qué puede hacer | Cómo se llega |
| --- | --- | --- |
| **Quien contribuye** | Proponer cambios, abrir incidencias, aportar al corpus, revisar | Aportando |
| **Quien revisa** | Aprobar cambios en su área; su voto pesa en decisiones técnicas | Invitación tras un historial sostenido de aportaciones de calidad |
| **Quien mantiene** | Fusionar, publicar versiones, administrar la infraestructura | Consenso de quienes mantienen, tras un periodo como persona revisora |
| **Consejo de accesibilidad** | Veto sobre cambios que empeoren el acceso | Invitación a personas usuarias y profesionales del ámbito |

### El consejo de accesibilidad

Es la pieza menos habitual y la más importante.

Un proyecto de accesibilidad dirigido solo por quienes escriben código deriva,
sin mala intención, hacia lo que a quienes escriben código les parece
interesante. El consejo lo integran personas que **usan** esto —con dislexia,
con baja visión, con dificultades de lectura, con tecnología de asistencia— y
profesionales que trabajan con ellas.

Tiene **veto sobre cambios que degraden el acceso**. No es un comité asesor: su
rechazo detiene el cambio. La composición se publica y se renueva.

**Nada sobre nosotros sin nosotros.** El lema viene del movimiento por los
derechos de las personas con discapacidad y está recogido en la Convención de la
ONU. Aquí obliga a tres cosas:

1. **Mayoría de personas usuarias.** Más de la mitad del consejo son personas
   que usan tecnología de asistencia a diario, no profesionales que trabajan
   «para» ellas. Ambas voces hacen falta; solo una de las dos puede ser mayoría.
2. **Poder real, no consulta.** El veto detiene el cambio. Un consejo que solo
   opina es un adorno.
3. **El recurso contra un veto se gana con evidencia de uso real**, nunca con
   argumentos técnicos.

### Participar no cuesta ni se paga

Nadie tiene que pagar para participar, y el proyecto no paga a nadie por
hacerlo: no gestiona dinero (ver [Dinero](#dinero)). Lo que sí garantiza es que
**aportar no salga gratis para quien aporta**: crédito, voz en las decisiones o
prioridad para lo que a esa persona le estorba. Elige quien aporta, y el menú
está en [docs/ASSISTIVE-TECHNOLOGY.md](docs/ASSISTIVE-TECHNOLOGY.md).

Dos límites que sí son firmes:

- **El proyecto no puede depender de trabajo no correspondido.** Si nadie
  aparece, se avanza con lo automatizable y se publica qué quedó sin validar.
- **Nadie aporta gratis mientras otra persona cobra por lo mismo.**

Mientras el consejo no exista formalmente, quienes mantienen asumen el
compromiso de buscar activamente ese contraste antes de tocar nada que afecte a
la experiencia de escucha, y de **decir en público cuando no han podido**. Hoy
no se ha podido: ninguna combinación de lector de pantalla ha sido validada por
una persona usuaria, y así consta en
[docs/ASSISTIVE-TECHNOLOGY.md](docs/ASSISTIVE-TECHNOLOGY.md).

## Cómo se decide

**Consenso primero.** Casi todo se resuelve discutiendo en una incidencia
pública. Si nadie con capacidad de revisión se opone en un plazo razonable, sale
adelante.

**Votación si el consenso falla.** Mayoría simple de quienes mantienen, con al
menos tres participando. Los empates se resuelven a favor de no cambiar nada:
quien propone tiene la carga de convencer.

**ADR para lo caro de revertir.** Estas decisiones necesitan un documento en
`docs/adr/` con las alternativas consideradas y sus contras:

- El formato de la partitura (`hearme.narration.score`)
- Las reglas de validación del corpus y sus umbrales
- La licencia del corpus o del código
- Añadir dependencias al núcleo
- Cualquier cosa que rompa compatibilidad

**Veto de accesibilidad.** Se ejerce en público y con motivo escrito. Se puede
recurrir aportando pruebas con personas usuarias reales; no con argumentos.

## El corpus

El corpus de narración tiene garantías propias, porque es donde se acumula el
trabajo de mucha gente que no controla el proyecto:

- **Siempre CC0.** Cambiar esto exige ADR, consenso de quienes mantienen y un
  periodo público de objeciones de treinta días como mínimo.
- **Réplicas independientes.** Cada publicación trimestral se deposita en al
  menos dos sitios que no controla el proyecto. Si esto desaparece mañana, el
  corpus sobrevive.
- **Derecho de retirada.** Quien aportó una lectura de referencia puede revocar
  su consentimiento; las marcas derivadas se eliminan en la siguiente
  publicación y queda constancia en el registro de cambios.
- **Sin exclusivas.** Nadie obtiene acceso anticipado o privilegiado, ni por
  financiar el proyecto.

## Dinero

**El proyecto no recauda ni gestiona dinero.** No hay caja común, ni cuentas que
llevar, ni nadie administrando pagos. Es deliberado: montar eso exigiría una
carga que un proyecto sostenido por tiempo donado no puede asumir, y acabaría
comiéndose el tiempo que debería ir a que esto funcione.

**Donaciones personales, de persona a persona.** Quien aporte —incluido quien
mantiene el proyecto— puede publicar su enlace de donación junto a su crédito.
Quien quiera apoyar a alguien lo hace directamente con esa persona, en privado.
El proyecto no intermedia ni se entera.

Se recomiendan medios libres (Liberapay, Open Collective o una transferencia
directa) por la misma coherencia que se aplica a las dependencias del código: un
proyecto que rechaza atarse a software privativo no debería empujar a nadie
hacia él para cobrar.

Reglas que sí son firmes:

- **Nada de lo que produce este proyecto está detrás de un pago.** Ni el
  software, ni el corpus, ni la atención a una incidencia. Donar no da prioridad
  ni influencia; no donar no quita nada. Las consecuencias legales están en
  [docs/LICENSING.md](docs/LICENSING.md#las-donaciones-no-dan-ningún-derecho).
- **La misma regla para todo el mundo**, sin trato distinto según el rol.
- Si algún día el proyecto recibiera fondos como tal —una subvención, por
  ejemplo—, se publican las cuentas y **la validación de accesibilidad cobra
  antes que el desarrollo**. Se fija ahora, sin dinero sobre la mesa, porque
  después siempre hay una urgencia técnica que parece más apremiante.
- La financiación **nunca compra dirección técnica**, ni se acepta condicionada
  a restringir el corpus o a añadir telemetría.

## Conflictos

Los técnicos se resuelven por el procedimiento de arriba. Los de conducta, por
el [código de conducta](CODE_OF_CONDUCT.md), que tiene su propia vía y sus
propios responsables.

Si alguien que mantiene el proyecto incumple estos principios de forma
sostenida, el resto puede retirarle el rol por mayoría. Es un mecanismo
desagradable y por eso conviene tenerlo escrito antes de necesitarlo.

## Si el proyecto se abandona

Un proyecto de infraestructura pública debe decir qué pasa si se muere.

Si pasan doce meses sin actividad de mantenimiento, cualquier persona con
historial de contribución puede reclamar el rol de mantenimiento anunciándolo
públicamente y esperando treinta días. El corpus, al estar en CC0 y replicado,
sigue disponible pase lo que pase.

## Revisión

Este documento se revisa cuando el proyecto pase de tres personas manteniéndolo
o de cien aportando al corpus, y en todo caso una vez al año. Los cambios siguen
el procedimiento de ADR.

**Estado actual:** el proyecto está en su fase inicial. Buena parte de lo
anterior describe el compromiso al que nos obligamos según crezca, no una
estructura ya en funcionamiento. Decirlo claro es preferible a simular una
gobernanza que todavía no existe.
