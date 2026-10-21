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
// A solve time, to the tenth of a second.
const tenths = new Intl.NumberFormat("en", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const SOLO_EN = {
    intro: "Guess drawings from public games you were not in. Who drew them stays a secret.",
    daily: "Daily",
    playDaily: "Play the Daily",
    continueDaily: (p: { left: number }) => `Continue · ${number(p.left)} left`,
    named: "Named",
    missed: "Missed",
    dailyDone: (p: { points: number }) => `Done for today: ${number(p.points)} points`,
    noDailyToday: "No Daily today: there are not enough drawings yet. Try a free run.",
    nextDailyIn: (p: { time: string }) => `Next Daily in ${p.time}`,
    freeRun: "Free run",
    quick: "Quick",
    classic: "Classic",
    endless: "Endless",
    best: "Best",
    start: "Start",
    startNamed: (p: { name: string }) => `Start ${p.name}`,
    startOver: "Start over",
    startOverNamed: (p: { name: string }) => `Start ${p.name} over`,
    startOverTitle: (p: { name: string }) => `${p.name}: start over?`,
    startOverFinite: (p: { played: number; length: number; points: number }) =>
      `The run in play ends here and keeps nothing: ${number(p.played)} of ${number(p.length)} played, ${counted(p.points, { one: "point", other: "points" })}.`,
    startOverEndless: (p: { count: number }) =>
      `The run in play ends here, at ${number(p.count)} in a row. That still counts toward your best.`,
    startOverEndlessNothing: "The run in play ends here, with nothing named yet.",
    continueRun: "Continue",
    continueNamed: (p: { name: string }) => `Continue ${p.name}`,
    runProgress: (p: { played: number; length: number; points: number }) =>
      `${number(p.played)}/${number(p.length)} · ${counted(p.points, { one: "point", other: "points" })}`,
    inARow: (p: { count: number }) => `${number(p.count)} in a row`,
    streakToGoal: (p: { days: number; goal: number }) =>
      `${counted(p.days, { one: "day", other: "days" })} in a row; the next milestone is ${counted(p.goal, { one: "day", other: "days" })}`,
    streakReached: (p: { days: number }) => `${counted(p.days, { one: "day", other: "days" })} in a row: a new milestone`,
    previousMonth: "Previous month",
    nextMonth: "Next month",
    missedDay: "missed day",
    underWay: (p: { played: number; total: number }) => `Started: ${number(p.played)} of ${number(p.total)} played`,
    noDaily: "No Daily",
    stillToCome: "Still to come",
    toPlayToday: "Today's Daily, to play",
    calendarDay: (p: { date: string; status: string }) => `${p.date}: ${p.status}`,
    dailiesPlayed: "Dailies played",
    namedShare: "named",
    longestStreak: "longest streak",
    playPast: "Play",
    continuePast: "Continue",
    review: "Review",
    reviewPick: (p: { position: number; prompt: string }) => `Drawing ${number(p.position)}: ${p.prompt}`,
    calendarDayAction: (p: { date: string; status: string; action: string }) => `${p.date}: ${p.status}. ${p.action}`,
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
    plusPoints: (p: { points: number }) => `+${number(p.points)} points`,
    secondsTaken: (p: { seconds: number }) => `${tenths.format(p.seconds)} s`,
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
    shareHeld: "Shared: it joins the Gallery once today's Daily is over everywhere.",
    react: "React",
    share: "Share",
    shared: "Shared",
    reportShort: "Report",
    shareTakenOut: "Its drawer keeps it out of the Gallery.",
    backToSolo: "Back to Solo",
    couldNotLoad: "Solo could not be loaded.",
    couldNotLoadDrawing: "This drawing could not be loaded.",
    cannotBeNamed: "This one can no longer be named, so it can only be given up.",
    promptGone: "No longer available",
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
