import type { LegalDocuments } from "./types.ts";

/** The privacy notice and the terms, in English (#1417).

The reference text: every other locale is a translation of this one, and a
change here makes the translations stale until they follow. Written to the
Swiss Federal Act on Data Protection, which binds the operator, and to the EU
General Data Protection Regulation, which applies to players in the EU; the
two agree on nearly everything and the stricter reading is used where they do
not.

Every statement about what is kept and for how long is a fact recorded
elsewhere - `docs/database.md` §10 for retention, R-GAL-01 for the Gallery,
R-PRIV-01..08 for export and deletion, R-RATE-02 for addresses, R-BAN-04 for
a suspended account - and changes with it. Plain second person, like the
rules: the reader is a player, not a lawyer. */
export const LEGAL_EN: LegalDocuments = {
  locale: "en",
  privacy: {
    title: "Privacy notice",
    intro: [
      "This notice explains what Sketchy keeps about you, why, for how long, " +
        "and what you can do about it. Sketchy is free: it shows no " +
        "advertising, and nothing about you is sold or used to market " +
        "anything to you.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Who is responsible",
        body: [
          "Sketchy is run by its operator, who is based in Switzerland and " +
            "decides what is kept and why. You can write to the operator at " +
            "{contact}.",
          "Swiss data protection law applies to everything here, and so does " +
            "the EU General Data Protection Regulation when you play from the " +
            "European Union.",
        ],
      },
      {
        id: "data",
        heading: "What is kept",
        body: ["Only what the game needs to work, to be fair and to stay safe:"],
        items: [
          "The name you play under, and the username of an account.",
          "If you create an account: your email address, your password — " +
            "stored only as a one-way hash that cannot be turned back into it — " +
            "and any passkeys or two-factor authentication you set up.",
          "Your settings and profile: your languages and preferences, a " +
            "profile picture if you upload one, your friends, the players you " +
            "block, your saved room settings, and the lists you star.",
          "Your games: the rooms you played in, your guesses, points and " +
            "scores, your reactions, the drawings you made, and the drawings " +
            "you shared to the Gallery.",
          "Chat, in rooms and in the lobby.",
          "The messages in your inbox, about your account, your drawings " +
            "and your friends.",
          "The prompt lists you write, and whether you published them.",
          "Reports you send, and reports about you, with the messages and " +
            "drawings they point to; and any warning or suspension given to " +
            "your account.",
          "A security and moderation log of sensitive actions — such as " +
            "password and email changes, blocking somebody, changing your " +
            "picture, and moderators' decisions.",
          "Your sign-ins: a rough description of each device (such as " +
            "\"Firefox on Windows\"), when it was last used, and a keyed hash " +
            "of the network address it came from. The same kind of hash is " +
            "kept with the log above and used to limit how often anything can " +
            "be done from one address. Sketchy never stores the address " +
            "itself, though the providers that deliver its traffic see it.",
          "When you join and leave rooms, so problems can be traced.",
          "Bug reports you send, with a screenshot if you attach one.",
          "Technical information about your connection and any errors in " +
            "your browser, so problems can be found and fixed. It contains " +
            "none of your messages or drawings.",
        ],
      },
      {
        id: "purposes",
        heading: "Why it is kept",
        body: [
          "To run the game you asked to play: rooms, turns, scores, your " +
            "history and your account. This is the agreement between you and " +
            "the operator, set out in the terms of use. Your email address is " +
            "used only for your account: to confirm it, to reset your " +
            "password, and to tell you about changes to it and decisions " +
            "about it.",
          "To keep the game fair and safe: moderating reports, stopping " +
            "cheating, spam and abuse, and protecting accounts. This is the " +
            "operator's legitimate interest, and that of everybody who plays.",
          "To find and fix problems, for the same reason.",
          "To answer the authorities where the law obliges the operator to.",
          "Nothing about you is used for advertising, sold, or used to build " +
            "a profile of you, and no decision with legal or similarly " +
            "significant effects on you is made by a machine alone.",
        ],
      },
      {
        id: "visibility",
        heading: "What other players see",
        body: [
          "The people in a room see your name, your messages, your drawings " +
            "and your score.",
          "A drawing is shown in the Gallery, where anybody can see it, only " +
            "once somebody shares it, with the name it was drawn under and " +
            "the name of the first player who shared it. You can share your " +
            "own drawings from any room. In a public room the other players " +
            "can share yours too, without asking first: playing in a public " +
            "room is playing in public, under the terms of use. You can take " +
            "any drawing of yours out of the Gallery, and nobody can share it " +
            "again unless you do. Drawings from a private room are seen only " +
            "by the people who were in it, unless you share your own.",
          "Deleting your account erases every drawing you made, except a " +
            "copy attached to a report, which stays with the report; to have " +
            "a single drawing erased, write to {contact}.",
          "A prompt list you publish can be read by everybody, with your name " +
            "as its author. Your profile shows what you have chosen to show.",
        ],
      },
      {
        id: "recipients",
        heading: "Who else handles it",
        body: [
          "Nobody receives your data to use for their own purposes. The " +
            "operator relies on a few providers to run Sketchy — hosting, " +
            "network delivery and email — who handle it only on the " +
            "operator's instructions. Where one of them handles it outside " +
            "Switzerland and the EU, it is under safeguards the law " +
            "recognises, such as the European Commission's standard " +
            "contractual clauses; write to {contact} to ask which countries " +
            "and which safeguards.",
          "Moderators and administrators appointed by the operator see the " +
            "reports they decide and what those reports point to. " +
            "Administrators also read bug reports, and can look up an account " +
            "and its recent activity when something goes wrong.",
          "Data is given to authorities only where the law requires it.",
        ],
      },
      {
        id: "retention",
        heading: "How long it is kept",
        body: [],
        items: [
          "Chat: 30 days, except lines cited in a report, which stay with it.",
          "Reports and what they cite, suspensions, the security and " +
            "moderation log, and bug reports: kept as the lasting record of " +
            "moderation and of the service's security, also after you delete " +
            "your account. Log entries then no longer name you.",
          "Warnings: 12 months, and deleted with your account.",
          "Messages in your inbox: 90 days, read or not, and deleted with " +
            "your account.",
          "Bug-report screenshots: until the report is dealt with, and never " +
            "more than 90 days.",
          "Guests: removed after 30 days without a finished game, or after " +
            "365 days without playing once they have one.",
          "Accounts: until you delete them. Friendships, blocks, prompt " +
            "lists, saved room settings and stars: until you remove them or " +
            "delete your account.",
          "Sign-ins: until they expire, and 30 days after that — except those of a suspended account, which are kept while the suspension lasts, since they are its only way to download or delete its data.",
          "Room joins and leaves: 30 days.",
          "Emails sent to you: 30 days.",
          "Data exports you ask for: 7 days.",
          "Finished games — scores, drawings, reactions — are part of every " +
            "player's history, so they are kept. When you delete your account " +
            "your drawings are erased and your place in those games is " +
            "anonymised, which keeps the other players' history intact " +
            "without you in it.",
        ],
      },
      {
        id: "rights",
        heading: "Your rights",
        body: [
          "In Settings you can download a copy of your data, correct your " +
            "name, email and profile, and delete your account or your guest " +
            "identity, whenever you like.",
          "You also have the right to ask for everything kept about you and " +
            "how it is used — including what the download leaves out, such as " +
            "reports about you — to have it corrected or erased, to receive " +
            "it in a format you can take elsewhere, to object to its use for " +
            "the operator's legitimate interests, and to have its use " +
            "restricted. Write to {contact} for anything Settings does not do.",
          "If you think your data is mishandled, you can complain to a data " +
            "protection authority: in Switzerland the Federal Data Protection " +
            "and Information Commissioner (FDPIC), and in the EU the authority " +
            "of the country you live in.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies and storage",
        body: [
          "Sketchy sets a single cookie, which keeps you signed in. It is " +
            "needed for the game to work, so you are not asked to accept it. " +
            "Your settings are also remembered in your own browser's storage.",
          "There are no advertising or analytics cookies, and no scripts " +
            "from anybody else.",
        ],
      },
      {
        id: "age",
        heading: "Age",
        body: [
          "Sketchy is for people aged {age} and over. If you are a parent and " +
            "believe your child under {age} is playing, write to {contact} and " +
            "their data will be deleted.",
        ],
      },
      {
        id: "changes",
        heading: "Changes to this notice",
        body: [
          "If this notice changes, the new version is published here. A " +
            "change that matters to how your data is used will not apply to " +
            "what was kept before it without telling you first.",
        ],
      },
    ],
  },
  terms: {
    title: "Terms of use",
    intro: [
      "These terms are the agreement between you and the operator of " +
        "Sketchy. By playing, you accept them; if you do not, please do not " +
        "use Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy is in beta",
        body: [
          "Sketchy is free, and it is still being built: features change, " +
            "things break, and in rare cases something may be lost. Thank you " +
            "for playing it anyway.",
        ],
      },
      {
        id: "age",
        heading: "Who can play",
        body: [
          "You must be {age} or older. By playing you confirm that you are.",
        ],
      },
      {
        id: "accounts",
        heading: "Your name and account",
        body: [
          "Choose a name that does not pretend to be somebody else and does " +
            "not break the rules. Keep your password and sign-in to yourself: " +
            "you are responsible for what is done with your account.",
          "A guest lives in one browser. Clearing that browser's data loses " +
            "the guest, unless you have made it an account.",
        ],
      },
      {
        id: "fair-play",
        heading: "Playing fairly",
        body: [
          "Follow the rules. Do not cheat — no automated guesses, no telling " +
            "others the answer, no playing as several people to gain an " +
            "advantage — do not try to break or overload Sketchy, and do not " +
            "use it for anything unlawful.",
        ],
      },
      {
        id: "content",
        heading: "What you draw and write",
        body: [
          "What you draw, write and publish stays yours. So that the game " +
            "can work, you allow the operator to store, show and copy it " +
            "within Sketchy — in your room, in the Gallery once a drawing is " +
            "shared, " +
            "in prompt lists you publish and in copies other players make of " +
            "them — free of charge, worldwide, for as long as Sketchy keeps " +
            "it.",
          "Only draw and write what you have the right to share, and nothing " +
            "the rules forbid.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderation",
        body: [
          "Moderators can hide content, warn players, and suspend accounts " +
            "that break these terms or the rules. Where a moderator records " +
            "which rule a decision is about, you are told it. A suspended " +
            "account's data can still be downloaded or deleted, from a device " +
            "that was signed in when the suspension began, or by writing to " +
            "{contact}.",
        ],
      },
      {
        id: "availability",
        heading: "No guarantees",
        body: [
          "Sketchy is provided as it is, without any guarantee that it will " +
            "always be available, work without errors, or keep what you made " +
            "for ever. The operator may change it, pause it or close it.",
        ],
      },
      {
        id: "liability",
        heading: "Liability",
        body: [
          "As far as the law allows, the operator is not liable for indirect " +
            "loss, or for the loss of content or data. Nothing here limits " +
            "liability that the law does not allow to be limited, such as " +
            "for intent or gross negligence.",
        ],
      },
      {
        id: "leaving",
        heading: "Leaving",
        body: [
          "You can stop at any time and delete your account in Settings. The " +
            "operator may end your access if you break these terms or the " +
            "rules, or close Sketchy altogether.",
        ],
      },
      {
        id: "law",
        heading: "Which law applies",
        body: [
          "These terms are governed by Swiss law, which does not take away " +
            "the protection the mandatory law of the country you live in " +
            "gives you as a consumer. Disputes go to the courts of the " +
            "operator's place of business in Switzerland, unless that law " +
            "gives you the right to go to court at home.",
        ],
      },
      {
        id: "changes",
        heading: "Changes to these terms",
        body: [
          "If these terms change in a way that matters, you will be told " +
            "before the change applies, and playing after it applies means " +
            "you accept it. Questions go to {contact}.",
        ],
      },
    ],
  },
};
