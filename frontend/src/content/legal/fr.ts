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
            "ne peut pas le retrouver – et les clés d'accès ou l'authentification " +
            "à deux facteurs que tu configures.",
          "Tes paramètres et ton profil : tes langues et préférences, une photo " +
            "de profil si tu en envoies une, tes amis, les joueurs que tu " +
            "bloques, tes réglages de salon enregistrés et les listes que tu " +
            "mets en favori.",
          "Tes parties : les salons où tu as joué, tes réponses, tes points et " +
            "résultats, tes réactions, les dessins que tu as faits et les " +
            "dessins que tu as partagés dans la Galerie.",
          "Le chat, dans les salons et dans le hall.",
          "Les messages de ta boîte de réception, au sujet de ton compte, de " +
            "tes dessins et de tes amitiés.",
          "Les listes de mots que tu écris, et si tu les as publiées.",
          "Les signalements que tu envoies et ceux qui te concernent, avec les " +
            "messages et dessins auxquels ils renvoient, ainsi que tout " +
            "avertissement ou toute suspension de ton compte.",
          "Un journal de sécurité et de modération des actions sensibles – par " +
            "exemple les changements de mot de passe et d'adresse e-mail, le " +
            "blocage de quelqu'un, le changement de ton image et les décisions " +
            "de modération.",
          "Tes connexions : une description approximative de chaque appareil " +
            "(par exemple « Firefox sous Windows »), sa dernière utilisation, et " +
            "une empreinte à clé secrète de l'adresse réseau d'où il venait. Le " +
            "même type d'empreinte est conservé dans le journal ci-dessus et " +
            "limite le nombre d'actions possibles depuis une même adresse. " +
            "Sketchy ne conserve jamais l'adresse elle-même, même si les " +
            "prestataires qui acheminent son trafic la voient.",
          "Le moment où tu entres dans un salon et où tu en sors, pour pouvoir " +
            "retracer les problèmes.",
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
            "l'opérateur, tel que le décrivent les conditions d'utilisation. Ton " +
            "adresse e-mail ne sert qu'à ton compte : le confirmer, réinitialiser " +
            "ton mot de passe et te prévenir des changements qui le concernent " +
            "et des décisions à son sujet.",
          "Pour que le jeu reste équitable et sûr : modérer les signalements, " +
            "empêcher la triche, le spam et les abus, et protéger les comptes. " +
            "C'est l'intérêt légitime de l'opérateur et de tous ceux qui jouent.",
          "Pour trouver et corriger les problèmes, pour la même raison.",
          "Pour répondre aux autorités lorsque la loi y oblige l'opérateur.",
          "Rien à ton sujet n'est utilisé pour la publicité, vendu ou utilisé " +
            "pour te profiler, et aucune décision produisant des effets " +
            "juridiques ou t'affectant de manière comparable n'est prise par une " +
            "machine seule.",
        ],
      },
      {
        id: "visibility",
        heading: "Ce que voient les autres joueurs",
        body: [
          "Les personnes d'un salon voient ton nom, tes messages, tes dessins " +
            "et ton score.",
          "Un dessin n'apparaît dans la Galerie, où tout le monde peut le voir, " +
            "qu'une fois que quelqu'un l'a partagé, avec le nom sous lequel il a " +
            "été dessiné et le nom de la première personne qui l'a partagé. Tu " +
            "peux partager tes propres dessins depuis n'importe quel salon. Dans " +
            "un salon public, les autres personnes du salon peuvent aussi " +
            "partager les tiens, sans te demander d'abord : jouer dans un salon " +
            "public, c'est jouer en public, selon les conditions d'utilisation. " +
            "Tu peux retirer de la Galerie n'importe lequel de tes dessins, et " +
            "personne ne peut alors le partager de nouveau, sauf toi. Les dessins " +
            "d'un salon privé ne sont vus que par les personnes qui y étaient, " +
            "sauf si tu partages les tiens.",
          "Supprimer ton compte efface tous tes dessins, sauf une copie jointe " +
            "à un signalement, qui reste avec lui ; pour en faire effacer un " +
            "seul, écris à {contact}.",
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
            "européenne ; écris à {contact} pour savoir quels pays et quelles " +
            "garanties.",
          "Chaque connexion à Sketchy est chiffrée, les mots de passe ne sont " +
            "conservés que sous forme d'empreintes à sens unique, l'équipe de " +
            "modération et d'administration ne voit que ce que chaque rôle " +
            "exige, et les données anciennes sont supprimées selon les durées " +
            "indiquées plus bas.",
          "Les modérateurs et administrateurs désignés par l'opérateur voient " +
            "les signalements qu'ils tranchent et ce à quoi ils renvoient. Les " +
            "administrateurs lisent aussi les rapports de bug et peuvent " +
            "consulter un compte et son activité récente quand quelque chose ne " +
            "va pas.",
          "Les données ne sont transmises aux autorités que lorsque la loi " +
            "l'exige.",
        ],
      },
      {
        id: "retention",
        heading: "Combien de temps c'est conservé",
        body: [],
        items: [
          "Chat : 30 jours, sauf les lignes citées dans un signalement, qui " +
            "restent avec lui.",
          "Les signalements et ce qu'ils citent, les suspensions, le journal " +
            "de sécurité et de modération et les rapports de bug : conservés " +
            "comme trace durable de la modération et de la sécurité du service, " +
            "y compris après la suppression de ton compte. Les entrées du " +
            "journal ne te nomment alors plus.",
          "Avertissements : 12 mois, et supprimés avec ton compte.",
          "Messages de ta boîte de réception : 90 jours, lus ou non, et " +
            "supprimés avec ton compte.",
          "Captures d'écran des rapports de bug : jusqu'au traitement du " +
            "rapport, et jamais plus de 90 jours.",
          "Invités : supprimés après 30 jours sans partie terminée, ou après " +
            "365 jours sans jouer une fois qu'ils en ont une.",
          "Comptes : jusqu'à ce que tu les supprimes. Amitiés, blocages, listes " +
            "de mots, réglages de salon enregistrés et favoris : jusqu'à ce que " +
            "tu les retires ou que tu supprimes ton compte.",
          "Connexions : jusqu'à leur expiration, puis 30 jours – sauf celles d'un compte suspendu, conservées tant que dure la suspension, car elles sont son seul moyen de télécharger ou de supprimer ses données.",
          "Entrées et sorties des salons : 30 jours.",
          "E-mails qui te sont envoyés : 30 jours.",
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
          "Dans les Paramètres, tu peux télécharger une copie de tes données, " +
            "corriger ton nom, ton e-mail et ton profil, et supprimer ton compte " +
            "ou ton identité d'invité, quand tu veux.",
          "Tu as aussi le droit d'obtenir tout ce qui est conservé à ton sujet " +
            "et la manière dont c'est utilisé – y compris ce que le " +
            "téléchargement ne contient pas, comme les signalements te " +
            "concernant –, de le faire corriger ou effacer, de le recevoir dans " +
            "un format que tu peux emporter ailleurs, de t'opposer à son " +
            "utilisation pour les intérêts légitimes de l'opérateur et d'en " +
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
          "Respecte les règles. Ne triche pas – pas de propositions " +
            "automatiques, pas de réponse soufflée aux autres, pas de jeu sous " +
            "plusieurs identités pour prendre l'avantage –, n'essaie pas de " +
            "casser ou de surcharger Sketchy, et ne l'utilise pour rien " +
            "d'illégal.",
        ],
      },
      {
        id: "content",
        heading: "Ce que tu dessines et écris",
        body: [
          "Ce que tu dessines, écris et publies reste à toi. Pour que le jeu " +
            "fonctionne, tu autorises l'opérateur à le conserver, l'afficher et " +
            "le copier au sein de Sketchy – dans ton salon, dans la Galerie une " +
            "fois un dessin partagé, " +
            "dans les listes de mots que tu publies et dans " +
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
          "La modération est assurée par des personnes adultes désignées par " +
            "l'opérateur. Elles peuvent masquer du contenu, donner des " +
            "avertissements et suspendre les comptes qui enfreignent ces " +
            "conditions ou les règles. " +
            "Lorsqu'un modérateur indique quelle règle une décision concerne, on " +
            "te le dit. Les données d'un compte suspendu peuvent toujours être " +
            "téléchargées ou supprimées, depuis un appareil qui était connecté " +
            "au début de la suspension ou en écrivant à {contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Aucune garantie",
        body: [
          "Sketchy est fourni tel quel, sans aucune garantie qu'il soit " +
            "toujours disponible, qu'il fonctionne sans erreur ou qu'il conserve " +
            "pour toujours ce que tu as fait. L'opérateur peut le modifier, le " +
            "mettre en pause ou le fermer.",
        ],
      },
      {
        id: "liability",
        heading: "Responsabilité",
        body: [
          "Dans la mesure permise par la loi, l'opérateur n'est pas responsable " +
            "des dommages indirects ni de la perte de contenus ou de données. " +
            "Rien ici ne limite une responsabilité que la loi ne permet pas de " +
            "limiter, comme en cas de dol ou de faute grave.",
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
          "Ces conditions sont régies par le droit suisse, qui ne te prive pas " +
            "de la protection que t'accorde, en tant que consommateur, le droit " +
            "impératif du pays où tu vis. Les litiges relèvent des tribunaux du " +
            "siège de l'opérateur en Suisse, sauf si ce droit te permet d'agir " +
            "en justice chez toi.",
        ],
      },
      {
        id: "changes",
        heading: "Modifications de ces conditions",
        body: [
          "Si ces conditions changent sur un point important, tu en seras " +
            "informé avant que la modification s'applique, et continuer à jouer " +
            "ensuite signifie que tu l'acceptes. Les questions vont à {contact}.",
        ],
      },
    ],
  },
};
