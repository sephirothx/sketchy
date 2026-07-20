"""Static word list used for round word selection."""
import random

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


def random_word_choices(count: int = 3, exclude: set[str] | None = None) -> list[str]:
    """Return `count` unique random words, optionally excluding already-used ones."""
    pool = [w for w in WORDS if not exclude or w not in exclude]
    if len(pool) < count:
        pool = WORDS
    return random.sample(pool, count)
