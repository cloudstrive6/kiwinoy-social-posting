# GTA 6 Lose the Cops: exact cue sheet (from approved script v1; edit list v2)

**v2, 2026-11-25:** every "guides say / guides agree" line is now stated plainly in my own voice (Bryce: "Refrain from saying 'Guides say...' - we need to own it. Just state the fact"). A line stays only where two independent sources or KG's own footage back it; two one-source lines were cut (the airport rule in tip 7, the bank-app fee in tip 20) and the dog line was rewritten to what two sources agree on. Second sources are in the tip ledger. The independent review of render v1 is applied (see v2 changes at the end). Narration 1,660 words (was 1,727).

Built 2026-11-25 from `Z:\Bryce-Brain\raw-sources\kg-longform-research-2026-11\gta6-lose-the-cops-script-v1.md` (v1, approved by Bryce on 2026-11-25, "Approve as is"). The narration words, the section order and the tips are unchanged; only the approximate [ON SCREEN] and [CUT] cues were replaced with exact [CLIPS] and [GAME AUDIO] cues that `tools/analysis_edl.py` reads (game name `gta6-cops`, base game `gta6`, so Lucia is voiced lu-SEE-yah). Section headings became `Chapter:` headings and tip headings became level-3 headings, as in the beginners guide.

How the seconds were found: every shot range was read on frames pulled from B2 over signed URLs (2 s sheets of every candidate window, 1 s sheets and full-resolution top-right HUD strips where stars or icons are the evidence, 0.25 to 0.5 s steps at the moments that matter: the zone crossing at 01-00-16 p10 2:01, the Sheriff pickup at 1:29.6, the map card at 00-03-41 p02 2:06, the items wheel badge at 00-18-47 p01 1:15.5). Every burst was transcribed with faster-whisper medium.en (CPU only, word timestamps), its edges set on a 20 ms RMS envelope, and its subtitle band read on frames. No blocked range in `config.yaml reels.footage.blocked_ranges` is used, and every narration shot is 2 to 11 s.

