/** Solo's page (#1434), in English: everything `/solo` says.

Kept apart from `content/ui/` so it loads with the page rather than with every
first visit - the catalogue for the interface is in the first-load budget
(#475), and a page most visits never open has no business in it. The few words
other screens need (the header link, the lobby button, the drawer's controls)
stay in `ui.solo`. The reference: the other locales are typed against it.
*/
import { formattersFor } from "../ui/format.ts";

// No ordinals on this page: the suffixes are never read.
const { counted, number } = formattersFor("en", { other: "" });

export const SOLO_EN = {
    intro: "Guess drawings from public games you were not in. Who drew them stays a secret.",
    daily: "Daily",
    dailyIntro: "Five drawings, the same for everybody. A new set every midnight.",
    playDaily: "Play the Daily",
    continueDaily: (p: { played: number }) => `Continue (${number(p.played)}/5)`,
    dailyDone: (p: { points: number }) => `Done for today: ${number(p.points)} points`,
    noDailyToday: "No Daily today: there are not enough drawings yet. Try a free run.",
    nextDailyIn: (p: { time: string }) => `Next Daily in ${p.time}`,
    freeRun: "Free run",
    freeRunIntro: "Play as many as you like. An unlimited run ends at the first miss.",
    drawingsCount: (p: { count: number }) => counted(p.count, { one: "drawing", other: "drawings" }),
    unlimited: "Unlimited",
    continueRun: "Continue your run",
    supporterPreview: "Unlimited runs and past Dailies are going to be supporter perks. Until then they are open to everybody.",
    bests: "Your bests",
    bestFive: "5 drawings",
    bestTen: "10 drawings",
    bestUnlimited: "Unlimited",
    pointsValue: (p: { points: number }) => counted(p.points, { one: "point", other: "points" }),
    inARow: (p: { count: number }) => `${number(p.count)} in a row`,
    noBestYet: "Not played yet",
    streak: (p: { days: number }) => `${counted(p.days, { one: "day", other: "days" })} in a row`,
    yourDailies: "Your Dailies",
    noDailiesYet: "The Dailies you play will be listed here.",
    pastDailies: "Past Dailies",
    pastDailiesIntro:
      "Play a Daily you missed, finish one you left, or play one again. A past Daily never counts toward your streak, and playing one again is not recorded.",
    noPastDailies: "There are no past Dailies yet.",
    playPast: "Play",
    continuePast: "Continue",
    playAgain: "Play it again",
    showOlder: "Show older",
    notRecorded: "Not recorded",
    playedAgain: "Played again",
    drawingOf: (p: { position: number; length: number | null }) =>
      p.length === null ? `Drawing ${number(p.position)}` : `Drawing ${number(p.position)} of ${number(p.length)}`,
    secondsLeft: (p: { seconds: number }) => `${number(p.seconds)} s`,
    typeYourGuess: "Type your guess…",
    guess: "Guess",
    giveUp: "Give up",
    veryClose: "Very close!",
    someWordsRight: "Some of the words are right.",
    notIt: (p: { guess: string }) => `Not "${p.guess}".`,
    gotIt: "You got it!",
    timeUp: "Time's up",
    gaveUp: "You gave up",
    itWas: "It was",
    plusPoints: (p: { points: number }) => `+${number(p.points)} points`,
    next: "Next drawing",
    seeResult: "See the result",
    runOver: "Run over",
    dailyComplete: "Daily complete",
    youNamed: (p: { solved: number; total: number }) => `You named ${number(p.solved)} of ${number(p.total)}`,
    totalPoints: (p: { points: number }) => `${number(p.points)} points`,
    newBest: "New personal best!",
    copyResult: "Copy result",
    copied: "Copied",
    resultText: (p: { daily: string; date: string; marks: string; points: number }) =>
      `Sketchy ${p.daily} ${p.date}\n${p.marks} ${number(p.points)}`,
    shareToGallery: "Share to Gallery",
    sharedToGallery: "Shared to Gallery",
    shareHeld: "Shared: it joins the Gallery once today's Daily is over everywhere.",
    shareTakenOut: "Its drawer keeps it out of the Gallery.",
    anonymity: "Who drew it stays a secret. Share it, and it goes in the Gallery under its drawer's name.",
    backToSolo: "Back to Solo",
    couldNotLoad: "Solo could not be loaded.",
    couldNotLoadDrawing: "This drawing could not be loaded.",
    couldNotSaveAnswer: "Your answer could not be saved.",
    tryAgain: "Try again",
    signInToPlay: "Sign in to play Solo",
    signInBody: "Or choose a name in the lobby, then create an account.",
    accountToPlay: "Create an account to play Solo",
    accountBody: "Your Daily, your bests and your streak are kept with your account.",
    createAccount: "Create an account",
    backToLobby: "Back to lobby",
    report: "Report this drawing",
    optOut: "Let Solo players guess my public drawings",
    optOutHint: "Solo never shows who drew a drawing. Turn this off and none of yours is served to anybody.",
    takeOutOfSolo: "Take out of Solo",
    putBackInSolo: "Put back in Solo",
};

export type SoloCopy = typeof SOLO_EN;
