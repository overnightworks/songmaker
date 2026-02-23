"""Generate the Apologiez lyrics booklet as HTML.

Creates a styled HTML file that can be opened in a browser and printed to PDF.
Street art / graffiti aesthetic matching the album cover.

Run: .venv/Scripts/python scripts/create_apologiez_booklet.py
"""

from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("_output/apologiez/final")
OUTPUT_FILE = OUTPUT_DIR / "lyrics_booklet.html"

TRACKS = [
    {
        "number": "01",
        "title": "Happy Birthday Tobbisch",
        "subtitle": "Feel-good pop/dance • 116 BPM • G major",
        "lyrics": """\
[intro]
Tobbisch!
This one's for you, Bruder

[verse]
Du warst bei Spotify, Sony Music, the real deal,
Und ich sitz hier mit nem GPU und frag die KI how she feels,
Du warst DJ in den Clubs, ich war zu Hause am coden,
Aber irgendwie sind wir connected seit dem Pausenhof-Boden

Du bist der Stefan Raab unter unseren Leuten,
Kannst singen, kannst labern, kannst die ganze Crowd begeistern,
Und ich? Ich bau Maschinen die versuchen das zu tun,
Was du schon konntest mit dreizehn, Alter, gönn dir Ruh!

[chorus]
Happy Birthday Tobbisch, raise your glass tonight!
Du bist der Grund warum ich Songs schreib auch wenn keiner klingt ganz right,
Happy Birthday Tobbisch, dieses Mal klingts gut,
Weil die KI jetzt endlich singt als hätt sie echten Mut!

[verse]
Wir sehen uns nicht oft, aber Bruder das ist egal,
Manche Freundschaften brauchen keinen Terminkalender, keine Wahl,
Du rufst an, ich ruf an, manchmal Jahre dazwischen,
Aber wenn wir reden fühlt sichs an wie gestern auf den Tischen

In der Schule warst du schon der Typ der alle zum Lachen bringt,
Der eine der aufsteht und einfach irgendwas Verrücktes singt,
Du hast das beruflich gemacht, Sony, Spotify, die ganze Welt,
Und ich schick dir AI-Songs, sorry dass der letzte hat gefehlt!

[chorus]
Happy Birthday Tobbisch, raise your glass tonight!
Du bist der Grund warum ich Songs schreib auch wenn keiner klingt ganz right,
Happy Birthday Tobbisch, dieses Mal klingts gut,
Weil die KI jetzt endlich singt als hätt sie echten Mut!

[bridge]
Okay, real talk Tobi,
Das letzte Album war Müll, ich weiß,
Die Stimmen klangen wie ein Roboter der weint,
Aber ich hab weitergemacht, für dich,
Weil du der Einzige bist ders verdient,
Dass jemand um vier Uhr morgens,
Einer KI beibringt zu singen,
Happy Birthday, du Legende!

[chorus]
Happy Birthday Tobbisch, raise your glass tonight!
Flex0r und die Maschinen singen nur für dich heut Nacht,
Happy Birthday Tobbisch, Freunde seit Tag eins,
Egal wie weit, du weißt, ich meins!

[outro]
Happy Birthday, Bruder
Happy Birthday, Tobbisch
GG WP""",
    },
    {
        "number": "02",
        "title": "Sorry (Not Sorry)",
        "subtitle": "R&B slow jam • 85 BPM • E minor",
        "lyrics": """\
[intro]
Tobi... ich muss dir was sagen...

[verse]
I pressed send on your birthday,
Forty-one candles, and a ZIP file full of pain,
Du hast auf Play gedrückt in Berlin,
Und ich saß in Erlangen und hab gewartet auf ein Zeichen

But all I got was silence, Bruder,
Kein Wort, kein Emoji, nichts,
Du warst zu nett um mir zu sagen,
Dass der Monty Python Song ein Verbrechen ist

[chorus]
I'm sorry, not sorry, that I tried,
Sorry for the robot voice that cried,
Sorry for the Tarkan song at night,
But I'm not sorry that I tried to get it right

I'm sorry, Tobbisch, yeah I know,
Du bist der Musikmann, ich hab dir Müll geschickt als Show,
But thirty years of friendship, Erlangen to Berlin,
Deserve a better song than what that AI has been

[verse]
Du bist der Typ der auf der Bühne steht und alle rockt,
Stefan Raab in cool, der Crowd den Atem stockt,
Und ich? Ich schick dir WAV files um vier Uhr morgens,
Wo ne Maschine singt als hätt sie Zahnschmerzen

Du hast in der Musikbranche Karriere gemacht, kein Scherz,
Von Spotify zu Sony, immer mittendrin im Herz,
Und dein Schulfreund aus Erlangen denkt er kann dir Musik machen,
Alter, ich versteh wenn du nicht wusstest ob du weinen oder lachen

[chorus]
I'm sorry, not sorry, that I tried,
Sorry for the robot voice that cried,
Sorry for the Tarkan song at night,
But I'm not sorry that I tried to get it right

I'm sorry, Tobbisch, yeah I know,
Du bist der Musikmann, ich hab dir Müll geschickt als Show,
But thirty years of friendship, Erlangen to Berlin,
Deserve a better song than what that AI has been

[bridge]
Dreißig Jahre, Bruder,
Von der Schulbank bis hierher,
Du in Berlin, ich immer noch in Erlangen,
Aber manche Dinge ändern sich nie,
Ich werde immer versuchen dir Songs zu schicken,
Und sie werden immer besser,
Das hier ist der Beweis

[chorus]
I'm sorry, not sorry, that I tried,
Sorry that the old one made you cry,
But this time hear the difference in the sound,
This time, Tobbisch, I won't let you down

[outro]
Happy forty-one, Bruder...
This one's better, right?
...right?""",
    },
    {
        "number": "03",
        "title": "Rap Battle Part 2",
        "subtitle": "Hip-hop battle rap • 95 BPM • D minor",
        "lyrics": """\
[intro]
Ladies and Gentlemen!
Rap Battle Part Two!
Flex0r versus MC Tobbisch!
Last time was trash, this time we mean it!

[Flex0r]
Yo Tobbisch, Part eins war peinlich, ich gebs zu,
Die KI hat gerappt wie ne Waschmaschine im Schuh,
Aber jetzt bin ich upgraded, neues Modell, neuer Sound,
Und du bist immer noch der Typ der in der Schule rumgeclownt!

Du hast mich von der Seite gepiekst im Unterricht,
Ich dreh mich um und hau dich, Frau Loschert sieht nur mich!
Sie hat mich ermahnt und du sitzt da und lachst,
Immer ich der Dumme, weil du den Scheiß angefangen hast!

[MC Tobbisch]
Flex0r, mein Fanboy, du standest nur rum und hast applaudiert,
Im E-Werk Back to School, ich hab aufgelegt, du hast Bier kassiert,
Ich stand am Pult, du standst daneben mit nem Bier,
Und jetzt machst du AI Musik? Bruder, lass das lieber mir!

Du warst der Sportler und der Gamer, ich der Künstler hier,
Jedes Jahr am Berg die gleiche Jeansjacke, Alter, seriously?
Ich hör ein Lied einmal und sing es, du hast keinen Plan,
Und jetzt schickst du mir AI Songs von nem Typ der nicht mal singen kann!

[Flex0r]
Okay okay, du bist der Musiktyp, ich der Zocker am PC,
Mein Bruder hatte Internet, wir haben Napster durchgezogen, du und ich,
Tausend Songs gesaugt, die ganze Nacht am Stück,
Und jetzt willst du sagen ICH versteh nichts von Musik?

Du hast aufgelegt, ich stand daneben, Backup-Mann,
Du hast die Crowd gerockt, ich war der Typ der nichts besser kann,
Aber ich war da, jede Nacht, E-Werk bis zum Schluss,
Dein treuester Fan im Backstage, und das reicht als Plus!

[MC Tobbisch]
Flex0r, du sitzt in Erlangen, kommst nicht raus aus der Stadt,
Alle reisen um die Welt und du sitzt da wo du immer schon saßt,
Erst Poker, dann Gaming, fast gut aber nie genug,
Und jetzt AI Musik, Bruder, wann lernst du, wann ist Schluss?

Ich hab Tessa, Charlotte, Berlin, mein Leben ist komplett,
Und du hast Kaffee und Bier um vier Uhr im Bett,
Aber egal wie schlecht die Songs sind, egal wie schief der Ton,
Du bist mein Bruder seit der Schulbank, das reicht als Grund, Champion!

[Flex0r]
Du sagst ich sitz in Erlangen, ja stimmt, ich geb's zu,
Aber wenigstens kenn ich hier jeden, und jeder kennt mich, Bruh,
Du bist nach Berlin gezogen, großer Mann in der Stadt,
Aber rufst mich trotzdem an wenn du Heimweh hast!

Und ja, meine Songs sind KI, meine Stimme ist fake,
Aber wenigstens versuch ich was, ich mach was, ich schaff,
Du singst im Wohnzimmer Karaoke für Tessa allein,
Und ich stream meine Kunst in die Welt, Alter, das ist fein!

[MC Tobbisch]
Streamen, Alter, bitte, wer hört sich den Scheiß an?
Deine Mutter und ich, und deine Mutter nur aus Mitleid, Mann,
Du hast dreißig Jahre gebraucht für dein erstes Album hier,
Und es klingt wie AutoTune auf nem kaputten Klavier!

Aber weißt du was, Flex0r, ich sag dir jetzt was Echtes,
Kein Diss, kein Joke, jetzt mal was Gerechtes,
Von all den Leuten die ich kenn, Berlin bis Erlangen,
Bist du der Einzige der nie aufhört anzufangen!

[outro]
Unentschieden!
Wie immer!
Flex0r und MC Tobbisch!
Part drei kommt wenn die KI Gefühle hat!""",
    },
    {
        "number": "04",
        "title": "Die KI singt für dich",
        "subtitle": "Pop-punk anthem • 140 BPM • A major",
        "lyrics": """\
[intro]
Eins, zwei, drei, vier!

[verse]
Ich kann nicht singen, das ist Fakt,
Meine Stimme klingt wie'n Staubsauger der rappt,
Ich kann kein Klavier, keine Gitarre, keinen Bass,
Aber ich kann coden, Bruder, und das reicht für Spaß!

Vier Uhr morgens, Bildschirm leuchtet blau,
Prompt rein, Beat raus, ich weiß genau,
Mein Nachbar klopft und fragt ob alles klar,
Ich sag ja, Alter, ich mach grad ein Album, ist doch wunderbar!

[chorus]
Die KI singt für dich,
Weil ich es selber nicht kann,
Die KI singt für dich,
Und sie gibt alles was sie hat, Mann!
Ich hab keine Stimme, ich hab keinen Plan,
Aber ich hab ne Maschine die für mich singen kann,
Die KI singt für dich,
Und ich mein jedes Wort!

[verse]
Version eins war Bark, oh Gott, was für ein Graus,
Die Stimme klang als würd ein Roboter kotzen im Haus,
Ich hab dir trotzdem zehn Songs geschickt, zum Geburtstag, wie nett,
Und du hast geschwiegen, Bruder, und ich lag wach im Bett!

Dann kam ACE-Step, neues Modell, neuer Sound,
Plötzlich klingt es fast nach Musik, ich dreh mich im Kreis, ich bin Hound,
Zehn Stunden rendern für drei Minuten Song,
Meine GPU glüht, aber Tobi, es hat sich gelohnt!

[chorus]
Die KI singt für dich,
Weil ich es selber nicht kann,
Die KI singt für dich,
Und sie gibt alles was sie hat, Mann!
Ich hab keine Stimme, ich hab keinen Plan,
Aber ich hab ne Maschine die für mich singen kann,
Die KI singt für dich,
Und ich mein jedes Wort!

[bridge]
Und ja, du bist der Musikmann,
Du hörst sofort wenn irgendwas nicht stimmen kann,
Und ja, das hier ist künstlich, fake, aus Nullen und aus Einsen,
Aber die Gefühle dahinter, Bruder, die sind meins!

[chorus]
Die KI singt für dich,
Weil ich es selber nicht kann,
Die KI singt für dich,
Und sie wird besser, Song für Song, das ist der Plan!
Ich hab keine Stimme, aber ich hab nen Freund,
Der das hier hört und vielleicht, vielleicht, ein bisschen weint,
Die KI singt für dich,
Tobi, das hier ist für dich!

[outro]
Die KI singt für dich...
Und nächstes Jahr wird sie noch besser, versprochen!""",
    },
    {
        "number": "05",
        "title": "Bruder",
        "subtitle": "Acoustic ballad • 78 BPM • C major",
        "lyrics": """\
[verse]
Ich bin nicht gut in sowas,
Du weißt das, ich weiß das,
Ich sag lieber nichts als was Falsches,
Und dann sag ich gar nichts

Wir sehen uns einmal im Jahr wenn's gut läuft,
Weihnachten oder dein Geburtstag,
Und dazwischen ist Stille,
Aber keine die wehtut, eine die reicht

[chorus]
Du bist mein Bruder,
Nicht weil wir mussten, weil wir's sind,
Du bist mein Bruder,
Seit dem Pausenhof, seit wir Kinder sind,
Und ich hab dir das nie gesagt,
Weil Männer sowas halt nicht sagen,
Aber heute Nacht sagt's ne Maschine für mich,
Und ich mein jedes Wort, das sie singt

[verse]
Bei dir muss ich nicht so tun als wär ich irgendwer,
Kein Smalltalk, keine Rolle, einfach da,
Einfach Felix, der Typ aus Erlangen,
Der mit dir auf dem Boden saß und Bier getrunken hat

Du in Berlin mit Tessa und der Kleinen,
Und ich hier, immer noch am selben Fleck,
Aber wenn du anrufst ist es wie früh um neun im Schulhof,
Als hätt sich nichts verändert, als wär keiner je weg

[chorus]
Du bist mein Bruder,
Nicht weil wir mussten, weil wir's sind,
Du bist mein Bruder,
Seit dem Pausenhof, seit wir Kinder sind,
Und ich hab dir das nie gesagt,
Weil Männer sowas halt nicht sagen,
Aber heute Nacht sagt's ne Maschine für mich,
Und ich mein jedes Wort, das sie singt

[bridge]
Dreißig Jahre, Tobi,
Vom Klassenzimmer bis hierher,
Vom E-Werk bis Berlin,
Von Napster bis Spotify,
Wir sind älter geworden,
Aber das hier ist gleich geblieben,
Und das ist mehr als die meisten Menschen jemals haben

[chorus]
Du bist mein Bruder,
Das ist alles was ich sagen will,
Du bist mein Bruder,
Und das reicht, das reicht, das reicht,
Und wenn die Maschine aufhört zu singen,
Dann bleibt das hier,
Bleibt das hier

[outro]
Ich hab dich lieb, Bruder,
Das war's, mehr brauch ich nicht zu sagen""",
    },
    {
        "number": "BONUS",
        "title": "Fire in the Hole",
        "subtitle": "Boom-bap hip-hop • 90 BPM • A minor",
        "lyrics": """\
[intro]
Power Terminators connected,
Server Dark Terrorists,
Map de_aztec, alle da, let's go!

[verse]
Runde eins, CT Spawn, AWP schon in der Hand,
Flexx0r scoped die Brücke, Fadenkreuz am Rand,
Noob Saibot gibt die Ansage, links halten, rechts ist frei,
Kill O Zap zieht die Deagle, Headshot, eins, zwei, drei!

Tobbisch rennt mit AK rein, FIRE IN THE HOLE!
Spray Control, vier Kills, der Typ hat keine Kontrolle?
Doch! Ace! Der ganze Raum schreit, Monitor wackelt,
Was war das, Wichser?! Nächste Runde, weiter geballert!

[chorus]
Fire in the Hole! Power Terminators kommen rein,
Dark Terrorists Server, cs_militia, de_aztec, alles mein!
Fire in the Hole! AWP, AK, Deagle am Start,
Frag um Frag um Frag, Power Terminators, hart!
MONSTER KILL!

[verse]
Vier Uhr morgens, Bildschirm brennt, Augen komplett rot,
Pizza aufm Boden, Schlaf ist tot, Red Bull auch schon tot,
Du Spaßt, kauf Kevlar! Halts Maul, ich spar auf AWP!
Nächste Runde Eco, trotzdem Clutch, hört die Welt noch?

Clan War läuft, plötzlich, Wallhack! Scheiß Cheater!
Der Typ sieht durch die Wand, Autoaim, was ein Biter!
Vote kick! Der hat Aimbot, Alter, meld den Wichser!
Scheiß drauf, nächste Runde, wir sind trotzdem krasser!

Noob Saibot ruft den Strat, Alle B, jetzt pushen!
Kill O Zap, Deagle ready, Headshot durch die Büsche,
Tobbisch sprüht die AK leer, der Smoke verzieht sich,
Flexx0r wartet hinten, Scope, Zoom, Kopf, erledigt, sicher!

[chorus]
Fire in the Hole! Power Terminators kommen rein,
Dark Terrorists Server, cs_militia, de_aztec, alles mein!
Fire in the Hole! AWP, AK, Deagle am Start,
Frag um Frag um Frag, Power Terminators, hart!
MONSTER KILL!

[bridge]
Die Server sind jetzt offline,
Kein Ping, kein Frag, kein Sound,
Doch mach ich die Augen zu,
Hör ich Fire in the Hole, eine letzte Runde

[chorus]
FIRE IN THE HOLE! Power Terminators kommen rein!
Dark Terrorists Server, Spaßten, de_aztec ist mein!
Noob Saibot! Kill O Zap! Tobbisch! Flexx0r!
HEADSHOT! HEADSHOT! HEADSHOT! GAME OVER!
MONSTER KILL!

[outro]
Server disconnected,
GG WP""",
    },
]

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APOLOGIEZ — Lyrics Booklet</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;700&family=Open+Sans:wght@400;600&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: #1a1a1a;
    color: #e0e0e0;
    font-family: 'Open Sans', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
  }}

  .cover-page {{
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: linear-gradient(180deg, #0d0d0d 0%, #1a1a1a 50%, #0d0d0d 100%);
    padding: 60px 40px;
    page-break-after: always;
  }}

  .cover-title {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 96px;
    font-weight: 700;
    color: #ff3220;
    text-transform: uppercase;
    letter-spacing: 8px;
    text-shadow: 4px 4px 0 #000, 6px 6px 0 rgba(255,50,30,0.3);
    margin-bottom: 20px;
  }}

  .cover-subtitle {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    color: #ffdc00;
    letter-spacing: 4px;
    margin-bottom: 30px;
  }}

  .cover-tagline {{
    font-style: italic;
    color: #888;
    font-size: 20px;
    margin-bottom: 60px;
  }}

  .cover-tracklist {{
    text-align: left;
    color: #999;
    font-size: 16px;
    line-height: 2.2;
  }}

  .cover-tracklist span.track-num {{
    color: #ff3220;
    font-family: 'Oswald', Impact, sans-serif;
    font-weight: 700;
    margin-right: 12px;
  }}

  .cover-footer {{
    margin-top: 60px;
    color: #555;
    font-size: 13px;
  }}

  .track-page {{
    max-width: 800px;
    margin: 0 auto;
    padding: 60px 40px;
    page-break-after: always;
  }}

  .track-header {{
    border-bottom: 3px solid #ff3220;
    padding-bottom: 20px;
    margin-bottom: 30px;
  }}

  .track-number {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 48px;
    font-weight: 700;
    color: #ff3220;
    line-height: 1;
  }}

  .track-title {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    font-weight: 700;
    color: #fff;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-top: 5px;
  }}

  .track-subtitle {{
    color: #888;
    font-size: 14px;
    margin-top: 8px;
    font-style: italic;
  }}

  .lyrics {{
    white-space: pre-wrap;
    font-size: 16px;
    line-height: 1.8;
  }}

  .lyrics .section-tag {{
    display: inline-block;
    color: #ffdc00;
    font-family: 'Oswald', Impact, sans-serif;
    font-weight: 700;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-top: 25px;
    margin-bottom: 8px;
    background: rgba(255,220,0,0.1);
    padding: 2px 10px;
    border-left: 3px solid #ffdc00;
  }}

  .credits-page {{
    max-width: 800px;
    margin: 0 auto;
    padding: 60px 40px;
    text-align: center;
  }}

  .credits-page h2 {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    color: #ff3220;
    margin-bottom: 40px;
  }}

  .credits-page p {{
    color: #aaa;
    font-size: 16px;
    line-height: 2;
    margin-bottom: 10px;
  }}

  .credits-page .dedication {{
    margin-top: 60px;
    padding: 30px;
    border: 1px solid #333;
    background: rgba(255,220,0,0.03);
    font-style: italic;
    color: #ccc;
    font-size: 18px;
    line-height: 1.8;
  }}

  .credits-page .gg {{
    margin-top: 40px;
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 24px;
    color: #ffdc00;
  }}

  @media print {{
    body {{ background: #fff; color: #222; }}
    .cover-page {{ background: #fff; }}
    .cover-title {{ color: #cc0000; text-shadow: none; }}
    .cover-subtitle {{ color: #cc8800; }}
    .track-page {{ padding: 40px 20px; }}
    .lyrics {{ font-size: 14px; }}
    .lyrics .section-tag {{ background: #f5f5f5; color: #cc8800; }}
  }}
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover-page">
  <div class="cover-title">APOLOGIEZ</div>
  <div class="cover-subtitle">FLEX0R &rarr; MC TOBBISCH</div>
  <div class="cover-tagline">"sorry for the robot voice"</div>
  <div class="cover-tracklist">
{tracklist_html}
  </div>
  <div class="cover-footer">
    AI Generated &bull; 2026 &bull; Erlangen &rarr; Berlin
  </div>
</div>

<!-- TRACK PAGES -->
{tracks_html}

<!-- CREDITS PAGE -->
<div class="credits-page">
  <h2>CREDITS</h2>
  <p><strong>Written by</strong>: Flex0r &amp; Claude Code</p>
  <p><strong>Produced by</strong>: ACE-Step 1.5</p>
  <p><strong>Mastered by</strong>: Songmaker Engine</p>
  <p><strong>Cover Art</strong>: Pillow + Python + Spray Paint Dreams</p>
  <p><strong>For</strong>: MC Tobbisch (Tobias)</p>
  <p><strong>From</strong>: Flex0r (Felix), Erlangen</p>

  <div class="dedication">
    Tobi,<br><br>
    Dreißig Jahre Freundschaft.<br>
    Vom Pausenhof über das E-Werk bis Berlin.<br>
    Das letzte Album war Müll, ich weiß.<br>
    Dieses hier ist besser. Versprochen.<br><br>
    Und nächstes Jahr wird es noch besser.<br><br>
    Dein Bruder,<br>
    Felix
  </div>

  <div class="gg">GG WP</div>
</div>

</body>
</html>
"""


def format_lyrics(raw: str) -> str:
    """Convert raw lyrics to HTML with styled section tags."""
    lines = raw.split("\n")
    html_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            tag = stripped[1:-1]
            html_lines.append(f'<div class="section-tag">{tag}</div>')
        elif stripped == "":
            html_lines.append("")
        else:
            html_lines.append(stripped)
    return "\n".join(html_lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build tracklist HTML
    tracklist_lines = []
    for t in TRACKS:
        tracklist_lines.append(
            f'    <div><span class="track-num">{t["number"]}</span>{t["title"]}</div>'
        )
    tracklist_html = "\n".join(tracklist_lines)

    # Build track pages HTML
    track_pages = []
    for t in TRACKS:
        lyrics_html = format_lyrics(t["lyrics"])
        track_pages.append(f"""\
<div class="track-page">
  <div class="track-header">
    <div class="track-number">{t["number"]}</div>
    <div class="track-title">{t["title"]}</div>
    <div class="track-subtitle">{t["subtitle"]}</div>
  </div>
  <div class="lyrics">
{lyrics_html}
  </div>
</div>
""")
    tracks_html = "\n".join(track_pages)

    html = HTML_TEMPLATE.format(
        tracklist_html=tracklist_html,
        tracks_html=tracks_html,
    )

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Lyrics booklet saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
