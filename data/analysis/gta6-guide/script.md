# GTA 6 Beginners Guide: exact cue sheet (from approved script v1.1)

Built 2026-11-22 from `Z:\Bryce-Brain\raw-sources\kg-longform-research-2026-11\gta6-beginners-guide-script-v1.md` (v1.1, approved by Bryce on 2026-11-22, "Approve as is"). The narration words, the section order and the 10 game-line cuts are unchanged; only the approximate [ON SCREEN] and [CUT] cues were replaced with exact [CLIPS] and [GAME AUDIO] cues that `tools/analysis_edl.py` reads (game name `gta6-guide`). Section headings became `Chapter:` headings and tip headings became level-3 headings, because the parser reads any `####` line as narration.

How the seconds were found: every shot range was checked on frames pulled from B2 over signed URLs (1 s sheets for every candidate window, then a 4-frame strip of every final shot: start, one third, two thirds, end). Every burst was transcribed with faster-whisper small.en (CPU, word timestamps, float32 16 kHz input) and cut 0.1 to 0.25 s outside its first and last word. No blocked range in `config.yaml reels.footage.blocked_ranges` is used, no shot range overlaps another, and every shot is 2 to 12 s.

Coverage: 128 shots over 50 narration paragraphs, 832.6 s of shots against an estimated 833.5 s of narration (words / 175 x 60 + 0.5 s per paragraph), plus 10 bursts of 26.9 s; about 14:20 in all. Each paragraph's shots add up to within 1 s of its estimate. Shots are ordered and sized to the words they show at 175 wpm; Guide C reads about 210 wpm untouched, so set the EDL pace or add `at` anchors (see open issue 15).

Crops: evidence shots (menus, tooltips, HUD figures, maps) carry `"crop": "none"` so the HUD the narration points at stays in frame; every other narration shot takes the renderer's default subtitle crop. Bursts from cutscenes carry `"crop": "none"`; gameplay bursts carry "crop sides" (the band crop, which keeps the subtitle line). Two teaser shots of the unowned-items notice use the note words "blur the gore" only to switch on the renderer's blur, so the notice is unreadable until tip 27.

Shot keys: `cutscenes/gta6/GTA 6 (2026-11-19 HH-MM-SS).mp4` is launch night; `cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p03.mp4` style keys are the 2026-11-21 night session parts.

## Script

Cue key. [CLIPS <B2 key> @ a-b (note)] are narration shots in order, shared across the paragraph that follows by range length; "crop": "none" marks an evidence shot whose HUD, menu or tooltip must stay in frame. [GAME AUDIO <B2 key> @ a-b s: "line" (word times); crop] is the game's own line with narration paused, framed by narration. Game music and radio stay muted under narration.

### 0:00 Cold open

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 139-143.4 (wasted camera on the sheriff SUV, then the red WASTED card from about 141.5), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 13-17.3 (HUD wallet $0 with red minus $531 after the respawn; "crop": "none")]

[GFX lower "GTA 6: THE BEGINNER'S GUIDE"; counter $531 "LOST IN ONE DEATH" on "five hundred and thirty-one"]
New to GTA 6? You should not rob a store until you know why I lost five hundred and thirty-one dollars in one death.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 12-20 (Lucia walks the bridge into the sun), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 7.2-12.8 (respawn pose at Buckskin Swamp, HUD-free), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 31-33 (four stars with the outfit and face icons under them, top right; "crop": "none")]

[GFX caption "27 TIPS FROM MY FIRST WEEK IN LEONIDA"]
This is how a new player keeps their cash, keeps their cars and stays off the police radar. Here is the first problem. The cash in your pocket is gone when you die. Here is the second. The cops remember your face and your outfit.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p10.mp4 @ 137.5-145 (the unowned-items notice in the night kitchen, blur the gore (teaser blur, notice unreadable)), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p09.mp4 @ 30-33.6 (dusk drive, cinematic camera)]

And there is a third way to lose your stuff, without dying at all. I got that warning after loading a save, and I will show you near the end.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 236-238.1 (night chase on the causeway, sparks), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 0.2-2.3 (respray colour swatches on the Elegy), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 163-165.1 (Lucia and Tootsie the cow in the orchard)]

Money first, then cops, cars, health, side hustles and saving, with the top five at the end.

### 0:42 Chapter: Money

### Tip 1: Bank your cash (the most important tip)

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-31-14).mp4 @ 0.2-9 (HUD $531 cash top right on launch night; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 53-60 (the airliner skims the trees and slams into the swamp forest), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 102.6-113.4 (gunfight with the deputies in the woods (no blood; gore starts at 126)), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p08.mp4 @ 143-155 (Lucia walks into a shop for a hold-up)]

