# Track 02: Fire in the Hole

**Album**: Download Days
**Genre**: Boom-Bap Hip-Hop (90s)
**BPM**: 90
**Key**: A minor
**Vocal Styles**: RAP (verses) · SINGING (chorus) · SPOKEN (intro) · SHOUT (final chorus) · WHISPER (outro)
**Status**: 🟢 APPROVED

---

## Sound Effects (SFX)

Game sound samples to layer into the mix at marked positions:

| SFX ID | Source | Description | Usage |
|--------|--------|-------------|-------|
| `sfx_monster_kill` | Unreal Tournament | "MMMM MONSTER KILL" announcer | Chorus endings, Final Chorus |
| `sfx_fire_hole` | Counter-Strike | "Fire in the Hole" radio voice | Intro, Verse 1, Chorus |
| `sfx_awp_shot` | Counter-Strike | AWP single shot crack | Verse 1 headshot, Verse 2 snipe |
| `sfx_awp_reload` | Counter-Strike | AWP bolt-action *clack-clack* | After AWP shots |
| `sfx_ak_spray` | Counter-Strike | AK-47 burst (3-4 rounds) | Verse 1 Tobbisch spray |
| `sfx_deagle` | Counter-Strike | Deagle single shot | Verse 1 Kill O Zap |
| `sfx_headshot` | Counter-Strike | Headshot *dink* sound | Scattered through verses |
| `sfx_round_start` | Counter-Strike | Round start beep | Intro |
| `sfx_bomb_plant` | Counter-Strike | Bomb plant beep sequence | Bridge transition |

**Source**: WAV samples in `albums/download_days/sfx/` folder.
Game sounds are from CS 1.6 and UT99 — widely sampled in hip-hop production.

---

## [INTRO] — Spoken, server connect

> *`sfx_round_start`*
> Power Terminators connected.
> Server: Dark Terrorists.
> Map: de_aztec. Alle da? Let's go.

---

## [VERSE 1] — Rap, present tense — LIVE in de_aztec

> Runde eins, CT Spawn, AWP schon in der Hand,
> Flexx0r scoped die Brücke, Fadenkreuz am Rand,
> Noob Saibot gibt die Ansage — "Links halten, rechts ist frei!",
> Kill O Zap zieht die Deagle — *`sfx_deagle`* — Headshot — eins, zwei, drei!
>
> Tobbisch rennt mit AK rein — *`sfx_fire_hole`* — "FIRE IN THE HOLE!"
> *`sfx_ak_spray`* — Spray Control, vier Kills, der Typ hat keine Kontrolle?
> Doch! Ace! Der ganze Raum schreit, Monitor wackelt,
> *`sfx_awp_shot`* *`sfx_awp_reload`* — "Was war das, Wichser?!" — nächste Runde, weiter geballert!

---

## [CHORUS] — Singing, hard hook

> Fire in the Hole! *`sfx_fire_hole`* Power Terminators kommen rein,
> Dark Terrorists Server, cs_militia, de_aztec — alles mein!
> Fire in the Hole! AWP, AK, Deagle am Start,
> Frag um Frag um Frag — Power Terminators, hart!
> *`sfx_monster_kill`* — MMMM… MONSTER KILL!

---

## [VERSE 2] — Rap, all-night session + cheaters + squad chaos

> Vier Uhr morgens, Bildschirm brennt, Augen komplett rot,
> Pizza aufm Boden, Schlaf ist tot, Red Bull auch schon tot,
> "Du Spasst, kauf Kevlar!" — "Halt's Maul, ich spar' auf AWP!",
> Nächste Runde Eco, trotzdem Clutch — hört die Welt noch?
>
> Clan War läuft, plötzlich — Wallhack! Scheiß Cheater!
> Der Typ sieht durch die Wand, Autoaim, was'n Biter!
> "Vote kick!" — "Der hat Aimbot, Alter, meld den Wichser!",
> Scheiß drauf, nächste Runde, wir sind trotzdem krasser!
>
> Noob Saibot ruft den Strat — "Alle B, jetzt pushen!",
> Kill O Zap, Deagle ready — *`sfx_deagle`* *`sfx_headshot`* — Headshot durch die Büsche,
> Tobbisch sprüht die AK leer — *`sfx_ak_spray`* — der Smoke verzieht sich,
> Flexx0r wartet hinten, Scope — *`sfx_awp_shot`* *`sfx_awp_reload`* — Zoom, Kopf, erledigt, sicher!

---

## [CHORUS] — Repeat

> Fire in the Hole! *`sfx_fire_hole`* Power Terminators kommen rein,
> Dark Terrorists Server, cs_militia, de_aztec — alles mein!
> Fire in the Hole! AWP, AK, Deagle am Start,
> Frag um Frag um Frag — Power Terminators, hart!
> *`sfx_monster_kill`* — MMMM… MONSTER KILL!

---

## [BRIDGE] — Singing, slower — servers gone

> *`sfx_bomb_plant`* *(fading, distant)*
> Die Server sind jetzt offline,
> kein Ping, kein Frag, kein Sound,
> Doch mach ich die Augen zu,
> hör' ich "Fire in the Hole" — *`sfx_fire_hole` (reverbed, distant)* — eine letzte Runde…

---

## [FINAL CHORUS] — Shout, full squad, maximum volume

> FIRE IN THE HOLE! *`sfx_fire_hole`* Power Terminators kommen rein!
> Dark Terrorists Server — Spassten, de_aztec ist mein!
> Noob Saibot! Kill O Zap! Tobbisch! Flexx0r!
> *`sfx_awp_shot`* *`sfx_deagle`* *`sfx_ak_spray`* *`sfx_headshot`*
> HEADSHOT! HEADSHOT! HEADSHOT! — GAME OVER!
> *`sfx_monster_kill`* — MMMM… MONSTER KILL!

---

## [OUTRO] — Whisper, silence

> *`sfx_round_start` (reversed, fading)*
> Server disconnected.
> GG WP.

---

## Notes

- **Language**: German, Denglisch, uncensored LAN trash-talk
- **Focus**: 100% Counter-Strike. No other games mentioned (UT MONSTER KILL is an SFX only).
- **Tone**: Present tense (in the match), aggressive, funny, raw
- **Trash-talk**: "Wichser", "Spasst", "Halt's Maul", "Scheiß Cheater" — real squad energy
- **SFX implementation**: WAV samples from CS 1.6 + UT99, layered as a separate audio track at marked beat positions. Bridge uses reverbed/distant versions for nostalgic feel.
- **Rhyme scheme**: AABB with internal rhymes for boom-bap flow
- **Cast weapons & roles**:
  - **Flexx0r** — narrator, AWP sniper, patient, waits in the back, scopes through smoke
  - **MC Tobbisch** — AK-47 specialist, spray control god, loudest in the room
  - **Noob Saibot** — strategist, calls the strats ("Alle B, jetzt pushen!")
  - **Kill O Zap** — Deagle one-tap king, headshot machine
- **Maps**: cs_militia, de_aztec
- **Cheater rage**: Wallhack, Autoaim/Aimbot, vote kick, "Scheiß Cheater!", "meld den Wichser!"
- **Server**: Dark Terrorists (actual clan war server)
- **CS terms**: CT Spawn, AWP, AK-47, Deagle, Kevlar, Eco round, Ace, Clutch, Scope, Smoke, Spray Control, "Fire in the Hole", Headshot, Wallhack, Aimbot, Vote Kick, pushed B, Bomb plant
