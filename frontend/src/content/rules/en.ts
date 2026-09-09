import type { RulesDocument } from "./types.ts";

/** The rules, in English.

The reference text: every other locale is a translation of this one, and when
this changes a translation is stale until it follows. Written in the second
person and in plain sentences, because the person most likely to read it is
somebody who has just been told they broke one. */
export const RULES_EN: RulesDocument = {
  locale: "en",
  title: "Rules",
  intro: [
    "Sketchy is a drawing game people play with strangers. Nearly all of it " +
      "works because most people are decent without being asked. These rules " +
      "are for the rest, and they exist so that what a moderator does is " +
      "something you could have seen coming.",
    "They are applied to what you did, not to who you are. A moderator reads " +
      "what was said or drawn, in the order it happened, and decides on that.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "How you treat other people",
      blurb:
        "You are playing with strangers who cannot leave the room without " +
        "leaving the game. That is what these two are about.",
      rules: [
        {
          id: "harassment",
          heading: "Harassment",
          body: [
            "Do not abuse, threaten, demean, or single out other players. " +
              "This covers slurs and hate of every kind, sexual harassment, " +
              "and following somebody from room to room to keep at them.",
            "Losing a round badly is not a reason to take it out on whoever " +
              "won. Neither is somebody drawing something you find bad.",
          ],
          examples: [
            "Insulting a player's drawing to the point that it is about them, not the drawing",
            "Attacks on somebody's race, religion, sex, gender, disability, or nationality",
            "Joining a room to continue an argument from another one",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Do not flood chat, repeat yourself to drown others out, or use " +
              "the game to advertise. Guessing is not spam, however wrong " +
              "the guesses are - guessing quickly is how the game is played.",
          ],
          examples: [
            "Repeating a message until nobody else can follow the round",
            "Posting links or invitations to somewhere else",
            "Pasting the same block of text into room after room",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "What you put in front of people",
      blurb:
        "A drawing, a name, and a picture are all seen by people who did not " +
        "choose to see them. Nobody can look away from the canvas and keep " +
        "playing.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Offensive drawings",
          body: [
            "Draw the prompt. Do not use the canvas for sexual content, " +
              "gore, hateful symbols, or harassment of somebody in the room.",
            "A drawing being bad is not a rule. Being unable to draw is not " +
              "a rule either. This is about what you chose to put there " +
              "instead of the prompt.",
          ],
          examples: [
            "Sexual or graphically violent drawings",
            "Hate symbols, however badly drawn",
            "Drawing an insult about another player rather than the prompt",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Inappropriate names",
          body: [
            "Your display name is seen by everybody you play with. Do not " +
              "use slurs, sexual terms, or a name built to harass somebody. " +
              "Do not impersonate another player or a moderator.",
          ],
          examples: [
            "A name containing a slur or a sexual term",
            "A name chosen to look like somebody else's",
            "A name that is an insult aimed at a specific person",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Inappropriate pictures",
          body: [
            "The same goes for the picture on your account, which is on your " +
              "profile and beside your name wherever you play.",
            "A moderator can remove a picture without doing anything else to " +
              "your account. The first time, you can upload another one " +
              "straight away.",
          ],
          examples: [
            "Sexual or graphic images",
            "Hate symbols or extremist imagery",
            "A photograph of somebody who did not agree to it being there",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Playing fairly",
      blurb: "The game only works if the guessing is real.",
      rules: [
        {
          id: "cheating",
          heading: "Cheating",
          body: [
            "Do not pass the prompt to anybody who is meant to be guessing " +
              "it, whether in chat, in the drawing, or somewhere outside the " +
              "game. Do not use another program to play for you.",
            "Writing the word on the canvas is the same as saying it.",
          ],
          examples: [
            "Writing or spelling out the prompt while drawing it",
            "Telling a friend the prompt over a call or another app",
            "Using more than one account to feed yourself answers",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "What happens if you break one",
    body: [
      "Reports are read by a moderator, who sees what was actually said or " +
        "drawn. Most end in nothing at all: people report things that turn " +
        "out to be fine, and that is what reporting is for.",
      "Where something was wrong, a moderator may give you a warning, remove " +
        "a picture, or suspend the account. A warning restricts nothing, but " +
        "a further report may lead to a suspension. A suspension can be for a " +
        "day, a week, a month, or without an end date, and you are told which.",
      "Whatever is decided, you are told what it was about and shown your own " +
        "words or your own drawing behind it.",
    ],
  },
};
