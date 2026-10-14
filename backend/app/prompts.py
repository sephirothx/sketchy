"""Static prompt list used for turn prompt selection."""
import functools
import random
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from string import ascii_lowercase

# Quick prompts are typed into a room and held in memory for as long as it
# lives, on a server that owns every room in one process. Ten thousand was
# sized against what one message could carry rather than what one room should
# cost; this is sized against the room. An owned prompt list remains the place
# for a large curated set - it is stored once, not per room.
MAX_CUSTOM_PROMPTS = 2000
MAX_PROMPT_LENGTH = 32
# Comfortably fits MAX_CUSTOM_PROMPTS entries at MAX_PROMPT_LENGTH characters
# each plus separators (66,000), while still guarding against pathological
# input such as a string made entirely of commas. Well under the 1,000,000
# byte message ceiling python-socketio/engineio defaults to, which is the
# limit this used to be sized against.
MAX_RAW_INPUT_LENGTH = 80_000

PROMPTS: list[str] = [
    "apple", "banana", "airplane", "guitar", "elephant", "bicycle", "castle",
    "dragon", "umbrella", "volcano", "penguin", "rainbow", "sandwich", "robot",
    "spaceship", "octopus", "waterfall", "campfire", "skateboard", "telescope",
    "lighthouse", "snowman", "butterfly", "pirate", "dinosaur", "mountain",
    "kangaroo", "helicopter", "cactus", "avocado", "unicorn", "jellyfish",
    "windmill", "volleyball", "saxophone", "compass", "anchor", "balloon",
    "beehive", "cupcake", "fireworks", "glacier", "hammock", "igloo",
    "jackpot", "koala", "lantern", "mermaid", "necklace", "orchestra",
    "pancake", "quicksand", "rocket", "scarecrow", "treasure", "volcano",
    "wizard", "xylophone", "yacht", "zeppelin", "backpack", "chandelier",
]


def random_prompt_choices(
    count: int = 3,
    exclude: set[str] | None = None,
    pool: list[str] | None = None,
) -> list[str]:
    """Return up to `count` unique random prompts from `pool` (or the default PROMPTS list).

    Falls back to the full pool (ignoring `exclude`) once too few unused prompts
    remain, and shrinks `count` itself if the pool is smaller than requested
    (relevant for short custom prompt lists).
    """
    source = pool or PROMPTS
    available = [w for w in source if not exclude or w not in exclude]
    if len(available) < count:
        available = source
    return random.sample(available, min(count, len(available)))


def parse_custom_prompt_list(raw: str) -> list[str]:
    """Parse comma- or newline-separated custom prompts into a clean, deduped list.

    Entries may be several words long (e.g. "red panda"), not just single
    words. Blank entries and duplicates (case-insensitive) are dropped,
    entries longer than `MAX_PROMPT_LENGTH` are rejected, and the overall list
    is capped to avoid abuse via an excessively large payload.
    """
    seen: set[str] = set()
    prompts: list[str] = []
    for part in re.split(r"[,\r\n]+", raw[:MAX_RAW_INPUT_LENGTH]):
        prompt = part.strip()
        if not prompt or len(prompt) > MAX_PROMPT_LENGTH:
            continue
        key = prompt.lower()
        if key in seen:
            continue
        seen.add(key)
        prompts.append(prompt)
        if len(prompts) >= MAX_CUSTOM_PROMPTS:
            break
    return prompts


# Letters NFD leaves whole, read as the a-z key a keyboard without them types.
# A ligature is both of its letters. The language transliterations of guess
# matching stay out of it: on the wheel "ä" is an "a" with a mark, not "ae".
_WHEEL_LETTERS = {
    "ł": "l", "ø": "o", "đ": "d", "ð": "d", "ħ": "h", "ı": "i", "ŀ": "l",
    "þ": "th", "œ": "oe", "æ": "ae", "ĳ": "ij",
}


@functools.lru_cache(maxsize=4096)
def wheel_letters(character: str) -> str:
    """The a-z keys that reveal `character` on the Wheel of Fortune (#1384).

    The wheel has 26 keys - more is what #1267 had to undo on phones - so a
    bought letter reveals its accented forms too: "e" shows é, è, ê and ë,
    "z" shows ż and ź, "s" shows ß. It is the fold guess matching applies
    (`prompt_content._fold_accents` after case-folding, which makes ß "ss"),
    plus `_WHEEL_LETTERS` for the letters NFD cannot decompose; a ligature is
    revealed by either of its letters. Anything that is no a-z letter by
    either - a digit, a letter of another script - gives "".

    Cached per character: a list's histogram asks about each distinct
    character it holds, a few dozen, rather than every one. Bounded, since a
    room's custom prompts may hold any character there is.
    """
    decomposed = unicodedata.normalize("NFD", character.casefold())
    folded = "".join(
        _WHEEL_LETTERS.get(letter, letter)
        for letter in decomposed
        if not unicodedata.combining(letter)
    )
    return "".join(dict.fromkeys(letter for letter in folded if "a" <= letter <= "z"))


def letter_histogram(answers: Iterable[str]) -> tuple[dict[str, int], int]:
    """Count the wheel's a-z letters across `answers`, plus the total
    alphabetic characters.

    Wheel pricing asks how common a letter is among the solutions a game can
    draw, which is a distribution rather than the words themselves - so it can
    be precomputed per prompt-list revision and summed, leaving the prompts in
    the database. A letter counts toward every key that reveals it
    (`wheel_letters`), so "ż" prices "z" as it is revealed by it. The divisor
    counts each alphabetic character once, a ligature included, so the ratios
    are of letters as written.
    """
    characters = Counter(
        char
        for answer in answers
        for char in answer.lower()
        if char.isalpha()
    )
    counts: Counter[str] = Counter()
    for char, count in characters.items():
        for letter in wheel_letters(char):
            counts[letter] += count
    return (
        {letter: counts[letter] for letter in ascii_lowercase if counts[letter]},
        sum(characters.values()),
    )
