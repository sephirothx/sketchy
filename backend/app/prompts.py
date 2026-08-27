"""Static prompt list used for turn prompt selection."""
import random
import re

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
