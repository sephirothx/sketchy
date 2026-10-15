"""Whether a guess names a prompt, and how near a wrong one came.

Pure: no game, no room, no I/O. A room's `Game` and Solo (#1434) both judge
through `judge`, so the two can never disagree about what a guess is.
`fixtures/guess_judge_cases.json` records its verdicts, for the TypeScript
port Solo plays with to be held to.

A port has to reproduce the Python behaviour the corpus pins, not an
approximation of it: `difflib`'s ratio depends on which string comes first
(`_is_close_pair` passes the guess first); a length is counted in code points,
not UTF-16 units (`fits_a_guess`); `str.split` breaks on every character
`str.isspace` accepts, \x1c-\x1f and \x85 among them; and `_fold_accents`
drops what `unicodedata.combining` says is a mark, which is not exactly
Unicode's Mark category.

A target is the prompt as one guesser plays it: their own language's answer
and aliases, the other languages somebody in the game plays it in (a
mixed-language room, #1182), and the spellings that already mean something
else to the guesser (the false-friend guard, #1367). A single-language game
has no other languages and nothing taken, which is every branch below that
mentions them doing nothing.
"""
from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from app.prompt_content import (
    prompt_match_extra_words,
    prompt_match_variants,
    prompt_match_words,
)
from app.prompts import MAX_PROMPT_LENGTH

# Close guess detection (see `judge`):
# - distance 1 (a single insertion/deletion/substitution/transposition) is
#   always considered close.
# - distance >1 and <= CLOSE_GUESS_MAX_DISTANCE is close if the strings are
#   still similar enough overall (difflib ratio).
# - for multi-word prompts, words are matched position-independently (as a
#   bag/multiset, so reordered guesses still count) as long as the guess's
#   word count is within 1 of the target's. One or more correct words whose
#   combined length is at least CLOSE_GUESS_MIN_CORRECT_LETTERS letters is
#   flagged separately as a "some words are correct" hint.
CLOSE_GUESS_MAX_DISTANCE = 2
CLOSE_GUESS_SIMILARITY_THRESHOLD = 0.75
CLOSE_GUESS_MIN_CORRECT_LETTERS = 5
# A message holding the prompt as whole words - "der Hund" - is kept from the
# room whatever its length (#1416). Its author is told it is close only when
# it holds at most this many other words: a verdict on a longer message would
# answer "is it any of these eighty words?" in one go, and a guesser could
# halve a list to the answer without looking at the drawing.
HELD_VERDICT_MAX_EXTRA_WORDS = 1

def _accepted_spellings(text: str, language: str = "en") -> frozenset[str]:
    """Every spelling of `text` its language accepts (R-GUESS-01).

    Deciding whether a guess is right asks this rather than `_normalize`: a
    German answer is written both "maedchen" and "madchen", and no single key
    can be both. Everything else - which prompt this was, how close a wrong
    guess came - stays on the canonical key, so a wider accept set cannot
    widen anything it was not meant to.
    """
    return prompt_match_variants(text, language)


def _bounded_damerau_levenshtein(a: str, b: str, max_distance: int) -> int:
    """Bounded Damerau-Levenshtein distance (optimal string alignment variant).

    Returns ``max_distance + 1`` when the distance exceeds the requested
    bound. Only the diagonal band that could still produce an in-bound result
    is evaluated, and only three sparse rows are retained for adjacent
    transpositions.

    The distance counts single-character insertions, deletions, substitutions, or
    transpositions of two adjacent characters to turn `a` into `b`.

    Counting adjacent transpositions as a single edit (rather than two
    substitutions) matters for a guessing game, since swapped letters are one
    of the most common typos (e.g. "hte" for "the").
    """
    over_limit = max_distance + 1
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return over_limit
    if not a:
        return len(b) if len(b) <= max_distance else over_limit
    if not b:
        return len(a) if len(a) <= max_distance else over_limit
    len_b = len(b)

    previous_previous: dict[int, int] = {}
    previous = {j: j for j in range(min(len_b, max_distance) + 1)}
    for i, ch_a in enumerate(a, start=1):
        current: dict[int, int] = {}
        first_column = max(0, i - max_distance)
        last_column = min(len_b, i + max_distance)
        if first_column == 0:
            current[0] = i
        for j in range(max(1, first_column), last_column + 1):
            ch_b = b[j - 1]
            insert_cost = current.get(j - 1, over_limit) + 1
            delete_cost = previous.get(j, over_limit) + 1
            substitute_cost = previous.get(j - 1, over_limit) + (ch_a != ch_b)
            best = min(insert_cost, delete_cost, substitute_cost)
            if i > 1 and j > 1 and ch_a == b[j - 2] and a[i - 2] == ch_b:
                best = min(best, previous_previous.get(j - 2, over_limit) + 1)
            current[j] = min(best, over_limit)
        previous_previous, previous = previous, current
    return previous.get(len_b, over_limit)


