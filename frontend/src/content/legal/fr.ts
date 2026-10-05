import type { LegalDocuments } from "./types.ts";

/** Politique de confidentialité et conditions d'utilisation, en français (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader. */
export const LEGAL_FR: LegalDocuments = {
  locale: "fr",
  privacy: {
    title: "Politique de confidentialité",
    intro: [
      "Cette politique explique ce que Sketchy conserve à ton sujet, pourquoi, " +
        "combien de temps, et ce que tu peux y faire. Sketchy est gratuit : il " +
        "n'affiche aucune publicité, et rien à ton sujet n'est vendu ni utilisé " +
        "pour te vendre quoi que ce soit.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Qui est responsable",
        body: [
          "Sketchy est exploité par son opérateur, établi en Suisse, qui décide " +
            "de ce qui est conservé et pourquoi. Tu peux écrire à l'opérateur à " +
            "{contact}.",
          "Le droit suisse de la protection des données s'applique à tout ce " +
            "qui est décrit ici, ainsi que le Règlement général sur la " +
            "protection des données de l'UE lorsque tu joues depuis l'Union " +
            "européenne.",
        ],
      },
      {
        id: "data",
        heading: "Ce qui est conservé",
        body: ["Seulement ce dont le jeu a besoin pour fonctionner, rester équitable et sûr :"],
        items: [
          "Le nom sous lequel tu joues, et le nom d'utilisateur d'un compte.",
          "Si tu crées un compte : ton adresse e-mail, ton mot de passe – " +
            "conservé uniquement sous forme d'empreinte à sens unique, dont on " +
            "ne peut pas le retrouver – et les clés d'accès ou la connexion en " +
            "deux étapes que tu configures.",
          "Tes paramètres et ton profil : tes langues et préférences, une photo " +
            "de profil si tu en envoies une, tes amis et les joueurs que tu " +
            "bloques.",
          "Tes parties : les salons où tu as joué, tes propositions, tes points " +
            "et résultats, tes réactions et les dessins que tu as faits.",
          "Le chat, dans les salons et dans le hall.",
          "Les listes de mots que tu écris, et si tu les as publiées.",
          "Les signalements que tu envoies et ceux qui te concernent, avec les " +
            "messages et dessins auxquels ils renvoient.",
          "Tes connexions : une description approximative de chaque appareil " +
            "(par exemple « Firefox sous Windows »), sa dernière utilisation, et " +
            "une empreinte à clé secrète de l'adresse réseau d'où il venait – " +
            "jamais l'adresse elle-même. Le même type d'empreinte limite le " +
            "nombre d'actions possibles depuis une même adresse.",
          "Les rapports de bug que tu envoies, avec une capture d'écran si tu " +
            "en joins une.",
          "Des informations techniques sur ta connexion et les erreurs de ton " +
            "navigateur, pour trouver et corriger les problèmes. Elles ne " +
            "contiennent aucun de tes messages ni de tes dessins.",
        ],
      },
      {
        id: "purposes",
        heading: "Pourquoi c'est conservé",
        body: [
          "Pour faire fonctionner le jeu auquel tu veux jouer : salons, tours, " +
            "points, ton historique et ton compte. C'est l'accord entre toi et " +
            "l'opérateur, tel que le décrivent les conditions d'utilisation.",
          "Pour que le jeu reste équitable et sûr : modérer les signalements, " +
            "empêcher la triche, le spam et les abus, et protéger les comptes. " +
            "C'est l'intérêt légitime de l'opérateur et de tous ceux qui jouent.",
          "Pour trouver et corriger les problèmes, pour la même raison.",
          "Rien à ton sujet n'est utilisé pour la publicité, vendu ou utilisé " +
            "pour établir ton profil, et aucune décision te concernant n'est " +
            "prise par une machine seule.",
        ],
      },
      {
        id: "visibility",
        heading: "Ce que voient les autres joueurs",
        body: [
          "Les personnes d'un salon voient ton nom, tes messages, tes dessins " +
            "et ton score.",
          "Les dessins faits dans un salon public apparaissent dans la Galerie, " +
            "où tout le monde peut les voir, avec le nom sous lequel ils ont été " +
            "dessinés. Les dessins d'un salon privé ne sont vus que par les " +
            "personnes qui y étaient. Supprimer ton compte efface tous tes " +
            "dessins ; pour en faire retirer un seul, écris à {contact}.",
          "Une liste de mots que tu publies peut être lue par tout le monde, " +
            "avec ton nom comme auteur. Ton profil montre ce que tu choisis d'y " +
            "montrer.",
        ],
      },
      {
        id: "recipients",
        heading: "Qui d'autre les traite",
        body: [
          "Personne ne reçoit tes données pour les utiliser à ses propres fins. " +
            "L'opérateur fait appel à quelques prestataires pour faire " +
            "fonctionner Sketchy – hébergement, acheminement réseau et e-mail –, " +
            "qui ne les traitent que sur ses instructions. Lorsque l'un d'eux le " +
            "fait hors de Suisse et de l'UE, c'est avec des garanties reconnues " +
            "par la loi, comme les clauses contractuelles types de la Commission " +
            "européenne.",
          "Les modérateurs désignés par l'opérateur voient les signalements " +
            "qu'ils tranchent et les messages et dessins auxquels ils renvoient.",
          "Les données ne sont transmises aux autorités que lorsque la loi " +
            "l'exige.",
        ],
      },
      {
        id: "retention",
        heading: "Combien de temps c'est conservé",
        body: [],
        items: [
          "Chat : 30 jours. Les lignes citées dans un signalement sont " +
            "conservées avec lui aussi longtemps que la modération en a besoin.",
          "Invités : supprimés après 30 jours sans partie terminée, ou après " +
            "365 jours sans jouer une fois qu'ils en ont une.",
          "Comptes : jusqu'à ce que tu les supprimes.",
          "Connexions : jusqu'à leur expiration, puis 30 jours.",
          "E-mails qui te sont envoyés : 30 jours.",
          "Captures d'écran des rapports de bug : jusqu'au traitement du " +
            "rapport, et jamais plus de 90 jours.",
          "Exports de données que tu demandes : 7 jours.",
          "Les parties terminées – points, dessins, réactions – font partie de " +
            "l'historique de tous ceux qui ont joué, elles sont donc conservées. " +
            "Si tu supprimes ton compte, tes dessins sont effacés et ta place " +
            "dans ces parties est anonymisée, ce qui préserve l'historique des " +
            "autres sans toi.",
        ],
      },
      {
        id: "rights",
        heading: "Tes droits",
        body: [
          "Dans les Paramètres, tu peux télécharger tout ce que Sketchy conserve " +
            "à ton sujet, corriger ton nom, ton e-mail et ton profil, et " +
            "supprimer ton compte ou ton identité d'invité, quand tu veux.",
          "Tu as aussi le droit de savoir ce qui est conservé à ton sujet et " +
            "comment c'est utilisé, de le faire corriger ou effacer, de t'opposer " +
            "à son utilisation pour les intérêts légitimes de l'opérateur et d'en " +
            "faire limiter l'utilisation. Écris à {contact} pour tout ce que les " +
            "Paramètres ne permettent pas.",
          "Si tu estimes que tes données sont mal traitées, tu peux te plaindre " +
            "auprès d'une autorité de protection des données : en Suisse, le " +
            "Préposé fédéral à la protection des données et à la transparence " +
            "(PFPDT), et dans l'UE, l'autorité du pays où tu vis.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies et stockage",
        body: [
          "Sketchy dépose un seul cookie, qui te garde connecté. Il est " +
            "nécessaire au fonctionnement du jeu, donc on ne te demande pas de " +
            "l'accepter. Tes paramètres sont aussi mémorisés dans le stockage de " +
            "ton propre navigateur.",
          "Il n'y a ni cookies publicitaires ni cookies de mesure d'audience, " +
            "et aucun script provenant de tiers.",
        ],
      },
      {
        id: "age",
        heading: "Âge",
        body: [
          "Sketchy s'adresse aux personnes de {age} ans et plus. Si tu es parent " +
            "et penses que ton enfant de moins de {age} ans joue, écris à " +
            "{contact} et ses données seront supprimées.",
        ],
      },
      {
        id: "changes",
        heading: "Modifications de cette politique",
        body: [
          "Si cette politique change, la nouvelle version est publiée ici. Une " +
            "modification qui touche à l'utilisation de tes données ne " +
            "s'appliquera pas à ce qui a été conservé avant sans que tu en sois " +
            "informé d'abord.",
        ],
      },
    ],
  },
  terms: {
    title: "Conditions d'utilisation",
    intro: [
      "Ces conditions sont l'accord entre toi et l'opérateur de Sketchy. En " +
        "jouant, tu les acceptes ; si tu ne les acceptes pas, n'utilise pas " +
        "Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy est en bêta",
        body: [
          "Sketchy est gratuit et encore en construction : des fonctions " +
            "changent, des choses cassent et, dans de rares cas, quelque chose " +
            "peut être perdu. Merci d'y jouer quand même.",
        ],
      },
      {
        id: "age",
        heading: "Qui peut jouer",
        body: ["Tu dois avoir au moins {age} ans. En jouant, tu confirmes que c'est le cas."],
      },
      {
        id: "accounts",
        heading: "Ton nom et ton compte",
        body: [
          "Choisis un nom qui ne se fait pas passer pour quelqu'un d'autre et " +
            "qui respecte les règles. Garde ton mot de passe et ta connexion pour " +
            "toi : tu es responsable de ce qui est fait avec ton compte.",
          "Un invité vit dans un navigateur. Effacer les données de ce " +
            "navigateur fait perdre l'invité, sauf si tu en as fait un compte.",
        ],
      },
      {
        id: "fair-play",
        heading: "Jouer franc jeu",
        body: [
          "Respecte les règles. Ne triche pas – pas de devinettes automatisées, " +
            "pas de réponse soufflée aux autres, pas de jeu sous plusieurs " +
            "identités pour prendre l'avantage –, n'essaie pas de casser ou de " +
            "surcharger Sketchy, et ne l'utilise pour rien d'illégal.",
        ],
      },
      {
        id: "content",
        heading: "Ce que tu dessines et écris",
        body: [
          "Ce que tu dessines, écris et publies reste à toi. Pour que le jeu " +
            "fonctionne, tu autorises l'opérateur à le conserver, l'afficher et " +
            "le copier au sein de Sketchy – dans ton salon, dans la Galerie pour " +
            "les salons publics, dans les listes de mots que tu publies et dans " +
            "les copies que d'autres en font –, gratuitement, dans le monde " +
            "entier et aussi longtemps que Sketchy le conserve.",
          "Ne dessine et n'écris que ce que tu as le droit de partager, et rien " +
            "que les règles interdisent.",
        ],
      },
      {
        id: "moderation",
        heading: "Modération",
        body: [
          "Les modérateurs peuvent masquer du contenu, avertir des joueurs et " +
            "suspendre ou bannir les comptes qui enfreignent ces conditions ou " +
            "les règles. On te dit quelle règle une décision concerne, et un " +
            "compte suspendu peut toujours télécharger et supprimer ses données.",
        ],
      },
      {
        id: "availability",
        heading: "Aucune garantie",
        body: [
          "Sketchy est fourni tel quel, sans promesse qu'il soit toujours " +
            "disponible, qu'il fonctionne sans erreur ou qu'il conserve pour " +
            "toujours ce que tu as fait. L'opérateur peut le modifier, le mettre " +
            "en pause ou le fermer.",
        ],
      },
      {
        id: "liability",
        heading: "Responsabilité",
        body: [
          "Dans la mesure permise par la loi, l'opérateur n'est pas responsable " +
            "des dommages indirects ni de la perte de contenus ou de données. " +
            "Rien ici ne limite une responsabilité que la loi ne permet pas de " +
            "limiter, comme en cas de faute intentionnelle ou de négligence " +
            "grave.",
        ],
      },
      {
        id: "leaving",
        heading: "Partir",
        body: [
          "Tu peux arrêter à tout moment et supprimer ton compte dans les " +
            "Paramètres. L'opérateur peut mettre fin à ton accès si tu enfreins " +
            "ces conditions ou les règles, ou fermer Sketchy complètement.",
        ],
      },
      {
        id: "law",
        heading: "Quel droit s'applique",
        body: [
          "Ces conditions sont régies par le droit suisse. Les litiges relèvent " +
            "des tribunaux du siège de l'opérateur en Suisse, sauf si le droit " +
            "du pays où tu vis te donne, en tant que consommateur, le droit " +
            "d'agir en justice chez toi.",
        ],
      },
      {
        id: "changes",
        heading: "Modifications de ces conditions",
        body: [
          "Si ces conditions changent, la nouvelle version est publiée ici. " +
            "Continuer à jouer après une modification signifie que tu " +
            "l'acceptes. Les questions vont à {contact}.",
        ],
      },
    ],
  },
};