Coverage: 129 shots over 38 narration paragraphs, sized to the words at 175 wpm (words / 175 x 60 + 0.5 s per paragraph), plus 6 bursts of 21.5 s; about 10:09 at 175 wpm before the 5 s end tail (render v1 at the backup voice's pace ran 8:55 with a 13 s tail). Guide C reads about 210 wpm untouched, so most proof shots after a paragraph's first carry an `at` anchor in edits.json and land on their words whatever the pace.

Crops: evidence shots (menus, tooltips, HUD figures, maps) carry `"crop": "none"`; HUD close-ups (stars and icons) use a box crop of the top-right corner [0.64, 0, 1, 0.36] (2.8x, 16:9) and one items-wheel close-up uses [0.13, 0.15, 0.63, 0.65], both in edits.json; the phone call shot masks its centred subtitle and keeps the call card; every other narration shot takes the renderer's default subtitle crop. Bursts from cutscenes or subtitle-free gameplay carry `"crop": "none"`; gameplay bursts with HUD carry "crop sides"; the Dunk burst crops its subtitle band because the subtitles either side of the cut carry swears. Teaser shots use the note words "blur the gore" only to switch on the renderer's blur.

Shot keys: `cutscenes/gta6/GTA 6 (2026-11-19 HH-MM-SS).mp4` is launch day (KG's first GTA 6 recordings); the other keys are the 2026-11-21 to 2026-11-23 session parts.

## Script

Cue key. [CLIPS <B2 key> @ a-b (note)] are narration shots in order, shared across the paragraph that follows by range length or started on their anchor words; "crop": "none" marks an evidence shot whose HUD, menu or tooltip must stay in frame. [GAME AUDIO <B2 key> @ a-b s: "line" (word times); crop] is the game's own line with narration paused, framed by narration. Game music and radio stay muted under narration.

### 0:00 Cold open

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 119.3-126.8 (Lucia's white car drives into the red search zone: the bar turns red and three red stars light at 121.3 to 121.5; zoom box on the top right (a centred push would cut the stars at the edge); box crop in edits.json)]

[GFX lower "GTA 6: HOW TO LOSE THE COPS"]
You think you lost the cops in GTA 6? Your stars can come back. Here is why, before you lose your cash.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 136-140.5 (night chase, four stars), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 125.4-128.4 (pause map card: The cops are actively looking for you in this area. VEHICLE KNOWN, APPEARANCE KNOWN, OUTFIT KNOWN (card readable 126.0 to 127.2); "crop": "none"; push in; anchored at "First problem" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 141-143.3 (slow-motion sheriff SUV, then the WASTED card from about 141.5; anchored at "Get caught or killed" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 13-17.3 (HUD box crop: wallet $0 with red minus $531 after the respawn, held to the word Third; box crop in edits.json; anchored at "the cash in your pocket" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 22-26.5 (HUD box crop: four white stars in the six-slot meter over Vice City; box crop in edits.json; anchored at "Third" in edits.json)]

[GFX caption "20 TIPS TO LOSE THE COPS IN LEONIDA"]
This is how I shake the police in Leonida, and make them forget me. First problem. The cops remember your face, your clothes and your car, even after the stars go. Second. Get caught or killed, and the cash in your pocket is gone. Third. Reach six stars, and there is no escape at all.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 61-64.6 (live HUD with no stars, teaser blur (blur the gore); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 72.5-76.5 (the white car on the causeway, no stars)]

And one move can bring the cops right back. I made it on camera. I will show you near the end.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 70-72 (HUD box crop: four white stars; box crop in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 240-242 (HUD box crop: two hollow stars and the gun icon; box crop in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 270-272 (Lucia with the long gun along a container wall), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 74.8-76.8 (the items wheel: UNSAVED EYEWEAR ON with its red badge; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 240.8-242.8 (two red stars at the toll plaza (after the crude overhead sign leaves frame at 240.6); "crop": "none")]

First, reading the stars. Then what makes it worse, breaking away, changing your look, and what comes after. The top five are at the end.

### 0:44 Chapter: Read the screen

### Tip 1: Read the colour of your stars

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 61-64 (HUD box crop: the six-slot meter, four empty slots and two red stars, against cloud; box crop in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 30-33 (HUD box crop: four white stars (outfit, face and car icons); box crop in edits.json; anchored at "White stars mean" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 40.5-45.5 (the airliner low over the suburbs, four stars; anchored at "I had four white ones" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 72.5-79 (Jason runs through the pines after the crash), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 155.2-157.9 (HUD box crop: three red stars beside three empty slots (before the billboard at 158); box crop in edits.json; anchored at "Red stars mean" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 230.5-233 (HUD box crop: two hollow stars; box crop in edits.json; anchored at "Hollow stars mean" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 86-90 (the white sedan on the highway, two red stars; anchored at "So glance up" in edits.json)]

[GFX chapter 1 "READ THE SCREEN"; tag "TIP 1: READ THE STAR COLOUR"]
Tip number one. Read the colour of your stars. The meter goes up to six. White stars mean they are chasing you, and they can see you. I had four white ones, running from a crashed plane. Red stars mean you got away, and the area is still hot. Hollow stars mean a crime is being looked into. Learn all three. So glance up before you move. The colour tells you whether to run or to hide.

### Tip 2: The icons under the stars (the most important tip)

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 59.5-66 (HUD box crop: two red stars with the hanger, person and car icons; box crop in edits.json; push in), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 235.8-239.8 (HUD box crop: two hollow stars and the gun icon; box crop in edits.json; anchored at "The gun is your weapon" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 162-167.8 (HUD stars with the hanger and face icons; "crop": "none"; anchored at "There are two more" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 127-134 (night chase, four stars; anchored at "Each icon is one more" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 125.8-130.8 (Lucia in town with three red stars, hanger and person icons, red bar; "crop": "none"; anchored at "Losing the cops" in edits.json)]

[GFX tag "TIP 2: THE ICONS UNDER THE STARS"; slam "CLEAR EVERY ICON."]
Tip number two, and it is the most important tip in this video. The red icons under the stars are what the police know about you. The coat hanger is your outfit. The little person is your face. The car is your vehicle. The gun is your weapon. There are two more, for a security camera and for your partner. Each icon is one more way to spot you. Losing the cops in GTA 6 means clearing those icons, one by one.

### Tip 3: Open the map and read the search area

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 67-71 (the white sedan with two red stars and three icons; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 124.6-128.4 (pause map card: VEHICLE KNOWN, APPEARANCE KNOWN, OUTFIT KNOWN (readable 126.0 to 127.2); "crop": "none"; push in; anchored at "Mine said" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 128.6-133 (the pause map scrolls to Hamlet; "crop": "none"; anchored at "That is your to-do list" in edits.json)]

[GFX tag "TIP 3: READ THE SEARCH AREA"; caption "VEHICLE KNOWN, APPEARANCE KNOWN, OUTFIT KNOWN"]
Tip number three. Open the map after a crime. The search area spells it out in words. Mine said vehicle known, appearance known, outfit known. That is your to-do list. Clear it, line by line.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 139-143.4 (the white car on the country road, Weasel News on the radio)]

And in Leonida, the local news is always happy to help.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 145.60-149.22 s: "Weasel News (radio): a man and woman had been caught on CCTV fleeing the scene." (words 145.68-149.16; 'that' ends about 145.6, next 'He said' 149.32; news read, no music heard in the window; HUD and minimap at the edges); gameplay HUD, crop sides]

### Tip 4: The police are not on your minimap

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 84-87.4 (the white car takes the bend), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 88.7-90.4 (a SHERIFF pickup passes at 89.6 to 90.3; "crop": "none"; anchored at "A Sheriff truck" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 90.4-92.9 (minimap box crop: the route line and no police marker (88.7 to 92.0 checked); box crop in edits.json; anchored at "my minimap showed no police" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 93-98 (open road, minimap clear; "crop": "none"; anchored at "Rob Nelson said" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 160-166 (night chase, police lights behind; anchored at "So when you are wanted" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 106.5-109.5 (the truss bridge, minimap clear; "crop": "none"; anchored at "Your minimap will not" in edits.json)]

[GFX tag "TIP 4: NOT ON YOUR MINIMAP"]
Tip number four. Do not trust your minimap. A Sheriff truck drove right past me here, and my minimap showed no police marker. Rockstar's Rob Nelson said the police do not show up on the radar. They show up when you use Focus. So when you are wanted, use Focus to find them. Your minimap will not warn you.

### 2:20 Chapter: What makes it worse

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 112-117 (the Driftair airliner taxis across the apron)]

[GFX chapter 2 "WHAT MAKES IT WORSE"]
Now you can read the screen. Section two is what makes it worse.

### Tip 5: Put your gun away

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 221-226.5 (Jason walks out onto the deck with a rifle on his back (never the inside of the house); "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 226.5-230.4 (HUD box crop: two hollow stars and one icon, a gun; box crop in edits.json; anchored at "hollow stars, and one icon" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p01.mp4 @ 233.2-235.8 (Jason at the pickup's tailgate; "crop": "none"; anchored at "A pistol can be" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 283.6-287.4 (Lucia crouched with the long gun; tooltip: When the cops are looking for you, carrying a visible weapon may draw their attention; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-23 03-59-02) p09.mp4 @ 26-30.5 (at the trunk: CLEAR & STOW LONGARMS prompt; "crop": "none"; anchored at "A long gun has to be" in edits.json), cutscenes/gta6/GTA 6 (2026-11-23 03-59-02) p09.mp4 @ 49.5-56.5 (STOW LONGARMS prompt at the open trunk; "crop": "none"; push in; anchored at "At the trunk" in edits.json)]

[GFX tag "TIP 5: PUT YOUR GUN AWAY"]
Tip number five. Put your gun away. Here I am walking out of a house with a rifle on my back. Two hollow stars, and one icon under them. A gun. At that moment, my weapon was the only thing on their list. A pistol can be holstered. A long gun has to be dropped, or stowed in a trunk. At the trunk, look for stow longarms. Out of sight is out of the description.

### Tip 6: Leave the cops standing

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p10.mp4 @ 254.5-259.5 (police cars chase the ambulance (cutscene; subtitles cropped)), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p10.mp4 @ 274.5-281.5 (tip: Disabling a pursuing cop vehicle without casualties will contribute toward a hardened criminal profile; subtitle masked (a line at 275.7 to 277.6 swears); "crop": "none"; subtitle mask in edits.json; anchored at "A tip says disabling" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p10.mp4 @ 262-268.5 (tip: Use combat focus while aiming to see vulnerable areas to target on vehicles; subtitle masked; "crop": "none"; subtitle mask in edits.json; anchored at "Another says combat focus" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p10.mp4 @ 268.6-273.5 (firing at the pursuing police car; anchored at "Aim for the car" in edits.json)]

[GFX tag "TIP 6: LEAVE THE COPS STANDING"]
Tip number six. Leave the cops standing. Killing police brings a more aggressive response. It also pushes your criminal profile toward violent. The game tracks the opposite too. A tip says disabling a pursuing cop car without casualties counts toward a hardened profile. Another says combat focus shows the vulnerable areas on their cars. Aim for the car, and leave the driver alone.

### Tip 7: Some crimes send the stars flying

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 10.5-16 (the airport restroom, two red stars; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 98-102.6 (Jason runs up the boarding stairs of the Driftair jet; anchored at "Then I took a passenger jet" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 103.5-111 (taxiing; tooltip: Flying at a lower altitude can reduce your chance of being spotted by law enforcement; stars 2 to 4 at about 106 to 108; "crop": "none"; anchored at "Before it left the ground" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 189-191.4 (a fighter jet appears beside the airliner, four stars; "crop": "none"; anchored at "Then a fighter jet" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-39-35).mp4 @ 181.5-186.5 (Jason runs along the airport terminal curb; anchored at "If you want an easy" in edits.json)]

[GFX tag "TIP 7: SOME CRIMES SEND STARS FLYING"]
Tip number seven. Some crimes send the stars flying. At the airport, I already had two stars. Then I took a passenger jet off the apron. Before it left the ground, I had four. The game told me that flying lower can reduce my chance of being spotted. Then a fighter jet pulled up beside me. If you want an easy escape, do not start at an airport.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 18.2-21.8 (Jason leaves the restroom into the concourse, security ahead)]

To be fair, someone gave me very clear instructions.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 21.90-24.85 s: "Airport security: Don't move! Don't you move!" (words about 22.0-24.50; next 'Hands up!' 25.26; no subtitles on screen; the script's "You moved!" was a Whisper mishearing of these two lines); gameplay HUD, crop sides]

### Tip 8: Never let it reach six stars

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 0.5-7.5 (the airliner over Vice City, four stars in the meter; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 7.6-12.6 (the airliner banks over the city), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 14-21 (the airliner climbs over the coast)]

[GFX tag "TIP 8: NEVER REACH SIX STARS"]
Tip number eight. Never let it reach six stars. At six, you can no longer lose your wanted level. The police and the military keep coming until you are busted or wasted. There is no clever trick at six. So the moment you see five, stop adding crimes, and start running.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-23 01-40-40) p07.mp4 @ 65-68.9 (Lucia pulls up at Watkins Auto Parts at night)]

Someone at Moses' garage knows how far it can go.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-23 01-40-40) p07.mp4 @ 88.85-92.20 s: "Garage mechanic: Got so bad once, I had bounties on me in three different states." (words 88.98-92.08; 'streets.' ends 88.48, next 'Nowadays' 92.34; the subtitle on screen reads the same line; the mechanic answers Lucia's question about racing; no profanity); "crop": "none"]

### 4:09 Chapter: Break away

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 144-150.5 (night chase, a police car alongside)]

[GFX chapter 3 "BREAK AWAY"]
Keep the stars low, and you can get away. So section three is how to break away.

### Tip 9: Break line of sight, then leave the red zone

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 84-90 (Jason runs through tall grass, four stars), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p09.mp4 @ 214.3-217.4 (pause map: the red search zone; "crop": "none"; push in; anchored at "The red area on your map" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 116-119.5 (the white car comes into town, plain bar along the top; "crop": "none"; anchored at "Here is a landmark" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 119.6-125.4 (the zone edge reaches the minimap at 121.0, the bar turns red and three stars light at 121.3 to 121.5; no push, the stars sit at the right edge; "crop": "none"; anchored at "In my footage" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 150-154.5 (red bar and three red stars in town; "crop": "none"; anchored at "Treat a red bar" in edits.json)]

[GFX tag "TIP 9: BREAK LINE OF SIGHT"]
Tip number nine. Break line of sight, then get out of the red zone. The red area on your map is where they are searching. You have to leave it unseen. Here is a landmark. Watch the bar across the top of your screen. In my footage, it turned red the moment I crossed into the zone. Treat a red bar as your warning.

### Tip 10: On foot, hide

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p04.mp4 @ 77.5-83.4 (Lucia crouched in the bushes by the bar deck), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 275-283.4 (Lucia with the long gun behind a container, stars up), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 97.5-103.5 (Lucia creeps past a dumpster and barrels in the junkyard, stars up; anchored at "crept through a whole" in edits.json)]

[GFX tag "TIP 10: ON FOOT, HIDE"]
Tip number ten. On foot, hide. Bushes, shipping containers, dumpsters. Lucia crept through a whole junkyard like this, with the stars still up. Stay hidden until the search moves on. One catch. In bigger chases, police dogs can run you down. If dogs show up, keep moving through cover. Out of sight is the whole game.

### Tip 11: Know what winning looks like

[CLIPS cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p01.mp4 @ 185-188.3 (Lucia's red sedan at dusk, two stars; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p01.mp4 @ 188.4-195.2 (HUD box crop: two stars lit (189 to 191), dim (192 to 193), gone (194); box crop in edits.json; anchored at "Watch the top right" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-39-35).mp4 @ 154.5-159.5 (zoom box: the toast Heat cleared (right, 156 to 159); box crop in edits.json; anchored at "On launch night" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 98.5-103 (the white car on the open road, no stars; anchored at "When you see it" in edits.json)]

[GFX tag "TIP 11: KNOW WHAT WINNING LOOKS LIKE"]
Tip number eleven. Know what winning looks like. Here, Lucia is driving with two stars. Watch the top right. They dim, and then they are gone. On launch night, the game also flashed heat cleared when my star went away. When you see it, slow down and blend into the traffic. The cops are gone. The heat might not be.

### Tip 12: Ditch the car

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 48-53.5 (the airliner drops low over the swamp forest; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 53.5-58.5 (HUD box crop: four stars with the hanger, person and car icons; box crop in edits.json; anchored at "In the air" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 64-69 (HUD box crop: four stars, hanger and person only, the car icon gone; box crop in edits.json; anchored at "Once I was on foot" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 41-46.5 (Lucia walks up to a parked white car on the bridge; anchored at "So if they know" in edits.json)]

[GFX tag "TIP 12: DITCH THE CAR"]
Tip number twelve. Ditch the car. Watch the icons when my plane went down. In the air, they knew my outfit, my face and my vehicle. Once I was on foot, the vehicle icon was gone. A different car does the same job. So if they know your ride, leave it somewhere quiet and find another.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 234-238 (the white car pulls into Watkins)]

Of course, a new car comes with its own questions.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 289.45-294.60 s: "Moses: I don't know nothing about you, except you got a name and a ride that ain't yours." (words 289.60-294.22; 'know.' ends 288.84, next 'Maybe' 295.20; the subtitle on screen reads the same line; Moses on his creeper); "crop": "none"]

### 5:48 Re-hook

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 58.8-61 (the white car on the causeway (teaser blur, blur the gore)), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 73.9-75.95 (wheel box crop, unblurred: the eyewear and cap slots with their red badges; box crop in edits.json; anchored at "the free disguise" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 242.6-244.8 (the toll plaza (teaser blur, blur the gore); "crop": "none"; anchored at "still owe you" in edits.json)]

We are past halfway. Next, the free disguise that takes two seconds. And I still owe you that move.

### 5:55 Chapter: Change your look

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 213.5-219.3 (Lucia walks into the clothing store, Buy a new outfit)]

[GFX chapter 4 "CHANGE YOUR LOOK"]
The car was easy. You are harder to change. So section four is your disguise.

### Tip 13: Check the items wheel for the red badge

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 71-73.9 (the white sedan on the highway, then the items wheel opens; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 73.9-75.95 (wheel box crop: BASEBALL CAP and UNSAVED EYEWEAR both ON with red badges (to 74.8), the cap goes OFF, the eyewear selected ON with its badge (75.2 to 75.95); held until the words took them off; box crop in edits.json; anchored at "small red badge" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 75.4-79.4 (HUD box crop: three icons (hanger, person, car) to 76.6, then the glasses go OFF and the person icon is gone from 76.8; box crop in edits.json; anchored at "I took them off" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 82-86 (back on the highway, two red stars; anchored at "seconds. No shop" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 242.8-248.4 (Lucia's items wheel: Rod's Racing Cap, glasses ON; "crop": "none"; anchored at "Check the wheel" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 90-94.5 (the white sedan heads for the toll plaza; anchored at "This is tip number two" in edits.json)]

[GFX tag "TIP 13: CHECK THE ITEMS WHEEL"]
Tip number thirteen. Open your items wheel. The game marks each item the police know with a small red badge. One was on Jason's glasses. I took them off, and the face icon vanished from under the stars. Two seconds. No shop, no cost. Check the wheel every time the stars go up. This is tip number two in action. One icon down.

### Tip 14: Mask on for the job, off after

[CLIPS cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p02.mp4 @ 54.5-58.5 (Lucia drives under the overpass at dusk), cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p02.mp4 @ 59.3-64.8 (items wheel: FACE WRAP ON and DOUBLE BRIDGE AVIATORS, both taken off; "crop": "none"; push in; anchored at "face wrap and glasses" in edits.json), cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p02.mp4 @ 65.2-69.8 (toast: Appearance heat cleared (66 to 68); "crop": "none"; anchored at "the game said appearance" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p06.mp4 @ 139-145.3 (Lucia puts on the cap from the items wheel; anchored at "The mask sits" in edits.json)]

[GFX tag "TIP 14: MASK ON, MASK OFF"]
Tip number fourteen. Wear a mask for the job, and take it off after. A mask helps hide your face. Here, Lucia had a face wrap and glasses on. She took both off, and the game said appearance heat cleared. The mask sits on the same items wheel. Put it on before. Take it off after.

### Tip 15: Change your outfit once you are out of sight

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 177-186.5 (the tow truck leaves with stars still up; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 188-193 (stars gone, the HUD shows money only; "crop": "none"; anchored at "Only once the stars" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 207.5-213.4 (the tow truck parks, Lucia walks to the store), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 260.5-266 (DENIM CUTOFFS $12; "crop": "none"; anchored at "Denim cutoffs" in edits.json)]

[GFX tag "TIP 15: CHANGE CLOTHES OUT OF SIGHT"; counter $12 "DENIM CUTOFFS"]
Tip number fifteen. Change your outfit, but only once you are out of sight. A new outfit clears outfit known, once you break line of sight. Lucia slipped away from a junkyard in a tow truck. Only once the stars were gone did she walk into a clothing store. Denim cutoffs were twelve dollars. You can also keep a spare outfit in your car's trunk. Change after you vanish, never before.

### Tip 16: Paint the car after the chase

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 121-125 (Lucia climbs into the tow truck, stars up), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p07.mp4 @ 125.5-132 (tooltip: You can't enter a Pay 'n' Spray when the cops are nearby or in pursuit; "crop": "none"; anchored at "The game says you cannot" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 50.5-55.8 (Moses' services menu: RESPRAY, Change the vehicle color to reduce recognition, This vehicle has no heat; "crop": "none"; push in; anchored at "The respray menu says" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p02.mp4 @ 92.5-99.5 (respray preview, $100; "crop": "none"; anchored at "At Moses' shop" in edits.json)]

[GFX tag "TIP 16: PAINT IT AFTER THE CHASE"; counter $100 "RESPRAY AT MOSES' SHOP"]
Tip number sixteen. Paint the car after the chase. The game says you cannot enter a Pay 'n' Spray when the cops are nearby or chasing you. Lose them first. Then respray. The respray menu says a new colour reduces recognition. It even tells you whether the car has heat. At Moses' shop, a respray was a hundred dollars. Escape first. Paint second.

### Tip 17: Split up, and watch for cameras

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p12.mp4 @ 109.5-118.5 (Lucia calls Jason (call card), stand-in for splitting up; subtitle masked; "crop": "none"; subtitle mask in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-39-35).mp4 @ 192-200 (the airport check-in hall, a crowd (stand-in; no camera or CCTV icon shown); anchored at "Camera footage stored" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-39-35).mp4 @ 202-205.5 (Jason walks to the LineAir counters)]

[GFX tag "TIP 17: SPLIT UP, WATCH FOR CAMERAS"]
Tip number seventeen. Split up, and watch for cameras. The police can know you as a couple. Splitting Jason and Lucia up makes you harder to spot. Camera footage stored on site can be destroyed. Footage backed up to the cloud cannot. So destroy the recording, or keep your face off camera.

### 7:47 Chapter: After the chase

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 0.5-5.5 (Lucia walks the bridge into the sun)]

[GFX chapter 5 "AFTER THE CHASE"]
Now you look like someone else. Last section. What happens after the chase.

### Tip 18: Stars gone does not mean safe (pays off the open loop)

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 12.5-15.5 (Lucia on the bridge beside a white sedan), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 59.3-64.6 (live HUD in the white car: no stars; "crop": "none"; anchored at "Look at my screen" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 66-69.9 (zoom box on the pause map: three red stars (top right), the red zone round Port Gellhorn, APPEARANCE KNOWN, OUTFIT KNOWN (68 to 69); box crop in edits.json; anchored at "Now open the map" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 110-116 (the white car drives on into town, no stars; "crop": "none"; anchored at "I changed nothing" in edits.json), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 119.4-123 (the crossing: the bar turns red and three stars light at 121.3 to 121.5; zoom box on the top right; box crop in edits.json; anchored at "The second I crossed" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 232-235.4 (Jason's pickup on the highway, no stars; "crop": "none"; anchored at "Jason's stars came back" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 125.4-128.4 (Jason's map: VEHICLE KNOWN, APPEARANCE KNOWN, OUTFIT KNOWN (126.0 to 127.2); "crop": "none"; anchored at "with his map still" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 240.8-242 (HUD box crop: two red stars at the toll plaza (after the crude overhead sign leaves frame at 240.6); box crop in edits.json; anchored at "red stars at a toll" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 242-245.1 (the stars turn white, a Hamlet Police car alongside; "crop": "none"; anchored at "white seconds later" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 249.5-252 (driving away, two white stars; anchored at "The heat stays around" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 22-40-04) p07.mp4 @ 166-170.4 (night chase, police lights ahead; anchored at "So go around" in edits.json)]

[GFX tag "TIP 18: STARS GONE IS NOT SAFE"; slam "THE HEAT STAYS."]
Tip number eighteen. This is the move I promised you. Stars gone does not mean safe. Look at my screen. No stars on the HUD. Now open the map. Three red stars are still there, with a red zone round the town I was driving to. Appearance known. Outfit known. I changed nothing, and drove straight in. The second I crossed the line, three stars lit up again. Jason's stars came back too, in the same pickup, with his map still saying vehicle known. Two red stars at a toll plaza, white seconds later. My footage does not show what set those off. The heat stays around where you were last seen. So go around the zone, or clear your icons before you go in.

### Tip 19: Lie low and let it cool

[CLIPS cutscenes/gta6/GTA 6 (2026-11-23 01-40-40) p04.mp4 @ 269-280 (Lucia's campsite by the fire at night), cutscenes/gta6/GTA 6 (2026-11-23 01-40-40) p04.mp4 @ 256.5-260.5 (the campsite tent and fire (quiet; the barge clip has song lyrics on its radio))]

[GFX tag "TIP 19: LIE LOW, LET IT COOL"]
Tip number nineteen. Lie low, and let it cool. The heat on an area fades with time, as long as you stop committing crimes there. So do something quiet somewhere else. Come back later. The town will still be there.

### Tip 20: Bank your cash before you start trouble

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 139-142.8 (slow-motion sheriff SUV, then WASTED), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 13-17.3 (HUD wallet $0 with red minus $531; "crop": "none"; anchored at "Mine was five hundred" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p11.mp4 @ 170-173.6 (Jason and Lucia walk down the stairs (subtitles cropped); anchored at "Getting busted takes" in edits.json), cutscenes/gta6/GTA 6 (2026-11-19 12-50-26).mp4 @ 19.5-25.5 (tip: Unowned weapons are lost after you die in combat or get arrested; "crop": "none"; anchored at "And the game says" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 172-177.5 (Lucia steps up to the motel lobby ATM; anchored at "So bank it" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p01.mp4 @ 178.8-181.8 (ATM screen: Your Account, Deposit / Withdraw / Transactions (from 179.0; the statement list comes at 182); "crop": "none")]

[GFX tag "TIP 20: BANK YOUR CASH FIRST"; counter -$531 "LOST IN ONE DEATH"]
Tip number twenty. Bank your cash before you start trouble. If you get wasted, the cash in your pocket is gone. Mine was five hundred and thirty-one dollars. Getting busted takes your pocket cash too. And the game says it plainly. Unowned weapons are lost after you die in combat or get arrested. So bank it at an ATM first. Then go and cause problems.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p11.mp4 @ 174.2-178.2 (Jason walks to the cops below the stairs (subtitles cropped))]

And when they do catch you, they keep it short.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-21 21-42-41) p11.mp4 @ 182.75-184.55 s: "Officer: Okay, you are under arrest!" (words 183.04-184.36; the line before (it swears) ends 182.52, next 'And' 184.94; subtitle shows from 182.85, no earlier line on screen at 182.6); "crop": "none"]

### 9:18 The ask

[CLIPS cutscenes/gta6/GTA 6 (2026-11-22 01-59-31) p01.mp4 @ 113-119 (cinematic night drive over the bridge)]

If this kept your stars down even once, subscribe. There are more GTA 6 guides coming.

### 9:24 Chapter: Top five recap

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-44-38).mp4 @ 180-186.5 (recall: the airliner over the city, four stars; "crop": "none"), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p09.mp4 @ 214.3-217.4 (recall: the red search zone; "crop": "none"; anchored at "Number four" in edits.json), cutscenes/gta6/GTA 6 (2026-11-23 02-14-28) p01.mp4 @ 180-184.6 (recall: the items wheel, Rod's Racing Cap; "crop": "none"; anchored at "Number three" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-03-41) p02.mp4 @ 240.8-244.4 (recall: two red stars at the toll plaza, then white; "crop": "none"; anchored at "Number two" in edits.json), cutscenes/gta6/GTA 6 (2026-11-21 00-18-47) p01.mp4 @ 66-71 (recall: HUD box crop, the icons under the stars; box crop in edits.json; anchored at "And number one" in edits.json)]

[GFX lower "TOP FIVE RECAP"]
Here are the five that matter most. Number five. Never let it reach six stars. Number four. Break line of sight, and get out of the red zone. Number three. Check your items wheel for the red badge, and take that item off. Number two. Stars gone does not mean safe. Go around the zone. And number one, the most important tip in this video. Clear every icon under your stars.

[CLIPS cutscenes/gta6/GTA 6 (2026-11-23 05-04-53) p04.mp4 @ 240.8-244.8 (she walks up to the trailer (subtitles cropped; the shot of her bending at the fence, 236 to 240.6, is out))]

Even after all that, people still get the wrong idea about me.

[GAME AUDIO cutscenes/gta6/GTA 6 (2026-11-23 05-04-53) p04.mp4 @ 249.00-253.62 s: "Dunk: I thought you was a cop or somethin'. Her reply: No, still not a cop, Dunk." (words 249.20-253.35; 'freaked me out.' ends 248.82, the next line opens with a swear at 253.90; the subtitle before this one carries a swear and stays on screen to about 251.2, and the next one appears at about 253.6, so the subtitle band is cropped); crop the subtitle]

### 9:58 Comment question and end

[CLIPS cutscenes/gta6/GTA 6 (2026-11-19 12-47-53).mp4 @ 36.6-40.4 (the airliner over the suburbs, four stars (no speech in the clip)), cutscenes/gta6/GTA 6 (2026-11-22 01-00-16) p10.mp4 @ 24-38 (Lucia walks the bridge into the sun (traffic only; the barge and bridge clips had song lyrics on the radio); anchored at "Tell me in the comments" in edits.json)]

[GFX endscreen; caption "GTA 6 STARTER PACK: GTA6.BOSSKG.COM (UNOFFICIAL FAN GUIDE)"]
What is the highest wanted level you have hit so far, and how? Mine was four stars, in a passenger jet. Tell me in the comments. See you in Leonida.

## YouTube chapters (estimated from the cue sheet at 175 wpm; take the real times from the render)

### YouTube chapters

```
0:00 How to lose the cops in GTA 6
0:44 Read the screen
2:20 What makes it worse
4:09 Break away
5:55 Change your look
7:47 After the chase
9:24 Top five recap
```

## Cuts confirmed by ear (faster-whisper medium.en, CPU, 2026-11-25)

| Burst | Cut | Words heard | Speaker | Profanity check |
|---|---|---|---|---|
| Tip 3 news | `01-00-16 p10` 145.60-149.22 | "a man and woman had been caught on CCTV fleeing the scene." 145.68-149.16 | Weasel News radio read | none in the cut; the next sentence is outside |
| Tip 7 instructions | `12-44-38` 21.90-24.85 | "Don't move! Don't you move!" about 22.0-24.50 | airport security officers, not named | none; no subtitles on screen |
| Tip 8 bounties | `01-40-40 p07` 88.85-92.20 | "Got so bad once, I had bounties on me in three different states." 88.98-92.08 | the garage mechanic at Watkins, answering Lucia's "So, you race or anything when you're not in the shop?" | none |
| Tip 12 Moses | `01-00-16 p10` 289.45-294.60 | "I don't know nothing about you, except you got a name and a ride that ain't yours." 289.60-294.22 | Moses (subtitle and his close-up) | none |
| Tip 20 arrest | `21-42-41 p11` 182.75-184.55 | "Okay, you are under arrest!" 183.04-184.36 | officer | the swearing line before ends 182.52 and its subtitle is gone by 182.6 |
| Recap Dunk | `05-04-53 p04` 249.00-253.62 | "I thought you was a cop or somethin'." "No, still not a cop, Dunk." 249.20-253.35 | Dunk, then the player character (not named: the log cannot confirm she is Lucia) | starts after "you freaked me out." (ends 248.82, silence to 249.14); ends on "Dunk." (silence 253.36 to 253.88, the next line's swear starts 253.90); subtitle band cropped because the subtitle before (it swears) stays up to 251.2 and the next one appears at 253.6 |

No cut was dropped.

## Open issues

Changed from the approved cues (no narration word changed):

1. **Tip 7 game line is "Don't move! Don't you move!", not "You moved!".** Whisper medium.en heard "Don't move!" (22.28-23.06) and "Don't you move!" (23.72-24.50); there is no "You moved!" anywhere in 14 to 42 s, and no subtitles show in the window. The approved quote came from an older transcript. The setup line ("someone gave me very clear instructions") fits the real words, so the cut stays with the corrected quote; Bryce can drop it if he prefers.
2. **Tip 12 Moses line is at 4:49.5 to 4:54.6, not 4:08 to 4:43.** The footage log's event range (248 to 283) was too early; Whisper and the subtitle frames put the line at 289.60 to 294.22. The burst ends 4.6 s before the clip's end (bursts play their exact range).
3. **Tip 19 swamp meditation dropped.** `03-59-02 p09` 3:00 to 3:15 is a face close-up with dialogue subtitles (a talking face under narration); tip 19 runs on the campsite (`01-40-40 p04` 4:29 to 4:40) and a container barge at sunset (`05-04-53 p03` 2:57.5 to 3:01.5).
4. **Tip 20 SURRENDER prompt not shown.** Its only frames (`12-44-38` 22.8 to 24.8) are the tip 7 burst picture; tip 20 shows the stairs before the scripted arrest (`21-42-41 p11` 2:50 to 2:53.6) and the motel ATM (`23-37-28 p01` 2:52 to 3:01.5, as verified for the beginners guide) for "bank it at an ATM".
5. **The six-slot meter:** tip 1's "goes up to six" plays `00-18-47 p01` 61 to 64 in the HUD box crop (four empty slots and two red stars against cloud; against bright sky the empty slots vanish). That range overlaps tip 2's opening HUD shot (59.5 to 66, same icons, 20 s later); accepted, since no other clip shows all six slots this cleanly. The crossing at `01-00-16 p10` 2:01 plays in the cold open, tip 9 and tip 18 by design (hook, rule, payoff).
6. **The VEHICLE KNOWN map card** (`00-03-41 p02`) is readable for only 1.2 s (126.0 to 127.2); it plays in the open (problem one), tip 3 (anchored at "Mine said", push in, with a caption graphic carrying the three words) and tip 18 (Jason's map). It is the only VEHICLE KNOWN card in KG's footage.

Footage facts found while scrubbing (not narrated; for the claims check and the reviewer):

7. `01-00-16 p10` 0:56 to 0:57: a person lies on the road by the white car's open door (the car was taken from its driver). No shot uses 0:47 to 0:58.
8. `01-00-16 p10` 2:11 to 2:17: after the crossing Lucia opens the items wheel (cap, glasses, parachute). Tip 18 says "I changed nothing, and drove straight in", true up to the crossing at 2:01; no shot uses 2:11 to 2:17.
9. `01-00-16 p10` 4:00: "Heat cleared" shows as the white car rolls into Moses' garage. Not used.
10. `02-14-28 p01` 3:05 to 3:14: the two stars go lit (3:05), dim (3:06 to 3:08), lit again (3:09 to 3:11), dim (3:12 to 3:13), gone (3:14). The tip 11 box crop plays 3:08.4 to 3:15.2 (lit, dim, gone). "They dim, and then they are gone" holds.
11. `01-00-16 p07` 1:26 to 1:35: Lucia's phone shows a text with a swear; no shot uses it. 4:00: an "Outfit heat cleared" toast in the clothing store (not used).
12. `01-00-16 p06` 4:44 to 4:52: tooltip "When the cops are looking for you, carrying a visible weapon may draw their attention", shown under tip 5 (283.6 to 287.4, before a dog walks in at 4:48).

For the narrate and render steps:

13. **Pace.** 1,660 words (v2) estimate 10:09 at 175 wpm with the bursts; render v1 ran 8:55 on the backup voice. Proof shots are anchored, so a faster read only shortens b-roll; set the EDL `"pace"` by ear if the cut should run nearer 10 minutes.
14. **End screen (v2).** Bryce, 2026-11-25: about 5 s from the narrator's last word to the end is enough. `beat_tail` b043 = 4.6 s (v1 measured 13.4 s from "See you in Leonida" to the end with a 13 s tail, so wav tail plus the 0.35 s pause is about 0.4 s). The end card (`last`: 20) covers the whole last beat, about 12.4 s at v1's pace; 20 s would put it over the Dunk punchline, so it stops there. Under it: the airliner (the jet the outro mentions; tip 7 holds the proof) then Lucia on the bridge; the WATCH NEXT slot carries no text.
15. **Far-off faces under narration:** the mechanic stands in the Watkins setup shot (`01-40-40 p07` 1:05 to 1:09), Jason's face shows briefly on the deck (`00-03-41 p01` 3:42); none is a close talking face. Check mouths on the render.
16. **Box crops at 2.8x** come from 1080p sources, so the HUD close-ups are soft; they are held 2 to 6.5 s.

Independent review (one reviewer agent, 2026-11-25, given only this cue sheet, the EDL and a contact sheet per section): **PASS WITH FIXES**, 2 must-fixes, both applied:

17. **Caption G02** said "20 TIPS FROM MY OWN CHASES IN LEONIDA", more than the narration claims (several tips are from guides). Now "20 TIPS TO LOSE THE COPS IN LEONIDA".
18. **Tip 1 "The meter goes up to six"** played a box crop where only four slots read against the sky. Now `00-18-47 p01` 61 to 64 (six slots readable); "Red stars mean" moved to `01-00-16 p10` 2:35.2 to 2:37.9 (three red beside three empty).

Should-fixes applied: subtitle masks on both ambulance tooltip shots (`22-40-04 p10`, a line at 275.7 to 277.6 swears); the toll-plaza shots now start at 240.8, after a crude overhead sign leaves the frame (it reads in 239 to 240.6); tip 18's last shot no longer plays `01-00-16 p10` 2:34 to 2:39 (a crude billboard from 2:38) and uses the night chase instead; push-in removed from shots whose proof sits at the frame edge (the map stars in tip 18, the crossing in tip 9, the low-altitude tooltip, Heat cleared, the unowned-weapons tip); the tip 20 ATM shot now starts on the Your Account screen (178.8). Checked and kept: the STOW LONGARMS prompt shows bottom right from 26 s in `03-59-02 p09` (a vape pickup prompt shares the frame); the phone-call mask is in edits.json; burst crop "band" is the renderer's crop for "crop sides" (beginners guide convention); the Dunk scene's player character is blonde in a yellow cap and is never named.

## v2 changes (2026-11-25, after the independent review of render v1, 8:55)

Must-fixes:
1. Tip 18 crossing: `01-00-16 p10` 119.4 to 123.0 (stars light 121.3 to 121.5), anchored on "The second I crossed", zoom box [0.25, 0, 1, 0.75] towards the top right (the renderer's push is centred and would cut the stars at the frame edge, so the zoom is a fixed box); Jason's shot keeps its own anchor after it.
2. Tip 20 counter: the -$531 counter now starts at "Getting busted takes", after the wallet shot, so it never covers the HUD figure.
3. Cold-open wallet: HUD box crop of `12-50-26` 13 to 17.3, anchored at "the cash in your pocket" and ended by the next shot anchored at "Third", so "-$531" holds about 2 s; the WASTED shot now starts at 141.0 so the card shows in its shorter slot.
4. End: `beat_tail` 4.6 (see 14 above).
5. Tip 13: the badge box `00-18-47 p01` 73.9 to 75.95 is anchored at "small red badge" and holds until "I took them off"; then the HUD box 75.4 to 79.4 shows three icons to 76.6 and two from 76.8. Frames at 0.4 s steps: the BASEBALL CAP and the glasses were both ON with red badges to 74.8, the cap went OFF at 75.0 (the face icon stayed), the glasses went OFF at about 76.2 and the face icon went at 76.8, so "One was on Jason's glasses. I took them off, and the face icon vanished" holds.

Should-fixes: cold open starts at 119.3 with the same top-right zoom box; the Sheriff shot starts at 88.7 and is followed by a 2.5x box on the minimap (no police marker) anchored at "my minimap showed no police" (no ring graphic exists in analysis_gfx, so the zoom is the ring); the fighter-jet shot starts at 189.0; zoom boxes on the Heat cleared toast and on the tip 18 map (stars and card both in frame); the toll-plaza stars get a HUD box (240.8 to 242.0) before the wide shot; the subscribe lower third waits until 46 s (`brand` in gfx.json); the re-hook shows the items-wheel badges unblurred at "the free disguise"; the Dunk setup shot no longer shows her bending at the fence (now 240.8 to 244.8).

Found while fixing: the outro shots (`05-04-53 p03` 176 to 205 and `01-59-31 p01` 20 to 30) carry song lyrics on the car or ship radio (faster-whisper heard sung lines; v1's last seconds played them alone after the narration). Replaced by the airliner (`12-47-53`, no speech in the clip) and Lucia on the bridge (`01-00-16 p10` 24 to 38, traffic only); tip 19's barge shot replaced by the campsite (`01-40-40 p04` 256.5 to 260.5, quiet); the ask shot trimmed to end before a spoken line at 119.06.