[GFX chapter 1 "MONEY"; tag "TIP 1: BANK YOUR CASH"; counter $0 "WALLET AFTER ONE DEATH" on "my HUD said zero"]
Tip number one, and it is the most important tip in this whole video. Bank your cash. Whatever you carry is lost when you die. Guides say the same goes for getting busted. I had five hundred and thirty-one dollars on me on launch day. One plane crash and one shootout later, my HUD said zero. Guides also report a small fee from your BuckMe bank app when you go down. So every time you pass an ATM with real money on you, stop and deposit it. Cash in the bank survives. Cash in your pocket is only on loan. Every robbery fills your pocket. So bank it before the next one.

### Tip 2: Deposit at an ATM, in person

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 172-175.5 (Lucia steps up to the motel lobby ATM), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 168.5-176.5 (phone in hand, apps and messages), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 175.5-181.5 (ATM screen: Deposit / Withdraw / Transactions; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p12.mp4 @ 137.5-144 (convenience store ATM beside the magazine rack)]

[GFX tag "TIP 2: DEPOSIT AT AN ATM, IN PERSON"]
Tip number two. You deposit at an ATM, in person. A lot of new players think the phone app can bank their cash. It cannot. Guides agree your phone will not move pocket cash into the bank. ATMs sit in places you already visit. Lucia's motel has one in the lobby. The convenience store has one by the magazines. Find the ATM before you find the action.

### Tip 3: Jason and Lucia share one account

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 182-188.5 (Transactions list with the Coastal Auto Care debits; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p08.mp4 @ 144-150 (transmission menu at Coastal Auto Care, bank figure falling from $7,066; paid from the bank, unlike the wing in p07, which was cash; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 194-200.9 (same statement, scrolled; "crop": "none")]

[GFX tag "TIP 3: ONE SHARED BANK ACCOUNT"]
Tip number three. Jason and Lucia share one bank account. I spent a pile of Jason's bank money at Coastal Auto Care. Later, Lucia checked her ATM, and those charges were on her statement, with Brian's payments too. So money one of them banks is money the other one can spend.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 20-22.9 (Lucia crosses the motel lot)]

Our landlord was very understanding about it.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 230.2-233.5 s: "Linda: I want rent plus 10% for the trouble." (words 230.40-233.26; next line 234.04); gameplay HUD, crop sides]

### Tip 4: Stolen goods are not money yet

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p01.mp4 @ 196-203 (notice: You have some marked bills. Take them to a drop-off to sell for usable cash; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p05.mp4 @ 272-278 (map tooltip Brian's Lockup, goods to sell, price list; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p03.mp4 @ 82-90 (blue lockup with the marlin mural, Jason carries the duffel in), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p03.mp4 @ 100-106.6 (Jason takes the bag in through the lockup door), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p04.mp4 @ 37-44 (Brian's text: "Paid you for those bags you stashed at the lockup", bank +$9,840; "crop": "none")]

[GFX tag "TIP 4: STOLEN GOODS ARE NOT MONEY YET"; counter $8,160 "SELL OFFER FOR MY STASH" on "eight thousand one hundred"]
Tip number four. Stolen goods are not money yet. When you loot narcotics, jewelry or marked bills, they go into a stash bag. The game tells you straight. Take them to a drop-off to sell for usable cash. Early on, that drop-off is Brian's Lockup. Look for the blue building with the marlin mural. Carry the bag inside. Inside, the sell prompt offered eight thousand one hundred and sixty dollars for my stash. Then Brian texts you that he paid. Until someone pays you, that bag is just a heavy backpack.