def _near_miss(guess: str, answers: Sequence[str]) -> str | None:
    """"close" if the guess is near a whole answer, "partial" if enough of a
    multi-word answer's words are in it, else None (see `judge`).
    Both sides are `prompt_match_words` spellings, words apart."""
    # Close is measured with the separators gone, as acceptance compares:
    # "hang glider" and "hangglidr" are one typo apart, not two.
    if any(_is_close_pair(guess.replace(" ", ""), answer.replace(" ", "")) for answer in answers):
        return "close"
    guess_tokens = guess.split(" ")
    for answer in answers:
        word_tokens = answer.split(" ")
        if len(word_tokens) <= 1 or abs(len(guess_tokens) - len(word_tokens)) > 1:
            continue
        # Bag-of-words intersection: matches regardless of word order,
        # capping duplicate words at the lower count on either side.
        overlap = Counter(guess_tokens) & Counter(word_tokens)
        correct_letter_count = sum(
            len(word) * count for word, count in overlap.items()
        )
        if correct_letter_count >= CLOSE_GUESS_MIN_CORRECT_LETTERS:
            return "partial"
    return None


def fits_a_guess(text: str) -> bool:
    """Whether a message is short enough to be judged as a guess at all.

    No answer is longer than `MAX_PROMPT_LENGTH`, so anything longer is chat.
    Measured with whitespace collapsed, as matching folds it: counting the
    raw text sent a 32-character answer typed with one doubled space to the
    room as chat, unjudged (#1416).
    """
    return len(" ".join(text.split())) <= MAX_PROMPT_LENGTH


def _is_close_pair(guess: str, target: str) -> bool:
    """Whether `guess` is close to `target` (already known to differ).

    Very short strings are skipped to avoid trivial/noisy matches (e.g. a
    guess of "a" being "close" to a 3-letter word just by sharing a letter).
    """
    if len(target) < 3 or len(guess) < 2 or guess == target:
        return False
    if abs(len(guess) - len(target)) > CLOSE_GUESS_MAX_DISTANCE:
        return False
    distance = _bounded_damerau_levenshtein(
        guess,
        target,
        CLOSE_GUESS_MAX_DISTANCE,
    )
    if distance == 1:
        return True
    if distance <= CLOSE_GUESS_MAX_DISTANCE:
        return difflib.SequenceMatcher(None, guess, target).ratio() >= CLOSE_GUESS_SIMILARITY_THRESHOLD
    return False


Verdict = Literal["correct", "close", "partial", "another_language", "held"]


@dataclass(frozen=True, slots=True)
class AnswerForm:
    """One language's answer and its aliases, as written."""

    answer: str
    aliases: tuple[str, ...] = ()

    def spellings(self) -> tuple[str, ...]:
        return (self.answer, *self.aliases)


@dataclass(frozen=True, slots=True)
class JudgeTarget:
    """The prompt as one guesser plays it.

    `language` folds the guesser's text; `own` is the prompt in it. `others`
    are the forms in the other languages somebody in the game plays, each
    folded in its own language - never the guesser's own, and empty outside a
    mixed-language room. `taken` are spellings, in the guesser's fold, that
    are a different concept to them: another language's form that is one of
    them does not win (#1367).
    """

    language: str
    own: AnswerForm
    others: Mapping[str, AnswerForm] = field(default_factory=dict)
    taken: frozenset[str] = frozenset()


