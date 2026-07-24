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
        "TIMELINE RULE (CRITICAL): PETER has been Spider-Man for 8 years before this "
        "game starts — NEVER frame a Peter moment as 'before he had powers' / an origin "
        "/ him 'becoming' Spider-Man. His out-of-suit scenes (Otto's lab, the Bugle, "
        "home) are his DOUBLE LIFE, not pre-powers. (Only MILES is genuinely pre-powers "
        "here — he's bitten at the very END.)\n"
        "DON'T CONFUSE: the lab is Otto's/Peter's workplace (not a 'villain's lab' "
        "and Peter is not 'sneaking in'); the teen at the shelter is Miles the "
        "civilian (not Spider-Man); the man in the lab with Peter is Otto the "
        "mentor (not an enemy)."
    ),
    "spider-man-miles-morales": (
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
        "TIMELINE RULE (CRITICAL): Miles ALREADY has his powers for this whole game (he "
        "was bitten at the end of the 2018 game) — he is NEW and still learning, but "
        "NEVER 'before he had powers' / an origin. His out-of-suit scenes (home with "
        "Rio, Harlem, with Ganke) are his DOUBLE LIFE, not pre-powers.\n"
        "DON'T CONFUSE: Miles's yellow electric attacks are his 'Venom' bio-electric "
        "powers, NOT the Venom symbiote; the masked purple-tech enemies are the "
        "Underground led by the Tinkerer (Phin)."
    ),
    "spider-man2": (
        "MARVEL'S SPIDER-MAN 2 (2023) — BOTH Peter Parker and Miles Morales are "
        "playable Spider-Men across a bigger NYC (now incl. Brooklyn & Queens).\n"
        "NAMING RULE (CRITICAL): because BOTH are playable and the game swaps between "
        "them, you usually CANNOT tell which Spider-Man a given gameplay clip shows. "
        "DEFAULT to the generic \"Spider-Man\" and do NOT guess 'Peter' or 'Miles'. "
        "Name PETER only if the clip UNMISTAKABLY shows the black glossy SYMBIOTE suit "
        "(white spider + living tendrils) or an explicit Peter story beat; name MILES "
        "only if it UNMISTAKABLY shows his glowing YELLOW bio-electric 'Venom' zaps or "
        "an explicit Miles story beat. In ANY doubt, write \"Spider-Man\" — never assume.\n"
        "TIMELINE RULE (CRITICAL): there is NO origin story here — for the game's ENTIRE "
        "runtime BOTH Peter and Miles are long-established, fully-powered Spider-Men. "
        "NEVER write that a moment is 'before he had powers', 'before he was Spider-Man', "
        "an origin, or him 'becoming'/'getting' powers. Out-of-suit CIVILIAN scenes (their "
        "old school, a Homecoming dance, a locker, home life, MJ's sections) are the "
        "DOUBLE LIFE of an ALREADY-powered hero — they are never pre-powers.\n"
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


GAME_LORE["ff7"] = (
    "FINAL FANTASY VII — the compilation. Be accurate to canon; the threads track "
    "tends to fabricate FF7 lore, so ground every claim here.\n"
    "REAL TITLES: OG FF7 (1997), Crisis Core (2007; Reunion remaster 2022), Dirge "
    "of Cerberus (2006), Advent Children (2005 film), FF7 Remake (2020), "
    "INTERmission/Yuffie DLC (2021), FF7 Rebirth (2024), and FF7 REVELATION — the "
    "third and FINAL chapter of the Remake trilogy.\n"
    "FF7 REVELATION (Remake Part 3) — REAL and in scope, but UNRELEASED: announced "
    "June 2026 at Summer Game Fest; releasing SPRING 2027 (the OG's 30th "
    "anniversary); launching SIMULTANEOUSLY on PS5, Xbox Series X|S, Nintendo Switch "
    "2, and PC (Steam/Epic) — the first remake-trilogy game to go multiplatform day "
    "one (Remake/Rebirth were PS5-first). Director: Naoki Hamaguchi. Theme: "
    "'resolve' — Cloud and his companions confront their destinies and march to the "
    "final battle against Sephiroth one last time. Because it is unreleased, post "
    "ONLY officially confirmed news (title, Spring 2027 window, platforms, "
    "trailers); NEVER invent its plot, bosses, or in-game events.\n"
    "OG FF7 (1997) STORY ESSENTIALS:\n"
    "- Cloud Strife: ex-SOLDIER merc, the protagonist. Tifa Lockhart, Barret "
    "Wallace (leads AVALANCHE, an eco-group fighting Shinra), Aerith/Aeris "
    "Gainsborough (last Cetra/Ancient; killed by Sephiroth), Red XIII, Cait Sith, "
    "Cid, Yuffie, Vincent.\n"
    "- Shinra Electric Power Company: the megacorp draining the Planet's lifeblood "
    "(Mako/the Lifestream) via reactors. Midgar is Shinra's city.\n"
    "- Sephiroth: the antagonist. He summons METEOR (black magic) to gravely wound "
    "the Planet, so he can absorb the Lifestream's healing energy and become a god. "
    "HOLY (summoned via the White Materia, Aerith's role) is the counter-spell.\n"
    "- THE WEAPONS (Diamond, Ultima, Ruby, Emerald, etc.): colossal monsters the "
    "PLANET itself created/awakened as a DEFENSE MECHANISM to purge threats to the "
    "Planet. They are the Planet's protectors, not villains.\n"
    "- DIAMOND WEAPON marches on and attacks MIDGAR because it targets SHINRA — "
    "Shinra's Mako drain and its Sister Ray (giant Mako cannon) are the threat to "
    "the Planet. Shinra's Sister Ray then destroys Diamond Weapon (the blast "
    "continues toward Sephiroth at the Northern Crater). So Diamond Weapon attacking "
    "Midgar = the Planet's defense striking Shinra, NOT a 'boss threatening the "
    "city' in a villain sense.\n"
    "COMMON ERRORS TO AVOID: don't call a Weapon a generic 'boss menacing the city'; "
    "it's the Planet's immune response to Shinra. FF7 Revelation is real but "
    "UNRELEASED — don't fabricate its in-game events (e.g. the false claim that "
    "'Diamond Weapon fights for us against Meteor' in it); only OG-FF7 canon is "
    "established. Meteor is Sephiroth's spell, not a creature; the Weapons fight the "
    "THREAT to the Planet (Shinra), not 'for humanity'."
)


GAME_LORE["thelastofus2"] = (
    "THE LAST OF US PART II (2020, Naughty Dog) — GAME CANON ONLY. This is the VIDEO "
    "GAME, NOT the HBO TV show — the show reorders/changes events, names and timing, so "
    "ignore the series and describe only the game's story. Set ~5 years after Part I. "
    "TWO playable protagonists: ELLIE (first half) and ABBY (second half, same days "
    "retold from her side).\n"
    "KEY PEOPLE:\n"
    "- Ellie: late-teens, brown hair, a MOTH/fern tattoo on her right forearm; immune "
    "to the Cordyceps infection; plays guitar. Joel's surrogate daughter. Drives the "
    "revenge story.\n"
    "- Joel Miller: Ellie's father figure. At the START of the game he is beaten to "
    "death with a golf club by ABBY in Jackson — her revenge because Joel killed her "
    "father (the Firefly surgeon) at the end of Part I to save Ellie. His death sets "
    "the whole plot in motion.\n"
    "- Abby Anderson: tall, muscular, blonde ponytail; a soldier of the WLF. Daughter "
    "of the surgeon Joel killed. The SECOND playable protagonist (not a plain villain "
    "— the game makes you play as her).\n"
    "- Dina: Ellie's girlfriend; PREGNANT (with Jesse's baby, JJ); travels with Ellie "
    "to Seattle.\n"
    "- Jesse: Ellie & Dina's friend from Jackson (Dina's ex); comes to help; killed by "
    "Abby at the theater.\n"
    "- Tommy: Joel's younger brother, lives in Jackson; also hunts Abby.\n"
    "- Abby's WLF crew (present at Joel's death, hunted by Ellie): Owen, Mel (who is "
    "PREGNANT), Manny, Nora, Jordan, Leah.\n"
    "- Lev & Yara: siblings who DEFECT from the Seraphites. Lev is a young trans boy "
    "Abby protects; the Abby half is about her bond with Lev.\n"
    "- Isaac: hardened leader of the WLF.\n"
    "FACTIONS in Seattle: the WLF / 'WOLVES' (a large ex-military militia — soldiers, "
    "guard DOGS, guns, the old stadium as their base) vs the SERAPHITES / 'SCARS' (a "
    "religious cult — robed, scarred faces, use bows & melee, and WHISTLE to signal "
    "each other; live on an island).\n"
    "INFECTED (fungal, not zombies): Runners, Stalkers, CLICKERS (blind, fungus-headed, "
    "echolocate by clicking), Bloaters, and the new SHAMBLERS (spray acid). The RAT "
    "KING is a huge fused boss in the Seattle hospital basement.\n"
    "PLACES: JACKSON, Wyoming (snowy mountain town, Ellie & Dina's home) -> SEATTLE, "
    "Washington (rain-soaked, overgrown, flooded ruins: downtown, the WLF stadium, the "
    "hospital, the aquarium, the Seraphite island, a theater hideout) -> a farmhouse -> "
    "SANTA BARBARA, California (the Rattlers, a slaver group, at the end).\n"
    "STORY BEATS: Abby kills Joel in Jackson -> Ellie & Dina hunt Abby's crew across "
    "Seattle (Ellie kills Nora at the hospital, Owen & the pregnant Mel on a boat) -> "
    "perspective SWITCHES to Abby's 3 days (her WLF life, saving Lev/Yara) -> they "
    "collide at the theater (Abby beats Ellie & kills Jesse, spares her) -> months "
    "later at the farm (Ellie, Dina, baby JJ) Ellie leaves for revenge -> SANTA BARBARA: "
    "the Rattlers have enslaved Abby & Lev; Ellie frees then fights a starved Abby, and "
    "in the end LETS HER GO -> Ellie returns to an empty farm, unable to play guitar "
    "(two fingers bitten off in the fight).\n"
    "DON'T CONFUSE: it's the GAME, not the HBO show (don't cite show-only changes). "
    "Ellie = lean, brown-haired, arm tattoo; Abby = muscular, blonde ponytail — don't "
    "swap them. WLF 'Wolves' (military + dogs) are NOT the Seraphite 'Scars' (robed "
    "cultists who whistle). Clickers are blind and echolocate (not generic zombies). "
    "Joel dies EARLY (this is the inciting event, not a late twist). Abby is a "
    "PROTAGONIST you play, not just an enemy."
)


GAME_LORE["thelastofus1"] = (
    "THE LAST OF US PART I (the 2013 game; remade 2022) — GAME CANON, the STORY THAT "
    "SETS UP PART II. A Cordyceps fungal pandemic collapsed civilization; the game is "
    "set ~20 years after the outbreak.\n"
    "KEY PEOPLE:\n"
    "- Joel Miller: a hardened smuggler in the Boston quarantine zone (QZ). His young "
    "daughter Sarah was shot dead on the first night of the outbreak — the wound he "
    "carries all game.\n"
    "- Ellie: a 14-year-old girl who is IMMUNE (bitten but never turned) — humanity's "
    "one hope for a vaccine. Joel is hired to smuggle her across the country.\n"
    "- Tess: Joel's smuggling partner; dies (infected) early on.\n"
    "- Tommy: Joel's younger brother; runs a settlement at a hydro dam in Jackson, "
    "Wyoming.\n"
    "- The FIREFLIES: a rebel militia (vs the military dictatorship FEDRA) trying to "
    "cure the infection. Marlene is their leader.\n"
    "- Bill (paranoid survivor in Lincoln), Henry & Sam (brothers; Sam turns, Henry "
    "kills Sam then himself), and DAVID (a cannibal-cult leader Ellie kills in winter).\n"
    "PLACES: Boston QZ -> Pittsburgh -> Jackson/Tommy's dam -> University of Eastern "
    "Colorado -> Salt Lake City (the Firefly hospital). Famous quiet beat: the GIRAFFE "
    "in Salt Lake.\n"
    "STORY BEATS / THE ENDING THAT DRIVES PART II: at the Firefly hospital the surgeons "
    "conclude they must REMOVE Ellie's brain (where the immune Cordyceps grows) to make "
    "the cure — which would KILL her. Joel refuses, storms the hospital and kills the "
    "Fireflies — including the lead SURGEON (Jerry Anderson) — carries Ellie out, and "
    "LIES to her that they stopped looking for a cure. (In PART II, that surgeon's "
    "daughter ABBY comes for revenge — this is why Part II happens.)\n"
    "INFECTED: Runners, Stalkers, Clickers (blind, echolocate), Bloaters — same fungal "
    "enemies as Part II.\n"
    "NOTE: this is BACKGROUND/context. Our TikTok footage is PART II; only caption a "
    "clip as Part I if it's clearly a Part I flashback/reference."
)


GAME_LORE["halo"] = (
    "HALO: CAMPAIGN EVOLVED (2026) — a full REMAKE (Unreal Engine 5, Halo Studios) of "
    "the campaign of HALO: COMBAT EVOLVED (2001), the FIRST Halo game. The story IS "
    "Halo CE's; do NOT pull in later-Halo arcs (no Arbiter, no Banished, no 'the "
    "Weapon', nothing from Halo 2/3/4/5/Infinite).\n"
    "NEW CONTENT: adds 3 prequel missions — 'OPERATION METEORITE', set ONE YEAR BEFORE "
    "the main story, led by Master Chief + Sgt. Avery Johnson (before Halo is found). So "
    "a clip may be this prequel; still just the Chief + the UNSC vs the Covenant. "
    "CRITICAL: in Op METEORITE, CORTANA is NOT with the Chief yet — do NOT mention Cortana "
    "for a METEORITE clip; Johnson + UNSC Marines are the voices there.\n"
    "NAMING: single playable hero — the player is ALWAYS the MASTER CHIEF (Spartan "
    "John-117), a tall super-soldier in the iconic green MJOLNIR armor with a gold "
    "visor. Name him confidently. He barely speaks; CORTANA (his AI) does the talking.\n"
    "TIMELINE RULE: the Chief is an ALREADY-established SPARTAN-II super-soldier the "
    "whole game — NO origin story. Never write 'before he was a Spartan' or him "
    "'becoming' the Master Chief.\n"
    "KEY PEOPLE / AI:\n"
    "- MASTER CHIEF (John-117): the green-armored Spartan you play. Stoic, silent.\n"
    "- CORTANA: the AI companion — a blue/purple holographic woman in Chief's head; "
    "snarky, brilliant. The ORIGINAL loyal Cortana (not the later corrupted arc).\n"
    "- Sgt. Avery JOHNSON: tough, quippy UNSC Marine sergeant (co-leads Op METEORITE).\n"
    "- Captain Jacob KEYES: commander of the UNSC warship Pillar of Autumn.\n"
    "ENEMIES (two DISTINCT factions — never merge them):\n"
    "- THE COVENANT: a theocratic alliance of ALIENS on a holy war to exterminate "
    "humanity — Elites (tall, agile, energy swords), Grunts (small, squat, methane "
    "tanks), Jackals (arm shields), Hunters (huge armored), led by the Prophets.\n"
    "- THE FLOOD: a PARASITIC zombie-like infection released on the ring — turns humans "
    "AND Covenant into shambling combat forms + spore pods. The horror twist. NOT the "
    "Covenant.\n"
    "- 343 GUILTY SPARK: 'the Monitor' — a small floating white robotic eye that speaks "
    "politely, helps Chief, then turns on him. An AI, not the Covenant.\n"
    "PLACES / BEATS: the PILLAR OF AUTUMN (UNSC warship); HALO / Installation 04 (the "
    "giant ring-shaped Forerunner megastructure — the main setting); THE SILENT "
    "CARTOGRAPHER (island level with a Forerunner map room); the Library; the Control "
    "Room; the finale WARTHOG RUN escaping the self-destructing ship. The WARTHOG is the "
    "iconic UNSC jeep.\n"
    "TWIST: Halo isn't an anti-Covenant weapon — its TRUE purpose is a galaxy-wide "
    "superweapon that kills ALL sentient life to starve the Flood; the Chief destroys "
    "the ring to stop it.\n"
    "DON'T CONFUSE: green armor = Master Chief (the only hero); floating white eye = "
    "343 Guilty Spark; the zombies = the Flood; the alien army = the Covenant; Halo is "
    "a RING (a place), not a handheld weapon.\n"
    "CORTANA RULE: only mention Cortana if she is ACTUALLY present in the clip — her "
    "blue/purple hologram is visible OR her voice/subtitle appears. If the on-screen "
    "subtitle credits someone else (e.g. 'JOHNSON:') or you see Marines and no blue AI, "
    "Cortana is NOT there (likely Op METEORITE) — never attribute the moment to her."
)


def lore_for(game: str) -> str:
    """Return the story brief for a game id, or '' if we don't have one."""
    return GAME_LORE.get((game or "").strip().lower(), "")


# Keyword -> lore key, for tracks (like Threads) that don't know the game up
# front. First match wins; order from most specific to least.
_LORE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("spider-man2", ("spider-man 2", "spiderman 2", "marvel's spider-man 2")),
    ("spider-man-miles-morales", ("miles morales",)),
    ("spider-man1", ("spider-man", "spiderman", "peter parker", "insomniac spider")),
    ("ff7", ("final fantasy vii", "final fantasy 7", "ff7", "ffvii", "ff vii",
             "rebirth", "crisis core", "sephiroth", "cloud strife")),
    ("halo", ("halo", "master chief", "campaign evolved", "combat evolved", "spartan",
              "john-117", "cortana", "covenant", "mjolnir", "unsc")),
    ("thelastofus1", ("the last of us part i", "the last of us part 1", "tlou1",
                      "tlou part i", "the last of us remastered", "the last of us (2013")),
    ("thelastofus2", ("the last of us part ii", "the last of us part 2", "tlou2",
                      "tlou part ii", "the last of us 2", "ellie and abby", "abby anderson")),
]


def lore_key_for_text(*texts: str) -> str:
    """Best-guess lore key from free text (subject/title/focus_game). '' if none."""
    hay = " ".join(t for t in texts if t).lower()
    for key, kws in _LORE_KEYWORDS:
        if any(kw in hay for kw in kws):
            return key
    return ""
