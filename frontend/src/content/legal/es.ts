import type { LegalDocuments } from "./types.ts";

/** Política de privacidad y condiciones de uso, en español de España (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader. */
export const LEGAL_ES: LegalDocuments = {
  locale: "es",
  privacy: {
    title: "Política de privacidad",
    intro: [
      "Esta política explica qué guarda Sketchy sobre ti, por qué, durante " +
        "cuánto tiempo y qué puedes hacer al respecto. Sketchy es gratuito: no " +
        "muestra publicidad, y nada sobre ti se vende ni se usa para venderte " +
        "nada.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Quién es el responsable",
        body: [
          "Sketchy lo gestiona su operador, con sede en Suiza, que decide qué se " +
            "guarda y por qué. Puedes escribir al operador a {contact}.",
          "A todo lo que se describe aquí se aplica la ley suiza de protección " +
            "de datos y, cuando juegas desde la Unión Europea, también el " +
            "Reglamento General de Protección de Datos de la UE.",
        ],
      },
      {
        id: "data",
        heading: "Qué se guarda",
        body: ["Solo lo que el juego necesita para funcionar, ser justo y seguir siendo seguro:"],
        items: [
          "El nombre con el que juegas, y el nombre de usuario de una cuenta.",
          "Si creas una cuenta: tu dirección de correo electrónico, tu " +
            "contraseña —guardada solo como un hash de un solo sentido del que " +
            "no se puede recuperar— y las llaves de acceso o la verificación en " +
            "dos pasos que configures.",
          "Tus ajustes y tu perfil: tus idiomas y preferencias, una foto de " +
            "perfil si subes una, tus amigos, los jugadores que bloqueas, tus " +
            "ajustes de sala guardados y las listas que marcas con estrella.",
          "Tus partidas: las salas en las que jugaste, tus respuestas, puntos y " +
            "resultados, tus reacciones, los dibujos que hiciste y los dibujos " +
            "que compartiste en la Galería.",
          "El chat, en las salas y en el vestíbulo.",
          "Los mensajes de tu bandeja de entrada, sobre tu cuenta, tus dibujos " +
            "y tus amistades.",
          "Las listas de palabras que escribes y si las publicaste.",
          "Las denuncias que envías y las denuncias sobre ti, con los mensajes y " +
            "dibujos a los que se refieren, y cualquier advertencia o suspensión " +
            "de tu cuenta.",
          "Un registro de seguridad y moderación de las acciones delicadas —como " +
            "los cambios de contraseña y de correo, bloquear a alguien, cambiar " +
            "tu imagen y las decisiones de moderación.",
          "Tus inicios de sesión: una descripción aproximada de cada dispositivo " +
            "(como «Firefox en Windows»), cuándo se usó por última vez y un hash " +
            "con clave secreta de la dirección de red desde la que se conectó. El " +
            "mismo tipo de hash se guarda con el registro anterior y limita " +
            "cuántas veces se puede hacer algo desde una misma dirección. Sketchy " +
            "nunca guarda la dirección en sí, aunque los proveedores que " +
            "transportan su tráfico la ven.",
          "Cuándo entras y sales de las salas, para poder rastrear problemas.",
          "Los informes de fallos que envías, con una captura de pantalla si " +
            "adjuntas una.",
          "Información técnica sobre tu conexión y los errores de tu navegador, " +
            "para poder encontrar y corregir problemas. No contiene ninguno de " +
            "tus mensajes ni dibujos.",
        ],
      },
      {
        id: "purposes",
        heading: "Por qué se guarda",
        body: [
          "Para hacer funcionar el juego al que quieres jugar: salas, turnos, " +
            "puntos, tu historial y tu cuenta. Es el acuerdo entre tú y el " +
            "operador, tal como figura en las condiciones de uso. Tu dirección " +
            "de correo se usa solo para tu cuenta: para confirmarla, para " +
            "restablecer la contraseña y para avisarte de cambios en ella y de " +
            "decisiones que le afecten.",
          "Para que el juego siga siendo justo y seguro: moderar denuncias, " +
            "frenar las trampas, el spam y los abusos, y proteger las cuentas. Es " +
            "el interés legítimo del operador y de todos los que juegan.",
          "Para encontrar y corregir problemas, por la misma razón.",
          "Para responder a las autoridades cuando la ley obligue al operador.",
          "Nada sobre ti se usa para publicidad, se vende ni sirve para crear un " +
            "perfil tuyo, y ninguna decisión con efectos jurídicos o igualmente " +
            "importantes para ti la toma solo una máquina.",
        ],
      },
      {
        id: "visibility",
        heading: "Qué ven los demás jugadores",
        body: [
          "Quienes están en una sala contigo ven tu nombre, tus mensajes, tus " +
            "dibujos y tu puntuación.",
          "Un dibujo se muestra en la Galería, donde cualquiera puede verlo, " +
            "solo cuando alguien lo comparte, con el nombre con el que se dibujó " +
            "y el nombre de la primera persona que lo compartió. Puedes " +
            "compartir tus propios dibujos desde cualquier sala. En una sala " +
            "pública, el resto de la sala también puede compartir los tuyos, sin " +
            "preguntarte antes: jugar en una sala pública es jugar en público, " +
            "según las condiciones de uso. Puedes quitar de la Galería cualquier " +
            "dibujo tuyo, y nadie podrá volver a compartirlo a menos que lo " +
            "hagas tú. Los dibujos de una sala privada solo los ven quienes " +
            "estaban en ella, salvo que compartas los tuyos.",
          "Si eliminas tu cuenta, se borran todos tus dibujos, salvo una copia " +
            "adjunta a una denuncia, que se queda con ella; para que se borre " +
            "uno solo, escribe a {contact}.",
          "Una lista de palabras que publiques puede leerla cualquiera, con tu " +
            "nombre como autor. Tu perfil muestra lo que tú decidas mostrar.",
        ],
      },
      {
        id: "recipients",
        heading: "Quién más los trata",
        body: [
          "Nadie recibe tus datos para usarlos con sus propios fines. El " +
            "operador recurre a algunos proveedores para hacer funcionar " +
            "Sketchy —alojamiento, distribución por la red y correo " +
            "electrónico—, que solo los tratan siguiendo las instrucciones del " +
            "operador. Cuando alguno lo hace fuera de Suiza y de la UE, es con " +
            "garantías que la ley reconoce, como las cláusulas contractuales " +
            "tipo de la Comisión Europea; escribe a {contact} para saber qué " +
            "países y qué garantías.",
          "Toda conexión con Sketchy está cifrada, las contraseñas solo se " +
            "guardan como hashes de un solo sentido, el equipo de moderación y " +
            "administración solo ve lo que requiere cada función, y los datos " +
            "antiguos se eliminan según los plazos que se indican más abajo.",
          "Los moderadores y administradores que nombra el operador ven las " +
            "denuncias que deciden y aquello a lo que se refieren. Los " +
            "administradores también leen los informes de fallos y pueden " +
            "consultar una cuenta y su actividad reciente cuando algo va mal.",
          "Los datos solo se entregan a las autoridades cuando la ley lo exige.",
        ],
      },
      {
        id: "retention",
        heading: "Cuánto tiempo se guarda",
        body: [],
        items: [
          "Chat: 30 días, salvo las líneas citadas en una denuncia, que se " +
            "quedan con ella.",
          "Las denuncias y lo que citan, las suspensiones, el registro de " +
            "seguridad y moderación y los informes de fallos: se conservan como " +
            "constancia duradera de la moderación y de la seguridad del " +
            "servicio, también después de que elimines tu cuenta. Las entradas " +
            "del registro dejan entonces de nombrarte.",
          "Advertencias: 12 meses, y se eliminan con tu cuenta.",
          "Mensajes de tu bandeja de entrada: 90 días, leídos o no, y se " +
            "eliminan con tu cuenta.",
          "Capturas de los informes de fallos: hasta que se atienda el informe, " +
            "y nunca más de 90 días.",
          "Invitados: se eliminan tras 30 días sin una partida terminada, o tras " +
            "365 días sin jugar si ya tienen una.",
          "Cuentas: hasta que las elimines. Amistades, bloqueos, listas de " +
            "palabras, ajustes de sala guardados y estrellas: hasta que los " +
            "quites o elimines tu cuenta.",
          "Inicios de sesión: hasta que caduquen, y 30 días después, salvo los de una cuenta suspendida, que se conservan mientras dure la suspensión, porque son su única vía para descargar o eliminar sus datos.",
          "Entradas y salidas de las salas: 30 días.",
          "Correos que se te envían: 30 días.",
          "Exportaciones de datos que pidas: 7 días.",
          "Las partidas terminadas —puntos, dibujos, reacciones— forman parte " +
            "del historial de todos los que jugaron, así que se conservan. Si " +
            "eliminas tu cuenta, tus dibujos se borran y tu lugar en esas " +
            "partidas se anonimiza, de modo que el historial de los demás sigue " +
            "intacto sin ti.",
        ],
      },
      {
        id: "rights",
        heading: "Tus derechos",
        body: [
          "En Ajustes puedes descargar una copia de tus datos, corregir tu " +
            "nombre, tu correo y tu perfil, y eliminar tu cuenta o tu identidad " +
            "de invitado cuando quieras.",
          "También tienes derecho a pedir todo lo que se guarda sobre ti y cómo " +
            "se usa —incluido lo que la descarga no incluye, como las denuncias " +
            "sobre ti—, a que se corrija o se borre, a recibirlo en un formato " +
            "que puedas llevarte a otro sitio, a oponerte a su uso para los " +
            "intereses legítimos del operador y a que se limite su uso. Escribe " +
            "a {contact} para todo lo que no se pueda hacer en Ajustes.",
          "Si crees que tus datos se tratan mal, puedes reclamar ante una " +
            "autoridad de protección de datos: en Suiza, el Comisionado Federal " +
            "de Protección de Datos y Transparencia (FDPIC/EDÖB), y en la UE, la " +
            "autoridad del país en el que vives.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies y almacenamiento",
        body: [
          "Sketchy usa una sola cookie, que mantiene tu sesión iniciada. Es " +
            "necesaria para que el juego funcione, así que no se te pide " +
            "aceptarla. Tus ajustes también se recuerdan en el almacenamiento de " +
            "tu propio navegador.",
          "No hay cookies de publicidad ni de analítica, ni scripts de terceros.",
        ],
      },
      {
        id: "age",
        heading: "Edad",
        body: [
          "Sketchy es para personas de {age} años o más. Si eres madre, padre o " +
            "tutor y crees que tu hijo o hija menor de {age} años está jugando, " +
            "escribe a {contact} y se borrarán sus datos.",
        ],
      },
      {
        id: "changes",
        heading: "Cambios en esta política",
        body: [
          "Si esta política cambia, la nueva versión se publica aquí. Un cambio " +
            "que afecte a cómo se usan tus datos no se aplicará a lo guardado " +
            "antes sin avisarte primero.",
        ],
      },
    ],
  },
  terms: {
    title: "Condiciones de uso",
    intro: [
      "Estas condiciones son el acuerdo entre tú y el operador de Sketchy. Al " +
        "jugar, las aceptas; si no las aceptas, no uses Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy está en beta",
        body: [
          "Sketchy es gratuito y todavía se está construyendo: las funciones " +
            "cambian, algunas cosas fallan y, en casos raros, algo puede " +
            "perderse. Gracias por jugar de todos modos.",
        ],
      },
      {
        id: "age",
        heading: "Quién puede jugar",
        body: ["Debes tener al menos {age} años. Al jugar confirmas que los tienes."],
      },
      {
        id: "accounts",
        heading: "Tu nombre y tu cuenta",
        body: [
          "Elige un nombre que no se haga pasar por otra persona ni incumpla las " +
            "reglas. No compartas tu contraseña ni tu inicio de sesión: eres " +
            "responsable de lo que se haga con tu cuenta.",
          "Un invitado vive en un navegador. Si borras los datos de ese " +
            "navegador, pierdes el invitado, salvo que lo hayas convertido en " +
            "una cuenta.",
        ],
      },
      {
        id: "fair-play",
        heading: "Jugar limpio",
        body: [
          "Sigue las reglas. No hagas trampas —nada de respuestas automáticas, " +
            "de decir la respuesta a otros ni de jugar como varias personas para " +
            "sacar ventaja—, no intentes romper ni sobrecargar Sketchy y no lo " +
            "uses para nada ilegal.",
        ],
      },
      {
        id: "content",
        heading: "Lo que dibujas y escribes",
        body: [
          "Lo que dibujas, escribes y publicas sigue siendo tuyo. Para que el " +
            "juego funcione, permites al operador guardarlo, mostrarlo y " +
            "copiarlo dentro de Sketchy —en tu sala, en la Galería una vez que " +
            "se comparte un dibujo, " +
            "en las listas de palabras que publiques y en las " +
            "copias que otros hagan de ellas—, de forma gratuita, en todo el " +
            "mundo y mientras Sketchy lo conserve.",
          "Dibuja y escribe solo lo que tengas derecho a compartir, y nada que " +
            "las reglas prohíban.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderación",
        body: [
          "La moderación está a cargo de personas adultas que nombra el " +
            "operador. Estas personas pueden ocultar contenido, hacer " +
            "advertencias y suspender cuentas que incumplan estas condiciones o " +
            "las reglas. " +
            "Cuando un moderador registra a qué regla se refiere una decisión, " +
            "se te dice. Los datos de una cuenta suspendida se pueden seguir " +
            "descargando o eliminando, desde un dispositivo que tuviera la " +
            "sesión iniciada cuando empezó la suspensión o escribiendo a " +
            "{contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Sin garantías",
        body: [
          "Sketchy se ofrece tal cual, sin ninguna garantía de que esté siempre " +
            "disponible, funcione sin errores o conserve para siempre lo que " +
            "hiciste. El operador puede cambiarlo, pausarlo o cerrarlo.",
        ],
      },
      {
        id: "liability",
        heading: "Responsabilidad",
        body: [
          "En la medida en que la ley lo permita, el operador no responde de " +
            "daños indirectos ni de la pérdida de contenido o datos. Nada de esto " +
            "limita la responsabilidad que la ley no permite limitar, como en " +
            "caso de dolo o negligencia grave.",
        ],
      },
      {
        id: "leaving",
        heading: "Dejar de jugar",
        body: [
          "Puedes dejarlo cuando quieras y eliminar tu cuenta en Ajustes. El " +
            "operador puede retirarte el acceso si incumples estas condiciones o " +
            "las reglas, o cerrar Sketchy por completo.",
        ],
      },
      {
        id: "law",
        heading: "Qué ley se aplica",
        body: [
          "Estas condiciones se rigen por el derecho suizo, que no te quita la " +
            "protección que te da como consumidor la ley imperativa del país en " +
            "el que vives. Los litigios corresponden a los tribunales de la sede " +
            "del operador en Suiza, salvo que esa ley te dé derecho a acudir a " +
            "los tribunales de tu país.",
        ],
      },
      {
        id: "changes",
        heading: "Cambios en estas condiciones",
        body: [
          "Si estas condiciones cambian en algo importante, se te avisará antes " +
            "de que el cambio se aplique, y seguir jugando después significa que " +
            "lo aceptas. Las preguntas, a {contact}.",
        ],
      },
    ],
  },
};
