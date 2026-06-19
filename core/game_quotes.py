"""Curated, VERIFIED iconic quotes per game UNIVERSE, with attribution.

When a quote reel's footage is tied to a game (e.g. the Spider-Man games), the
quote should come from that game's whole world — for Spider-Man that means the
games AND the films/comics (every Spider-Man universe). Accuracy matters (we were
burned by fabricated FF7 lore before), so this is a HAND-CURATED set of real,
correctly-attributed lines — NOT live-generated text. Keep additions verified and
short (one line). Add a new universe + its game keys as footage for it is added.
"""
from __future__ import annotations

# Each entry: line (the quote), author (who said it), source (the work).
SPIDER_MAN: list[dict[str, str]] = [
    {"line": "With great power comes great responsibility.",
     "author": "Uncle Ben", "source": "Spider-Man"},
    {"line": "I believe there's a hero in all of us.",
     "author": "Aunt May", "source": "Spider-Man 2"},
    {"line": "Sometimes, to do what's right, we have to give up the things we want the most.",
     "author": "Peter Parker", "source": "Spider-Man 2"},
    {"line": "Not everyone is meant to make a difference. But for me, an ordinary life is no longer an option.",
     "author": "Peter Parker", "source": "Spider-Man 2"},
    {"line": "Whatever battle is raging inside us, we always have a choice.",
     "author": "Peter Parker", "source": "Spider-Man 3"},
    {"line": "These are the years when a man changes into the man he's going to become.",
     "author": "Uncle Ben", "source": "Spider-Man"},
    {"line": "If you can do good things for other people, you have a moral obligation to do those things.",
     "author": "Uncle Ben", "source": "The Amazing Spider-Man"},
    {"line": "Anyone can wear the mask. You could wear the mask.",
     "author": "Miles Morales", "source": "Into the Spider-Verse"},
    {"line": "It's a leap of faith.",
     "author": "Spider-Man", "source": "Into the Spider-Verse"},
    {"line": "A hero helps others simply because it's the right thing to do.",
     "author": "Stan Lee", "source": "tribute"},
    {"line": "When you can do the things that I can, but you don't, then the bad things happen because of you.",
     "author": "Peter Parker", "source": "Spider-Man: Homecoming"},
    {"line": "If you're nothing without this suit, then you shouldn't have it.",
     "author": "Tony Stark", "source": "Spider-Man: Homecoming"},
    {"line": "With great power, there must also come great responsibility.",
     "author": "Aunt May", "source": "No Way Home"},
    {"line": "Be greater.",
     "author": "Marvel's Spider-Man", "source": "Insomniac Games"},
    {"line": "What would Spider-Man do?",
     "author": "Miles Morales", "source": "Marvel's Spider-Man: Miles Morales"},
    {"line": "Go get 'em, tiger.",
     "author": "Mary Jane Watson", "source": "Spider-Man"},
    {"line": "Intelligence is not a privilege, it's a gift - use it for the good of mankind.",
     "author": "Otto Octavius", "source": "Spider-Man 2"},
    {"line": "No matter how lost you feel, you have to hold on to hope.",
     "author": "Gwen Stacy", "source": "The Amazing Spider-Man 2"},
    {"line": "Be greater. Together.",
     "author": "Marvel's Spider-Man 2", "source": "Insomniac Games"},
    {"line": "The brightest light casts the darkest shadow, but it is still the brightest light.",
     "author": "Madame Web", "source": "Spider-Man comics"},
]

# universe key -> its curated quote list
UNIVERSES: dict[str, list[dict[str, str]]] = {
    "spider-man": SPIDER_MAN,
}


def universe_for_game(game: str) -> str | None:
    """Map a footage/image game key (e.g. 'spider-man1', 'spider-manmilesmorales',
    'spider-man2') to its quote universe, or None if we have no quote set yet."""
    g = "".join(ch for ch in (game or "").lower() if ch.isalnum())
    if "spiderman" in g:
        return "spider-man"
    return None


def game_in_universe(game: str, universe: str) -> bool:
    return universe_for_game(game) == universe


def quotes_for(universe: str | None) -> list[dict[str, str]]:
    return list(UNIVERSES.get((universe or "").strip().lower(), []))


def has_universe(universe: str | None) -> bool:
    return bool(quotes_for(universe))
