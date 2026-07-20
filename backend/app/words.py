"""Static word list used for round word selection."""
import random

MAX_CUSTOM_WORDS = 10000
MAX_WORD_LENGTH = 32
# python-socketio/engineio defaults to a 1,000,000 byte max message size, so we
# cap the raw payload well below that (comfortably fits MAX_CUSTOM_WORDS entries
# at MAX_WORD_LENGTH chars each, plus separators) while still guarding against
# pathological inputs (e.g. a string made of huge numbers of commas).
MAX_RAW_INPUT_LENGTH = 400_000

WORDS: list[str] = [
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


def random_word_choices(
    count: int = 3,
    exclude: set[str] | None = None,
    pool: list[str] | None = None,
) -> list[str]:
    """Return up to `count` unique random words from `pool` (or the default WORDS list).

    Falls back to the full pool (ignoring `exclude`) once too few unused words
    remain, and shrinks `count` itself if the pool is smaller than requested
    (relevant for short custom word lists).
    """
    source = pool or WORDS
    available = [w for w in source if not exclude or w not in exclude]
    if len(available) < count:
        available = source
    return random.sample(available, min(count, len(available)))


def parse_custom_word_list(raw: str) -> list[str]:
    """Parse a comma-separated string of custom words/expressions into a clean, deduped list.

    Entries may be multi-word expressions (e.g. "red panda"), not just single
    words. Blank entries and duplicates (case-insensitive) are dropped,
    entries longer than `MAX_WORD_LENGTH` are rejected, and the overall list
    is capped to avoid abuse via an excessively large payload.
    """
    seen: set[str] = set()
    words: list[str] = []
    for part in raw[:MAX_RAW_INPUT_LENGTH].split(","):
        word = part.strip()
        if not word or len(word) > MAX_WORD_LENGTH:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= MAX_CUSTOM_WORDS:
            break
    return words