### Tip 5: Stow the stash bag and sell it soon

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p02.mp4 @ 106-116 (stash menu at the truck: Stow stash bag / Stash bag on back; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p03.mp4 @ 20-30 (driving the Ganado to the lockup), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p04.mp4 @ 36-44.3 (Brian's text, paid, +$9,840 on the bank icon; "crop": "none")]

[GFX tag "TIP 5: STOW THE BAG, SELL IT SOON"]
Tip number five. Stow that stash bag in your vehicle, and sell it soon. At your car, you can stow the bag or keep it on your back. Guides warn that a bag on your back will most likely be lost if you go down. So loot, stow, and drive straight to the drop-off. Do not go sightseeing with a bag of jewelry. And once Brian pays, the money lands straight in your bank account. A death cannot touch it there.

### Tip 6: Rob small stores for early cash

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p05.mp4 @ 46-58 (Lucia stops a robber at Tucker's farm stand and takes the clerk's offered cash, wallet $149 to $247; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p05.mp4 @ 94.5-100 (notice: Tucker's Citrus Farms is currently closed due to a robbery; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 110-118 (tooltips: mugging people, robbing with your partner; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 162-168.2 (Avery Pawn counter, gun drawn (before the clerk frame at 202))]

[GFX tag "TIP 6: SMALL STORES, SMALL MONEY"; counter $98 "THE CLERK'S REWARD AT TUCKER'S" on "about a hundred dollars"]
Tip number six. Small stores pay small money, and the game shuts them after. At Tucker's farm stand, someone else was already holding the place up. I stopped him. The clerk told me to take whatever I wanted, and I walked off with about a hundred dollars. Right after, the game told me Tucker's Citrus Farms was closed due to a robbery. The game also tells you that you can mug people, and rob places with your partner. I robbed a pawn shop myself, and it turned into a shootout. So rob small, bank it, and keep moving.

### 3:38 Chapter: The cops

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 200-206 (night causeway chase, police car alongside)]

[GFX chapter 2 "THE COPS"]
Robbing stores brings the cops, so section two is how the police work in GTA 6.

### Tip 7: The police remember what you look like

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 106.6-114 (Lucia sneaks through the yards, stars up), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 114.45-116.45 (map: The cops are actively looking for you in this area, Appearance known, Outfit known (starts on the map fade-in); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 162-167.8 (HUD stars with the outfit (hanger) and face icons; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 236-240.8 (Lucia tries on a new top in the clothing store), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 66-72.5 (pause map: The cops are actively looking for you in this area, APPEARANCE KNOWN, OUTFIT KNOWN; "crop": "none"; push in)]

[GFX tag "TIP 7: THEY REMEMBER YOUR LOOK"; slam "YOUR OUTFIT IS EVIDENCE." on "your outfit is evidence"]
Tip number seven. The police remember what you look like. Open the map after a crime and read the search area. When my stars went up, two red icons showed under them, a clothes hanger and a person. The map spelled it out: appearance known, outfit known. Check them every time the stars go up. So hiding is only half the job. You also have to stop looking like you. In Leonida, your outfit is evidence.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p11.mp4 @ 170-173.6 (Jason in the yellow shirt and Lucia in the wig walk down the stairs)]

Luckily, the cops here are very polite about it.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p11.mp4 @ 182.75-184.55 s: "officer: Okay, you are under arrest!" (words 182.86-184.32; 'God ... damn it' ends 182.52, next 'You can't' 184.84); "crop": "none"]

### Tip 8: Break line of sight, then leave the red zone

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p09.mp4 @ 213.8-217.4 (map with the red search zone; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p09.mp4 @ 218-230 (tow truck drives away past the refinery), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 55.5-64.6 (live HUD in the Elegy, no stars; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 64.8-71.6 (map: red zone, red stars, Appearance known, Outfit known; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 96-103.1 (driving away from the zone, open road)]

[GFX tag "TIP 8: BREAK LINE OF SIGHT"]
Tip number eight. To lose the cops, break line of sight, then leave the red zone. The red area on your map is where they are searching. Get out of it, and do not drive back in. Here is a myth to drop. Stars gone does not mean you are safe. Look at my screen here. The stars are gone from my HUD. But the map still shows the search zone, and it still knows my outfit. Guides agree the hot area stays while the heat fades. If police spot you there, the stars come back. So keep heading away from that zone. Leave like you have somewhere better to be.

### Tip 9: Hide until the search moves past

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 275-283 (Lucia with the long gun behind a container, stars up), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 110-117 (sneaking along the junkyard fence), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p04.mp4 @ 75-83.5 (crouched in the bushes by the bar deck)]

[GFX tag "TIP 9: HIDE UNTIL IT PASSES"]
Tip number nine. When you cannot outrun them, hide. Crouch in bushes, or behind a shipping container or a dumpster. Then stay hidden until the search moves past. Lucia crept through the bushes beside a waterfront restaurant like this, with four stars still up. One catch. Guides say that if police dogs show up, you should keep moving, or they will hunt you down. Out of sight is the goal.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p04.mp4 @ 83.6-86.8 (Lucia crouched in the bushes by the bar deck)]

I kept a very low profile that night.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 184.65-187.45 s: "Andy (phone): Lucia, there's police everywhere!" (words 184.84-187.22; next 'Just' 187.74); gameplay HUD, crop sides]

### Tip 10: Change your outfit once you are out of sight

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 176-186.5 (tow truck escape, stars still up (gone at 188); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 187.5-193 (stars gone, HUD shows money only; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 212-220 (into the clothing store, Buy a new outfit), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 257.5-265.5 (Denim cutoffs $12; "crop": "none")]

[GFX tag "TIP 10: CHANGE CLOTHES OUT OF SIGHT"; counter $12 "DENIM CUTOFFS" on "twelve dollars"]
Tip number ten. Change your outfit, but only once you are out of sight. Guides say a new outfit clears the outfit known line on your map. But that only works once you have broken line of sight. Lucia slipped away in a tow truck, with the stars still flashing. Only once the stars were gone did she walk into a clothing store. Denim cutoffs were twelve dollars. That is a cheap disguise. Three separate guides also suggest keeping a spare outfit in your car's trunk. Change after you vanish, never before.

### Tip 11: Hats, glasses and splitting up

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 242.8-248.4 (items wheel: Rod's Racing Cap, glasses ON, outfit; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 72-77 (launch-night items wheel with the baseball cap; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 138-145.3 (Lucia puts on the cap from the items wheel)]

[GFX tag "TIP 11: HATS, GLASSES, SPLIT UP"]
Tip number eleven. Small changes throw off the description too. Hats and glasses sit on the items wheel, so you can swap them in a second. Guides also say splitting up Jason and Lucia helps, because the police note your partner as well. A cap costs a lot less than getting busted.

### Tip 12: The Pay 'n' Spray will not save you mid chase

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 124.5-131.5 (tooltip: You can't enter a Pay 'n' Spray when the cops are nearby or in pursuit; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 49.5-55.5 (Moses' services menu, Respray: change the vehicle color to reduce recognition; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 92-100 (respray preview, $100; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 287.6-293.8 (the Elegy in Moses' garage, respray swatches)]

[GFX tag "TIP 12: NO RESPRAY MID CHASE"]
Tip number twelve. The Pay 'n' Spray trick from older games does not work here. The game says you cannot enter a Pay 'n' Spray when the cops are nearby or chasing you. Lose them first. Then respray the car. The respray menu says a new color reduces recognition. At Moses' shop, a respray was a hundred dollars. So the order is always the same. Escape first, then paint. Paint hides the car. It does not hide you.

### 6:35 Chapter: Cars

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 36-43 (Lucia on the bridge walks up to the white Elegy)]

[GFX chapter 3 "CARS"]
A respray only helps a car worth keeping. So section three is how to steal one and keep it.

### Tip 13: Check a car before you steal it

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 33-39.5 (WAiNK panel: access key cloner, alarmed, tracker standard; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p01.mp4 @ 110-115 (tooltip: Focus to check a vehicle's security and if there's anything valuable in the trunk; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 103-106.5 (Moses's yard: Lucia scans the Vapid Montagne XL, panel locked, alarmed, tracker none; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 177.5-186.2 (Slim Jim into the Montagne XL, ends before 'And she's in' (186.3))]

[GFX tag "TIP 13: SCAN BEFORE YOU STEAL"]
Tip number thirteen. Check a car before you steal it. Scan a parked car with the WAiNK app, and a panel shows its lock, its alarm and its tracker. The game also says Focus shows if there is anything valuable in the trunk. At Moses's yard, I scanned a Vapid Montagne XL. Locked, alarmed, tracker none. No tracker is what matters. That is the one you want. Locked cars open with a Slim Jim, and Moses teaches you how.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 172-175 (Lucia walks to the brown Montagne XL)]

It took me years to learn this.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 189.12-190.55 s: "Lucia: Guess I'm a natural." (words 189.16-190.34 (tight pass: 'Wow, I guess I'm a natural'); 'Wow' ends 189.16); gameplay HUD, crop sides]

### Tip 14: Early on, steal cars with no tracker

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 121-129.7 (phone scan of Moses' Riata in the yard, tracker standard (no Moses face); "crop": "none")]

[GFX tag "TIP 14: NO TRACKER, EARLY ON"]
Tip number fourteen. Early on, steal cars with no tracker. My car guy, Moses, says it flat. He does not do trackers.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 73.6-75.85 s: "Moses: One thing I don't do is trackers." (words 73.82-75.64; next 'You boost' 76.30); gameplay HUD, crop sides]

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 196-202.2 (map card Moses: buys low-key untracked vehicles, won't take vehicles stolen nearby; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 135-141 (phone scan of the Willard '92 Grouse: locked, security none, tracker none; "crop": "none")]

His map card says he buys low key untracked vehicles. Guides say tracked cars open up later in the story, through another contact. Until then, tracker none is the phrase you are hunting for.

### Tip 15: Register a car to keep it

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 4-10 (Register screen: FREE, Swap plates and register this vehicle as yours, 0/1 stored vehicles; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 11-14.1 (the red Elegy in Moses' garage, wide)]

[GFX tag "TIP 15: REGISTER IT TO KEEP IT"]
Tip number fifteen. To keep a stolen car, register it. Registering swaps the plates and makes the car yours. Moses does your first one free.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 255.6-259.8 s: "Moses: Just this once, I'll get your ride registered for you on the house." (words 255.80-259.58; next 'Call it' 260.98); "crop": "none"]

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 106.5-110 (Vapid Montagne XL scan card, cost to register $3,400; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p11.mp4 @ 279-284.5 (prompt Keep current / Find another; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 29-39.9 (the registered red Elegy rolls out of Watkins at dusk)]

[GFX counter $3,400 "COST TO REGISTER" on "three thousand four hundred"]
Guides say later ones cost more the pricier the car. A Vapid Montagne XL showed a cost to register of three thousand four hundred dollars. The game even asks if you want to keep the car or find another. So use your free one on a car you love, not the first junker you grab. A free registration happens once. Spend it like it matters.

### Tip 16: Get your car delivered

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 49-59 (Scooter Bros app: Request $100 BuckMe, Upgrade to Premium, 3 free deliveries a day; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p01.mp4 @ 2-9.6 (tooltip: You can get your vehicle delivered to you using the Scooter Bros app; "crop": "none")]

[GFX tag "TIP 16: GET YOUR CAR DELIVERED"]
Tip number sixteen. Once a car is registered, it can come to you. The Scooter Bros app delivers it for a hundred dollars a trip. A one time Premium upgrade in the app unlocks three free deliveries a day. A hundred dollars beats a long walk back from the swamp.

### Tip 17: Sell spare untracked cars to Moses

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 2-8 (pulling into Watkins Auto Parts at night), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 21-27 (Hold then press to sell a vehicle to Moses, Sell Bogan (+$350); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 56.5-62.5 (Sell +$350 on the bank icon, then Sell for $350?; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 229.5-235.3 (tooltip: Moses won't take in any vehicles stolen close by; "crop": "none")]

[GFX tag "TIP 17: SELL SPARES TO MOSES"; counter $350 "MOSES'S OFFER FOR A BOGAN" on "three hundred and fifty"]
Tip number seventeen. Sell your spare untracked cars to Moses. Pull into his shop, hold the button, and sell. Moses offered me three hundred and fifty dollars for a Bravado Bogan. Guides say that money goes straight into your bank, so no ATM run is needed. But read his rule first. Moses will not take a car you stole close by. So grab one across town, then drive it in.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 232-234.9 (the white Elegy pulls into Watkins Auto Parts)]

Every car I sell is completely legal.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 273.95-276.95 s: "Moses: Is that your ride? Lucia: Kinda." (words 274.14-276.74; next 'They'll' 277.44); "crop": "none"]

### Tip 18: Price up mods before you buy

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p06.mp4 @ 172-176 (arrival at Coastal Auto Care), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p08.mp4 @ 74-83 (engine menu, Stage 2 $1,800, bank b $9,766; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p08.mp4 @ 153-162.3 (Nitrous Boost $5,000, bank figure down to $5,506; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p08.mp4 @ 118-126 (transmission menu, $1,500 and $600, one part at a time; "crop": "none")]

[GFX tag "TIP 18: PRICE UP MODS FIRST"; counter $506 "LEFT IN THE BANK" on "in under two minutes"]
Tip number eighteen. Mod shops are expensive, so price things up before you buy. At Coastal Auto Care, engine stage two is eighteen hundred dollars. Nitrous is five thousand. Mod shop parts come straight out of your bank. My bank balance fell from about nine thousand eight hundred to about five hundred in under two minutes. Open every menu, check the price, and buy one part at a time. And remember tip number three. Lucia saw every one of those charges.

### 9:31 Re-hook

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 224.3-228.8 (Tootsie in her red cape at the trailer), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p05.mp4 @ 124.5-129.1 (unowned notice over the terrarium, blur the gore (teaser blur))]

We are past halfway. Next, staying alive, then money that does not need a gun. And I still owe you that third way to lose your stuff.

### 9:40 Chapter: Health and stats

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 113.5-120.5 (gunfight in the woods)]

[GFX chapter 4 "HEALTH AND STATS"]
A fast car will not save you in a gunfight, so section four is your health and your stats.

### Tip 19: Eat and drink to heal

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p02.mp4 @ 196-206 (Taco Bomb counter, ordering), cutscenes/gta6/GTA 6 (2026-11-21 21-14-10) p01.mp4 @ 233-240.6 (Jason grilling on Cal's dock)]

[GFX tag "TIP 19: EAT AND DRINK TO HEAL"]
Tip number nineteen. Eat and drink to heal. Guides agree that food, drinks and Zombix all restore health. Lucia ordered a full meal at Taco Bomb. Jason grilled fish on a dock. When you see an Eat prompt after a fight, take it. In Leonida, a taco is a medkit.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p02.mp4 @ 203-206.9 (Lucia at the boat wheel, sunset)]

My friends always keep their priorities straight in a crisis.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p02.mp4 @ 277.8-279.72 s: "Cal: Do me a favor and pick me up some snacks." (words 278.00-279.66 (tight pass); next word cause at 279.86, profanity only from 281.2); "crop": "none"]

### Tip 20: Save adrenaline for emergencies

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p02.mp4 @ 60.5-68.5 (tooltip: use the adrenaline from your loadout to overpower your health, stamina and focus for a short time; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p09.mp4 @ 150-160.7 (hospital shootout, red damage vignette)]

[GFX tag "TIP 20: SAVE ADRENALINE"]
Tip number twenty. Save your adrenaline for emergencies. The tooltip says adrenaline boosts your health, stamina and focus all at once, for a short time. That makes it your panic button. Use it when your health is low and you cannot get to cover. Do not waste a panic button on a jog.

### Tip 21: Finish the full workout, then rest

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-14-10) p03.mp4 @ 152-163 (pull-ups, REPS 12/15 then 13/15; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p05.mp4 @ 226-233 (punching bag, Workout Complete toast (reads level 3/4); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-31-51).mp4 @ 31.5-38.2 (toast: Strength Workout, you need time to recover; "crop": "none")]

[GFX tag "TIP 21: FINISH THE FULL WORKOUT"; counter 13/15 "PULL-UPS" on "thirteen out of fifteen"]
Tip number twenty-one. Work out, finish the full set, then rest. The strength workouts have a rep counter, like thirteen out of fifteen pull-ups. See it through to the end. Jason's level went up the moment his session said workout complete. His workout reached level three of four. After a session, the game tells you that you need time to recover. So train, go do a job, and come back later.

### 10:54 Chapter: Side hustles

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p05.mp4 @ 130-135.3 (quad through the citrus orchards)]

[GFX chapter 5 "SIDE HUSTLES"]
Now that you are healthy, here is money that does not need a gun.

### Tip 22: Open the pause map often

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 74-81.6 (pause map objectives, optional Search for the Skunk Ape; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p06.mp4 @ 139.5-145.3 (map tooltip Coastal Auto Care, mod shop; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p04.mp4 @ 82-87 (whole map of Leonida; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p05.mp4 @ 278.2-282.4 (Jason drives off after reading the map)]

[GFX tag "TIP 22: OPEN THE PAUSE MAP"]
Tip number twenty-two. Open the pause map often. It lists your open missions and your optional side jobs. One of mine was search for the Skunk Ape. Its pins also explain what each place is for, like Brian's Lockup and the mod shop. When the game says map updated, open it and look. A lot of this guide is written right there on that map.

### Tip 23: Search everything

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p01.mp4 @ 150-160 (stash value climbing with +$400 toasts; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p04.mp4 @ 184-190 (safe on top of the filing cabinet, cash pickup; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p01.mp4 @ 243-248.8 (collectible card Leroy Rook in the office; "crop": "none")]

[GFX tag "TIP 23: SEARCH EVERYTHING"]
Tip number twenty-three. Search everything when you clear a place. Offices, lockers and safes hide loot, guns and collectible cards. In one warehouse office, Jason's stash bag kept getting more valuable as he searched. He found loot in a safe on top of a filing cabinet. He found a trading card in the same office. If it has a drawer, open it.

### Tip 24: Sell collectible cards at pawn shops

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 51-54.6 (card close-up with the tooltip: collectible cards can be sold at pawn shops; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p06.mp4 @ 126.5-129.9 (two more cards, Backyard Wrestling; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p08.mp4 @ 85.5-88 (Lucia at the pawn counter), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p08.mp4 @ 98.6-109.5 (pawn sell menu, trading card sets; "crop": "none")]

[GFX tag "TIP 24: SELL CARDS AT PAWN SHOPS"]
Tip number twenty-four. Sell collectible cards at pawn shops. A tooltip tells you this when you pick one up. Guides agree that selling a card does not cost you collection progress. Guides count eighteen sets and four hundred and eighty cards. They put each one at about twenty dollars to over a thousand. In Leonida, cardboard is real income.

### Tip 25: Help strangers who flag you down

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 76-81 (the farmer flags Lucia down), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 158-163 (Calm and capture Tootsie), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 244-248.6 (loading Tootsie into the Howe Dairy trailer)]

[GFX tag "TIP 25: HELP STRANGERS"]
Tip number twenty-five. Help strangers who flag you down. A farmer stopped Lucia because his pageant cow, Tootsie, needed catching. Calm her, load her in the trailer, and he pays you. When someone waves at you from the road, pull over.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 149.5-152.4 (Lucia face to face with Tootsie)]

I came to Leonida for big heists.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p09.mp4 @ 267.2-268.95 s: "Farmer: Here's a little thank you." (words 267.42-268.72 (tight Whisper pass); next line 270.12); gameplay HUD, crop sides]

### 12:24 Chapter: Keep what you earn

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p08.mp4 @ 245-248.9 (sunset, Jason's face through the window)]

[GFX chapter 6 "KEEP WHAT YOU EARN"]
Last section. You earned it, so now you keep it.

### Tip 26: Save by hand from the pause menu

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 120-124.6 (pause-menu save list, slots dated 11/21/26; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p10.mp4 @ 94.6-98.9 (OVERWRITE SAVED GAME?; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 104.6-114.3 (Lucia walks out of Moses' garage into the dark lot), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 126.4-128.4 (the new save, Moses (31%) 11/22/26 02:06, readable 126.9 to 127.9 between fades; "crop": "none")]

[GFX tag "TIP 26: SAVE BY HAND"]
Tip number twenty-six. Save by hand from the pause menu. You do not need a safehouse or a bed to save. That habit is from older GTA games. I saved at Moses' car lot in the middle of the night. Save after every big payout, and before anything risky. A save takes seconds. A bad death can take the whole evening.

### Tip 27: Own it or store it (pays off the open loop)

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p02.mp4 @ 167.5-175 (notice: Unowned vehicles, weapons, or items that weren't stored during your last session were lost; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 17.5-27.5 (tip: Unowned weapons are lost after you die in combat or get arrested; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p01.mp4 @ 110-122 (Jason picks guns off the warehouse floor; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 72.5-81.6 (Stored vehicles: Lucia's '90 Elegy, current personal vehicle; "crop": "none"; push in, a still menu would read as a freeze)]

[GFX tag "TIP 27: OWN IT OR STORE IT"]
Tip number twenty-seven. This is the third way to lose your stuff that I promised you. Anything you do not own, or did not store, is gone when you load back in. The game says it plainly. Unowned vehicles, weapons or items you did not store during your last session were lost. I saw that warning when I loaded back into Jason's house. The game warns that unowned weapons are lost when you die in combat or get arrested. So treat guns you pick up off the floor as temporary. Guides say guns you buy are yours to keep. Cars work the same way. If a car is not registered, it is not yours. Own it, store it, or say goodbye to it.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-31-14).mp4 @ 12-14.6 (the pet snake in the terrarium)]

My house is very secure, though.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p05.mp4 @ 116.6-121.05 s: "Jason: All right, there you go Dolores, watch over the house while I'm gone." (words 116.82-120.84; Jason at the snake terrarium); gameplay HUD, crop sides]

### 13:35 The ask

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p09.mp4 @ 22-28 (dusk drive, the Ganado beside a boat on a trailer)]

If this saved you even one stash bag, subscribe. There are more GTA 6 guides coming.

### 13:41 Chapter: Top five recap

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 39.2-47.5 (services menu, Register $2,150 swap plates; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 85-90.5 (Respray: change the vehicle color to reduce recognition; "crop": "none"; push in, a still menu would read as a freeze), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p09.mp4 @ 244.8-249.6 (map with the red search zone; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p02.mp4 @ 236-241.5 (weapon wheel, stow long guns in the truck; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p11.mp4 @ 124-130.2 (Lucia passes the motel lobby ATM)]

[GFX chapter 7 "TOP FIVE RECAP"]
Here are the five that matter most. Number five. Register the cars you want to keep, and spend your free one wisely. Number four. The Pay 'n' Spray will not take you during a chase. Lose them, then respray. Number three. Stars gone does not mean safe. Stay out of the red zone. Number two. Own it or store it, or it is gone when you load back in. And number one, the most important tip in this video. Bank your cash at an ATM, every time.

### 14:11 Comment question and end

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p01.mp4 @ 22-32.4 (cable-stayed bridge at sunset)]

[GFX endscreen "MORE GTA 6 GUIDES"; caption "GTA 6 STARTER PACK: GTA6.BOSSKG.COM (UNOFFICIAL FAN GUIDE)"]
What is the most cash you have lost to one death so far? Mine is five hundred and thirty-one dollars. Tell me in the comments. See you in Leonida.

## YouTube chapters (estimated from the cue sheet at 175 wpm; take the real times from the render)

### YouTube chapters

```
0:00 New to GTA 6? Start here
0:42 Money
3:38 The cops
6:35 Cars
9:40 Health and stats
10:54 Side hustles
12:24 Keep what you earn
13:41 Top five recap
```

## Open issues

Must decide before narration:

1. **FIXED 2026-11-22: narration now says "His workout reached level three of four." Was: tip 21 says "level two of four", the footage says level 3/4.** The only "Workout Complete" toast (`21-42-41 p05` 226 to 233 s, read frame by frame 226 to 235) says "Reached level 3/4!". The earlier punching-bag session (`21-14-10 p03` 228 to 272 s) shows only "Cardio Workout", no level. The shot is evidence with "crop": "none", so viewers will read 3/4 while hearing "two of four". Options: change the narration to "level three of four" (one word, Bryce's call since the script is approved as is), or keep the words and switch that shot to the default crop so the toast is cut off.

Shots and timing to confirm on the first render:

2. **Cold open WASTED card:** the card shows from about 141.5 s, and `12-47-53` is 145.4 s long, so the range must end at 143.4 (playbook: end 2 s before the clip ends). The card holds about 1.9 s.
3. **Tip 1 "my HUD said zero":** the $0 / minus $531 frame (`12-50-26` 13 to 17.3) is used once, in the cold open, so tip 1 shows the $531 HUD, the crash and the shootout, then a shop hold-up for "Every robbery fills your pocket" (`01-00-16 p08` 143 to 155).
4. **Tip 6:** with the 4-shot cap there is no shot of the ATM by Tucker's till, and the partner-robbery tooltip (about `01-00-16 p06` 127 s) is outside the range; the range shows the mugging tooltip only.
5. **Tip 26 save row:** "Moses (31%) 11/22/26 02:06" is readable only from about 126.9 to 127.9 s in `01-59-31 p02`, between a fade in and a fade out; the 2 s shot (126.4 to 128.4) may trip the renderer's black scan. Fallback: drop it and lengthen the dark-lot walk.
6. **Tip 7 map shot** (`22-40-04 p06` 114.45 to 116.45) is the whole 2 s the map is open and starts on its fade in.
7. **Five shots, not four,** in tip 8 (the stars-gone proof needs both the live HUD at `01-00-16 p10` 55.5 to 64.6 and the map at 64.8 to 71.6, plus the red zone and two drive-aways) and in the top-five recap (one recall shot per line).
8. **Roadmap line** has 3 shots (cops, cars, side hustles); money, health and saving are not pictured because 6 one-second shots would break the 2 s minimum.
9. **Tip 13 panel:** the first theft panel is a Bravado Bison 3800 (key cloner, alarmed, tracker standard), not the Vapid Reclaimer the footage map named. The narration does not name it.
10. **Tip 2 phone shot** (`22-40-04 p06` 168 to 176.5) is Lucia's messages app, not the BuckMe app; no BuckMe app footage exists besides the Scooter Bros request.
11. **Tip 3** uses the Ganado body-work menu (`21-42-41 p07` 20 to 26) instead of the script's `p08` upgrade range, which tip 18 needs as its evidence.
12. **Far-off faces under narration:** Moses stands by the red Elegy in `01-00-16 p12` 11 to 14.1 (tip 15) and Lucia walks up to Moses in `p11` 279 to 284.5 (tip 15); the Taco Bomb clerks (tip 19) and the pawn clerk (tips 1 and 24) are in frame. None is a close talking face; check mouths on the render.
13. **Teaser blur:** P03 and the re-hook blur the unowned notice through the "blur the gore" flag. If the renderer's blur is too weak to hide the text, add a box mask in edits.json.

Bursts to confirm by ear:

14. **Cal, "pick me up some snacks":** cut at 279.72, 0.2 s before "cause I'm confused and hungry"; the profanity starts at 281.2 and is outside the cut. The audio says "Do me a favor and pick me up some snacks", so the cue quotes the full clause.
15. **Lucia, "Guess I'm a natural":** a tight pass hears "Wow, I guess I'm a natural" with "Wow" ending at 189.16; the in point (189.12) may keep the tail of "Wow".
16. **Andy:** Whisper hears "Lucy, there's police everywhere"; the subtitle should read Lucia.
17. **Dolores:** the burst picture (`21-42-41 p05` 116.6 to 121.05) already shows Jason at the snake's terrarium, so no picture swap is needed; the setup line uses the launch-night snake close-up (`12-31-14` 12 to 14.6).
18. **Farmer, "Here's a little thank you":** the first pass stretched the words; the tight pass puts them at 267.42 to 268.72 (cut 267.2 to 268.95).

For the build:

19. **No `at` anchors in the cue syntax.** Shots are ordered and sized to their words at 175 wpm. Guide C reads about 210 wpm untouched, so the renderer's length share will drift. Anchor at least the evidence shots in edits.json, for example: tip 1 "I had five hundred", tip 4 "Early on, that drop-off", tip 8 "Look at my screen here", tip 10 "Denim cutoffs", tip 15 "Moses does your first one free", tip 18 "Nitrous is five thousand", tip 21 "After a session".
20. **Gaps the approved script already listed:** no gun shop visit (tip 27 "guns you buy" is said over guns picked up off the floor), no BUSTED screen, no ATM deposit itself (only the menu and the statement).
21. **Section times** are recomputed from this sheet (Money 0:42, The cops 3:38, Cars 6:35, Health and stats 9:40, Side hustles 10:54, Keep what you earn 12:24, Top five recap 13:41) and differ slightly from the approved stamps.
