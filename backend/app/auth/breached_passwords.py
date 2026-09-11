"""Offline screening for passwords a guesser would reach before a brute force.

Screening is done in this process against a list committed beside it, rather
than against an online corpus such as HIBP's range API. Three reasons, in the
order they mattered: the zero-configuration deployment (R-AUTH-05, R-AUTH-12)
must work with no outbound network at all, and a check that silently passes
when it cannot reach a third party is not a check; a password is the one piece
of user data this codebase has never let leave the process, and a k-anonymous
prefix is still a request made because of somebody's password; and an offline
list is testable without a network stub, so the refusal is proved rather than
mocked.

What the list can and cannot do is decided by the length floor above it. At
twelve characters (R-AUTH-19) the published top-100k corpora are almost
entirely spent - they are lists of eight- to ten-character passwords - so
naming them here would refuse nothing the floor had not already refused. The
passwords that survive a length rule are the ones people build *in response* to
one: a short password written twice, a word with a year after it, a keyboard
row walked to its end, the site's own name. Those are shapes rather than
strings, so most of the work here is patterns, and `data/weak_passwords.txt`
carries only the specific long strings that appear often enough to name.

Deliberately not a strength estimator. A score invites a meter, and a meter
invites arguing with it; this answers one question - would this password fall
to a list or a pattern, rather than to a search of the keyspace - and says
which pattern when the answer is yes, because "choose a better password" is
not something somebody can act on.
"""
from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple
from pathlib import Path
import re
import unicodedata


_LIST_PATH = Path(__file__).with_name("data") / "weak_passwords.txt"

# Folded before comparison so a listed password is not defeated by the
# substitution everybody makes. Deliberately one-way and lossy: `pa55w0rd`
# folds onto `password`, and no password is ever unfolded again.
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a", "!": "i"})

# Rows as fingers actually travel them, both directions, plus the diagonals
# that a "complex" password is so often built from.
_WALKS = (
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "azertyuiop",
    "qwertzuiop",
    "1234567890",
    "abcdefghijklmnopqrstuvwxyz",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm",
    "qazwsxedcrfvtgbyhnujmik",
    "1q2w3e4r5t6y7u8i9o0p",
    "!@#$%^&*()",
)

MIN_DISTINCT_CHARACTERS = 5
# Long enough that an ordinary word overlapping the walk by chance is not
# caught, short enough that `qwertyuiopas` is.
MAX_WALK_RUN = 6
# A password is not allowed to be built around the name it protects, the
# address it is reached at, or this service. Below four characters a name is
# too likely to appear inside an unrelated word to refuse on.
MIN_IDENTIFIER_RUN = 4
SERVICE_WORDS = ("sketchy",)


class WeakPasswordError(ValueError):
    """A password refused for what it is rather than for how long it is."""


def _fold(password: str) -> str:
    """Case, accents and leetspeak removed, so one entry catches its variants."""
    decomposed = unicodedata.normalize("NFKD", password)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().translate(_LEET)


@lru_cache(maxsize=1)
def known_weak_passwords() -> frozenset[str]:
    """The committed list, folded once and held for the life of the process."""
    if not _LIST_PATH.exists():
        return frozenset()
    entries = (
        line.strip()
        for line in _LIST_PATH.read_text(encoding="utf-8").splitlines()
    )
    return frozenset(
        _fold(entry) for entry in entries if entry and not entry.startswith("#")
    )


def _shortest_repeated_unit(folded: str) -> str:
    """The block this password is, repeated - or the password itself.

    `abcabcabcabc` is a three-character password typed four times, and it is
    only as strong as `abc`. Found by the standard trick of looking for the
    string inside its own doubled self with the ends cut off: the offset where
    it reappears is the period.
    """
    if not folded:
        return folded
    # The offset at which the string reappears inside its own doubled self is
    # its period; a string that only reappears at the end does not repeat.
    period = (folded + folded).find(folded, 1)
    return folded[:period]


def _longest_walk_run(folded: str) -> int:
    """The longest stretch that is a straight line on the keyboard."""
    longest = 0
    for walk in _WALKS:
        both = (walk, walk[::-1])
        for start in range(len(folded)):
            # A window that is not on the walk cannot become one by growing,
            # so each start stops at its own first miss rather than trying
            # every length - which is what makes this linear in the password
            # rather than cubic in it.
            length = 1
            while start + length <= len(folded):
                window = folded[start : start + length]
                if not any(window in line for line in both):
                    break
                longest = max(longest, length)
                length += 1
    return longest


def _identifier_parts(username: str | None, email: str | None) -> list[str]:
    """The words this password must not be built out of."""
    parts: list[str] = list(SERVICE_WORDS)
    if username:
        parts.append(username)
    if email:
        local, _, domain = email.partition("@")
        parts.append(local)
        # The mailbox provider, not the whole domain: `gmail`, not `gmail.com`.
        parts.extend(piece for piece in domain.split(".")[:-1] if piece)
    return [_fold(part) for part in parts if len(part) >= MIN_IDENTIFIER_RUN]


class ScreeningRefusal(NamedTuple):
    """Why a password was refused: a name for a program, prose for a log.

    The `reason` is what reaches the player - the client writes the sentence
    from it, in their own language (R-I18N-01) - so it is a wire value and is
    added, never renamed. `sentence` stays for the log and for anybody reading
    a response by hand, and `detail` carries the one number a sentence needs.
    """

    reason: str
    sentence: str
    detail: int | None = None


def screening_failure(
    password: str,
    *,
    username: str | None = None,
    email: str | None = None,
) -> ScreeningRefusal | None:
    """Why this password would fall to a list or a pattern, or None.

    Ordered so the most specific answer wins: being on the list is worth
    saying before "too few different characters", which is true of half the
    entries on it and explains less.
    """
    folded = _fold(password)
    if folded in known_weak_passwords():
        return ScreeningRefusal(
            "common",
            "That password is one of the most common ones in use. Please choose another.",
        )

    unit = _shortest_repeated_unit(folded)
    if unit != folded and _fold(unit) in known_weak_passwords():
        return ScreeningRefusal(
            "common_repeated",
            "That is a common password repeated. Please choose another.",
        )
    # A password made of a short block repeated has the strength of the block,
    # whatever the block is: `xk2!xk2!xk2!` is four characters of secret.
    if unit != folded and len(unit) < 8:
        return ScreeningRefusal(
            "short_repeated",
            "That password is a short one repeated. Please choose another.",
        )

    if len(set(folded)) < MIN_DISTINCT_CHARACTERS:
        return ScreeningRefusal(
            "too_few_characters",
            (
                f"That password uses only {len(set(folded))} different characters. "
                "Please choose another."
            ),
            len(set(folded)),
        )

    walk = _longest_walk_run(folded)
    if walk > MAX_WALK_RUN:
        return ScreeningRefusal(
            "keyboard_walk",
            "That password is mostly a run of keys in order. Please choose another.",
        )

    for part in _identifier_parts(username, email):
        if part and part in folded:
            return ScreeningRefusal(
                "contains_identity",
                (
                    "A password must not contain your name, your email address, "
                    "or the name of this site."
                ),
            )

    # A single word with a year or a short run of digits after it is the shape
    # a length rule produces most often, and is guessed by a dictionary with a
    # suffix rule rather than by searching the keyspace.
    stem = re.fullmatch(r"([a-z]+)([0-9]{1,6})", folded)
    if stem is not None and _fold(stem.group(1)) in known_weak_passwords():
        return ScreeningRefusal(
            "common_with_digits",
            "That is a common password with digits added. Please choose another.",
        )

    return None