def own_spellings(target: JudgeTarget) -> frozenset[str]:
    """The guesser's own answer and aliases, in their fold."""
    return frozenset().union(
        *(_accepted_spellings(answer, target.language) for answer in target.own.spellings())
    )


def accepted_spellings(target: JudgeTarget) -> frozenset[str]:
    """Every spelling that wins: the guesser's own, and each other language's
    folded its own way, less what is taken."""
    spellings = own_spellings(target)
    for other, form in target.others.items():
        for answer in form.spellings():
            spellings = spellings | (_accepted_spellings(answer, other) - target.taken)
    return spellings


def near_miss_keys(target: JudgeTarget) -> tuple[str, ...]:
    """The guesser's own answer and aliases as `prompt_match_words` spells
    them: a near miss is measured against these only (R-GUESS-01)."""
    return tuple(
        dict.fromkeys(
            prompt_match_words(answer, target.language) for answer in target.own.spellings()
        )
    )


def judge(text: str, target: JudgeTarget) -> Verdict | None:
    """What a guess is: `"correct"`, or what its author is told about a wrong
    one - `"close"` (near a whole answer, `_is_close_pair`), `"partial"`
    (enough of a multi-word answer's words), `"another_language"` (the
    prompt in a language the false-friend guard refused, or near it), or
    `"held"` (the prompt as whole words amid more than
    `HELD_VERDICT_MAX_EXTRA_WORDS` others: kept private, answered as wrong).
    `None` is a plain wrong guess - or chat, when it does not `fits_a_guess`.

    Judged at any length: a correct answer folds to the answer however it was
    typed (#1416). A message holding the prompt as whole words is kept from
    the room at any length too, since it does not score (N-20) and broadcast
    it would hand the room the bare word.
    """
    guessed = _accepted_spellings(text, target.language)
    accepted = accepted_spellings(target)
    if not guessed.isdisjoint(accepted):
        return "correct"
    if _spells_the_prompt_elsewhere(guessed, target):
        # Another language's spelling the false-friend guard refused: not this
        # guesser's answer, but broadcast it and the seats playing that
        # language read their own answer in the chat (#1182, #1367).
        return "another_language"
    held = _held_verdict(text, target, accepted)
    if held is not None:
        return held
    if not fits_a_guess(text):
        return None
    verdict = _near_miss(prompt_match_words(text, target.language), near_miss_keys(target))
    if verdict is not None:
        return verdict
    # Near another language's spelling: the room must not see it either, or
    # the seats playing that language read their answer in a typo ("dogs"
    # from a German seat). Measured in that language's fold.
    for other, form in target.others.items():
        answers = tuple(
            dict.fromkeys(prompt_match_words(answer, other) for answer in form.spellings())
        )
        verdict = _near_miss(prompt_match_words(text, other), answers)
        if verdict is not None:
            return verdict
    return None


def _spells_the_prompt_elsewhere(guessed: frozenset[str], target: JudgeTarget) -> bool:
    """Whether a guess is the prompt as another language in play spells it."""
    return any(
        not guessed.isdisjoint(_accepted_spellings(answer, other))
        for other, form in target.others.items()
        for answer in form.spellings()
    )


def _held_verdict(text: str, target: JudgeTarget, accepted: frozenset[str]) -> Verdict | None:
    """Whether a wrong guess holds the prompt as whole words, and what its
    author is told.

    Measured against the guesser's own spellings and those of the languages
    in play: the words a guesser in this room could type to win. Every
    language's would hide ordinary chat for nothing - French "thé" folds to
    "the" in a room nobody plays French in.
    """
    extra = prompt_match_extra_words(text, target.language, own_spellings(target) | accepted)
    if extra is not None:
        return "close" if extra <= HELD_VERDICT_MAX_EXTRA_WORDS else "held"
    # Another language's word that is a different prompt to this guesser
    # (#1367): still the drawing to the seats playing it.
    in_play = frozenset().union(
        *(
            _accepted_spellings(answer, other)
            for other, form in target.others.items()
            for answer in form.spellings()
        )
    )
    extra = prompt_match_extra_words(text, target.language, in_play - accepted)
    if extra is not None:
        return "another_language" if extra <= HELD_VERDICT_MAX_EXTRA_WORDS else "held"
    return None
