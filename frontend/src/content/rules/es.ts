import type { RulesDocument } from "./types.ts";

/** The rules, in Spanish.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in Spanish
(R-RULES-03). */
export const RULES_ES: RulesDocument = {
  locale: "es",
  title: "Reglas",
  introHeading: "Introducción",
  intro: [
    "Sketchy es un juego que juegas con desconocidos, y casi todo funciona porque la mayoría de la gente se porta bien sin que nadie se lo pida. Estas reglas son para las veces en que eso no se cumple — y para que, si alguna vez interviene un moderador, no sea una sorpresa.",
    "Casi nada de lo que sale mal aquí es maldad. Un mal día lo tiene cualquiera, una broma puede caer mal, y nunca sabes de verdad con qué está lidiando quien está al otro lado de un dibujo. Da eso por supuesto primero y la mayoría de las cosas dejan de merecer una denuncia.",
    "Así que nada de esto está aquí como un palo. Está aquí para que las salas sigan siendo un sitio donde la gente aparece, dibuja algo ridículo y se relaja. Cuando sí tenemos que decidir algo, nos guiamos por lo que pasó y no por quién eres: un moderador lee lo que se dijo o se dibujó realmente, en el orden en que pasó, y decide a partir de ahí.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Cómo tratas a los demás",
      blurb: "Estás jugando con gente que no puede marcharse sin dejar la partida. Estas dos reglas van de eso.",
      rules: [
        {
          id: "harassment",
          heading: "Acoso",
          body: [
            "No vayas a por otros jugadores. Nada de insultos, amenazas ni humillaciones — y eso incluye ofensas y odio de cualquier tipo, acoso sexual y seguir a alguien de sala en sala para seguir con lo mismo.",
            "Las pullas son media diversión y no tienen nada de malo — mientras todo el mundo esté de verdad en el ajo y no se pase de la raya. El límite está donde deja de ser compartido: cuando alguien ya ha tenido bastante, o cuando apunta a una persona que no se ríe. Si no lo tienes claro, afloja. No te cuesta nada.",
            "Y perder mal una ronda no es motivo para pagarlo con quien ganó, igual que tampoco lo es que alguien dibuje algo que no te gusta.",
          ],
          examples: [
            "Cebarse con el dibujo de alguien hasta que en realidad va sobre esa persona",
            "Meterse con la raza, la religión, el sexo, el género, la discapacidad o la nacionalidad de alguien",
            "Seguir a alguien a una sala para continuar una discusión",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "No inundes el chat, no te repitas para tapar a los demás y no uses el juego para anunciar nada.",
            "Adivinar no es spam, por muy disparatados que sean los intentos — adivinar rápido es justo de lo que va esto.",
          ],
          examples: [
            "Repetir un mensaje hasta que nadie pueda seguir la ronda",
            "Publicar enlaces o invitaciones a otro sitio",
            "Pegar el mismo muro de texto en una sala tras otra",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Lo que todos los demás tienen que mirar",
      blurb: "Tu dibujo, tu nombre y tu imagen aterrizan delante de gente que no los eligió. Nadie puede apartar la vista del lienzo y seguir jugando.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Dibujos ofensivos",
          body: [
            "Dibuja la palabra. El lienzo no es sitio para contenido sexual, sangre, símbolos de odio ni para meterse con alguien de la sala.",
            "Dibujar mal no va contra las reglas — nadie está juzgando tus círculos. Esto va de dibujar otra cosa a propósito.",
          ],
          examples: [
            "Dibujos sexuales o sangrientos",
            "Símbolos de odio, por muy tosco que sea el dibujo",
            "Dibujar un insulto sobre alguien en vez de la palabra",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Nombres inapropiados",
          body: [
            "Todos los que juegan contigo ven tu nombre, así que deja fuera las ofensas, los términos sexuales y los nombres hechos para picar a alguien.",
            "Tampoco te hagas pasar por otro jugador ni por un moderador.",
          ],
          examples: [
            "Un nombre con una ofensa o un término sexual dentro",
            "Un nombre hecho para parecerse al de otra persona",
            "Un nombre que es una pulla contra una persona concreta",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Imágenes inapropiadas",
          body: [
            "Lo mismo vale para la imagen de tu cuenta: está en tu perfil y junto a tu nombre allí donde juegues.",
            "Un moderador puede quitar una imagen sin que le pase nada más a tu cuenta, y la primera vez que ocurre puedes poner otra enseguida.",
          ],
          examples: [
            "Imágenes sexuales o explícitas",
            "Símbolos de odio o imaginería extremista",
            "Una foto de alguien que no aceptó estar ahí",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Jugar limpio",
      blurb: "El juego solo funciona si el adivinar es de verdad.",
      rules: [
        {
          id: "cheating",
          heading: "Trampas",
          body: [
            "No le des la palabra a nadie que tenga que adivinarla: ni en el chat, ni en el dibujo, ni fuera del juego. Y no pongas un programa a jugar por ti.",
            "Escribir la palabra en el lienzo cuenta como decirla.",
          ],
          examples: [
            "Escribir o deletrear la palabra mientras la dibujas",
            "Decirle la palabra a un amigo por una llamada u otra aplicación",
            "Usar una segunda cuenta para pasarte respuestas a ti mismo",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Qué pasa si incumples alguna",
    body: [
      "Las denuncias van a un moderador, que ve lo que se dijo o se dibujó realmente. La mayoría acaban sin que pase nada: la gente denuncia cosas que resultan estar bien, y para eso sirve justamente denunciar.",
      "Si algo estuvo mal, un moderador puede darte un aviso, quitar una imagen o suspender la cuenta. Un aviso no restringe nada, pero otra denuncia después de uno puede llevar a una suspensión. Una suspensión puede durar un día, una semana, un mes o no tener fecha de fin, y se te dirá cuál es.",
      "Pase lo que pase, se te dirá de qué iba y se te mostrarán tus propias palabras, o tu propio dibujo, detrás de ello. Nadie intenta pillarte.",
    ],
  },
};
