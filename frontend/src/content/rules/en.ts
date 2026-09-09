import type { RulesDocument } from "./types.ts";

/** The rules, in English.

The reference text: every other locale is a translation of this one, and when
this changes a translation is stale until it follows.

Written the way you would explain it to somebody, not the way a policy is
drafted. The person most likely to read this is somebody who has just been
told they broke one, and a wall of "must not" reads as an accusation before
they have even got to what it says. Plain second person, contractions,
and the reason next to the rule wherever there is one worth giving. */
export const RULES_EN: RulesDocument = {
  locale: "en",
  title: "Rules",
  introHeading: "Introduction",
  intro: [
    "Sketchy is a game you play with strangers, and nearly all of it works " +
      "because most people are decent without being asked. These rules are " +
      "for the times that doesn't hold — and so that if a moderator ever " +
      "steps in, it isn't a surprise.",
    "Most of what goes wrong here isn't malice. A bad day can happen to " +
      "anyone, a joke can land badly, and you never really know what somebody " +
      "on the other side of a drawing is dealing with. Assume that first, and " +
      "most of it stops being worth a report at all.",
    "So none of this is here as a stick. It's here so the rooms stay " +
      "somewhere people can turn up, draw something ridiculous, and relax. " +
      "When we do have to decide something, we go on what happened rather " +
      "than on who you are: a moderator reads what was actually said or " +
      "drawn, in the order it happened, and decides from there.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "How you treat other people",
      blurb:
        "You're playing with people who can't just walk away without leaving " +
        "the game. These two are about that.",
      rules: [
        {
          id: "harassment",
          heading: "Harassment",
          body: [
            "Don't go after other players. No abuse, threats, or putting " +
              "someone down — and that includes slurs and hate of any kind, " +
              "sexual harassment, and following someone from room to room to " +
              "keep at it.",
            "Banter is half the fun and there's nothing wrong with it — as " +
              "long as everyone's actually in on it and it doesn't go too " +
              "far. The line is where it stops being shared: when somebody's " +
              "had enough, or it's pointed at one person who isn't laughing. " +
              "If you can't tell, ease off. It costs you nothing.",
            "And losing a round badly isn't a reason to take it out on " +
              "whoever won, any more than somebody drawing something you " +
              "don't like is.",
          ],
          examples: [
            "Piling on about someone's drawing until it's really about them",
            "Going after someone's race, religion, sex, gender, disability, or nationality",
            "Following someone into a room to carry on an argument",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Don't flood the chat, repeat yourself to drown everyone else " +
              "out, or use the game to advertise something.",
            "Guessing isn't spam, however wild the guesses get — guessing " +
              "fast is the whole point.",
          ],
          examples: [
            "Repeating a message until nobody can follow the round",
            "Posting links or invites to somewhere else",
            "Pasting the same wall of text into room after room",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "What everyone else has to look at",
      blurb:
        "Your drawing, your name and your picture all land in front of people " +
        "who didn't pick them. Nobody can look away from the canvas and keep " +
        "playing.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Offensive drawings",
          body: [
            "Draw the prompt. The canvas isn't the place for sexual content, " +
              "gore, hate symbols, or having a go at somebody in the room.",
            "Being bad at drawing isn't against the rules — nobody's judging " +
              "your circles. This is about drawing something else on purpose.",
          ],
          examples: [
            "Sexual or gory drawings",
            "Hate symbols, however rough the drawing",
            "Drawing an insult about somebody instead of the prompt",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Inappropriate names",
          body: [
            "Everyone you play with sees your name, so keep slurs, sexual " +
              "terms, and names built to needle somebody out of it.",
            "Don't pretend to be another player or a moderator either.",
          ],
          examples: [
            "A name with a slur or a sexual term in it",
            "A name made to look like somebody else's",
            "A name that's a dig at one particular person",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Inappropriate pictures",
          body: [
            "Same goes for your account picture — it sits on your profile and " +
              "next to your name wherever you play.",
            "A moderator can take a picture down without anything else " +
              "happening to your account, and the first time it happens you " +
              "can put a new one up straight away.",
          ],
          examples: [
            "Sexual or graphic images",
            "Hate symbols or extremist imagery",
            "A photo of somebody who didn't agree to be up there",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Playing fair",
      blurb: "The game only works if the guessing is real.",
      rules: [
        {
          id: "cheating",
          heading: "Cheating",
          body: [
            "Don't hand the prompt to anyone who's meant to be guessing it — " +
              "not in chat, not in the drawing, not somewhere outside the " +
              "game. And don't get a program to play for you.",
            "Writing the word on the canvas counts as saying it.",
          ],
          examples: [
            "Writing or spelling out the prompt while you draw it",
            "Telling a friend the prompt over a call or another app",
            "Using a second account to feed yourself answers",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "What happens if you break one",
    body: [
      "Reports go to a moderator, who sees what was actually said or drawn. " +
        "Most of them end with nothing happening — people report things that " +
        "turn out to be fine, and that's exactly what reporting is for.",
      "If something was wrong, a moderator might give you a warning, take a " +
        "picture down, or suspend the account. A warning doesn't restrict " +
        "anything, but another report after one can lead to a suspension. A " +
        "suspension can last a day, a week, a month, or have no end date, and " +
        "you'll be told which.",
      "Whatever happens, you'll be told what it was about and shown your own " +
        "words, or your own drawing, behind it. Nobody is trying to catch you " +
        "out.",
    ],
  },
};
