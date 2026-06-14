"""Per-game story bibles for the captioning agent.

The vision captioner used to guess wrong (e.g. "Peter sneaks into the villain's
lab" — it's actually Otto Octavius's lab where Peter WORKS as his research
partner). Knowing what's literally on screen isn't enough; the agent also needs
the game's story, characters, locations and common look-alike confusions so it
can map a clip to the RIGHT moment.

lore_for(game) returns a compact, accurate brief that gets injected into the
caption prompt. Unknown games return "" (the prompt simply omits the brief).
"""
from __future__ import annotations

# Keep each brief dense but accurate. Lead with the protagonist, then the people
# / places the agent is most likely to see, then the "DON'T CONFUSE" notes that
# fix the exact mistakes a vision model tends to make for that title.
GAME_LORE: dict[str, str] = {
    "spider-man1": (
        "MARVEL'S SPIDER-MAN (2018) — an experienced Peter Parker (8 years as "
        "Spider-Man).\n"
        "KEY PEOPLE:\n"
        "- Peter Parker / Spider-Man. Day job: research scientist working as Otto "
        "Octavius's lab partner/assistant at Octavius Industries (a small private "
        "lab) building advanced neural-prosthetic arms. In the lab in a shirt/"
        "lab-coat = Peter AT WORK, not an intruder.\n"
        "- Otto Octavius: brilliant scientist, Peter's mentor, friend and employer. "
        "Becomes DOCTOR OCTOPUS (Doc Ock) only in the final act. Early/mid game he "
        "is a friendly ally in the lab, NOT yet a villain.\n"
        "- Mary Jane (MJ) Watson: Daily Bugle investigative reporter, Peter's ex; "
        "has her own stealth sections (no powers, sneaks/photographs).\n"
        "- Miles Morales: a TEENAGER and civilian volunteer at the F.E.A.S.T. "
        "shelter. He is NOT Spider-Man in this game (he's bitten by the spider only "
        "at the very end). A young Black teen in a hoodie = Miles the civilian.\n"
        "- Wilson Fisk / KINGPIN: crime boss; the game's OPENING boss fight, then "
        "arrested.\n"
        "- Mister Negative / Martin Li: runs the F.E.A.S.T. shelter by day, leads "
        "the Inner Demons (glowing white/black powers) by night. Major villain.\n"
        "- Norman Osborn: MAYOR of NYC and Oscorp founder (a political antagonist "
        "here — he is NOT the Green Goblin in this game).\n"
        "- Yuri Watanabe: NYPD police captain, Spidey's radio ally.\n"
        "- Silver Sable: mercenary leading Sable International (armoured soldiers).\n"
        "- Aunt May: volunteers at F.E.A.S.T.\n"
        "- Sinister Six (late game): Doc Ock, Mister Negative, Electro, Vulture, "
        "Rhino, Scorpion.\n"
        "PLACES: Octavius's lab, F.E.A.S.T. shelter, Daily Bugle, Empire State "
        "University, Oscorp, The Raft (island prison), open-world Manhattan.\n"
        "STORY BEATS: arrest Kingpin (intro) -> research with Otto -> Mister "
        "Negative's Devil's Breath bioweapon plot -> Raft breakout frees the "
        "Sinister Six -> Otto becomes Doc Ock -> final fight vs Doc Ock.\n"
        "DON'T CONFUSE: the lab is Otto's/Peter's workplace (not a 'villain's lab' "
        "and Peter is not 'sneaking in'); the teen at the shelter is Miles the "
        "civilian (not Spider-Man); the man in the lab with Peter is Otto the "
        "mentor (not an enemy)."
    ),
    "spider-man-miles": (
        "MARVEL'S SPIDER-MAN: MILES MORALES (2020) — a NEW, still-learning Miles "
        "Morales as Spider-Man, over a snowy Christmas in Harlem, NYC. Peter Parker "
        "is away in Symkaria, so Miles guards the city.\n"
        "KEY PEOPLE:\n"
        "- Miles Morales / Spider-Man: has unique bio-electric VENOM powers (glowing "
        "yellow/blue electric blasts) and camouflage/invisibility. NOTE: 'Venom' "
        "here means his ELECTRIC powers — NOT the alien symbiote or Eddie Brock.\n"
        "- Rio Morales: Miles's mother, running for City Council.\n"
        "- Phin Mason / THE TINKERER: Miles's childhood best friend; leader of the "
        "Underground (purple-tech crew). The game's sympathetic antagonist.\n"
        "- Roxxon Energy / Simon Krieger: corrupt energy corporation; the Underground "
        "vs Roxxon fight over the dangerous Nuform energy source.\n"
        "- Ganke Lee: Miles's best friend and tech support over comms.\n"
        "- Uncle Aaron Davis / The Prowler.\n"
        "PLACES: wintry Harlem and Manhattan, Roxxon Plaza/labs, the Underground's "
        "tunnels.\n"
        "DON'T CONFUSE: Miles's yellow electric attacks are his 'Venom' bio-electric "
        "powers, NOT the Venom symbiote; the masked purple-tech enemies are the "
        "Underground led by the Tinkerer (Phin)."
    ),
    "spider-man2": (
        "MARVEL'S SPIDER-MAN 2 (2023) — BOTH Peter Parker and Miles Morales are "
        "playable Spider-Men across a bigger NYC (now incl. Brooklyn & Queens).\n"
        "KEY PEOPLE:\n"
        "- Peter Parker: bonds with the black alien SYMBIOTE suit (glossy black with "
        "white spider + tendrils), which makes him aggressive. Black-suit Peter = "
        "symbiote-influenced.\n"
        "- Miles Morales: the other Spider-Man (red/black suit), dealing with his "
        "father's death and the Martin Li thread.\n"
        "- KRAVEN THE HUNTER (Sergei Kravinoff): leads Kraven's Hunters, a private "
        "army hunting the city's super-powered people. Primary early villain.\n"
        "- VENOM: the symbiote leaves Peter and bonds with HARRY OSBORN (not Eddie "
        "Brock in this game) to become Venom.\n"
        "- Harry Osborn: Peter's best friend, gravely ill; ends up the Venom host.\n"
        "- The Lizard (Dr. Curt Connors) and a returning Mister Negative also appear.\n"
        "- MJ Watson: reporter, has her own playable sections.\n"
        "PLACES: expanded Manhattan + Brooklyn + Queens, the Emily-May Foundation, "
        "Oscorp, Coney Island, Harry's estate.\n"
        "DON'T CONFUSE: the big white-veined black monster is VENOM (hosted by Harry, "
        "not Eddie); black-suit Peter is the SYMBIOTE suit, not a separate villain."
    ),
}


def lore_for(game: str) -> str:
    """Return the story brief for a game id, or '' if we don't have one."""
    return GAME_LORE.get((game or "").strip().lower(), "")
