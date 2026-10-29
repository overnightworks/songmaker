# Design

Hier liegen die vom Operator gesegneten Bilder von Oberflächen — das, wogegen
gebaut wird. Ein Bild ist erst gesegnet, wenn es hier im Repository als
Besitzer eingefroren ist; ein Artefakt-Link allein reicht nicht.

**Warum:** Ein Bild, das nur als Artefakt-Link in einer Milestone-Beschreibung
lebt, verschwindet. Genau das ist am 30.08.2026 passiert: Der Link zeigte ins
Leere, und niemand hat es gemerkt, bis jemand danach gesucht hat.

**Regel:** Eine Änderung an einer Oberfläche (Raum, Seite, Karte, Ablauf)
fängt hier an — Bild lesen, Änderung einzeichnen, Freigabe des Operators
einholen, dann bauen. Wording- und Fehlerkorrekturen brauchen kein Bild.

## Inhalt

- `navigation.html` — die Navigation (#263, #564). Erste Fassung freigegeben
  am 30.08.2026, zweite Fassung freigegeben am 31.08.2026 — gegen die inzwischen
  gelandete Adressstruktur (#265) gehalten: jede Zeile der Leiste ist jetzt
  eine echte Adresse, das Aufklappen ist reine Darstellung. Neuzeichnung am
  04.09.2026 für #564: Die Leiste ist die eine Albumliste mit Cover, Filter,
  schaltbarem Detailgrad und ziehbarer Breite; die Reihe aus #545 ist als
  eigene Fläche abgelöst. Seit 20.09.2026 überschreibt `song-page-phone.html`
  Zustand (f) für die Songseite: keine Albumzeile mit Prev/Next mehr.
  Erweitert am 15.10.2026 für #1354 (#1373) um Zustand (i), freigegeben am
  15.10.2026 (Operator: „feels good! happy now!“, die 41 Regeln „yes all
  good“): Home zeigt Listen und Write, Library nur Alben und Playlists nur
  Playlists, auf dem Telefon drei Tabs unten statt des Drawers, ‹ auf jeder
  geöffneten Seite, die Player-Karte über den Tabs. Wo ältere Zustände etwas
  anderes zeigen, gilt (i). Zustand (j) für #1784 freigegeben am 22.10.2026
  (Operator: „2 sonst ok“, Desktop „ja a“): Account, Legal und Cleanup
  verlassen die Settings, das Konto ist am Desktop wie am Telefon ein Kreis
  mit Menü samt Rechtliches-Zeile; (j) überschreibt dort die Settings-Zeilen
  von (e) und (h), das Konto-Menü von (h) und (i) und die Konto-Zeile der
  Desktop-Leiste.
- `admin-models.html` — der Admin-Tab „Agents" (#317). Fassung 1 wurde am
  01.09.2026 freigegeben; Fassung 2 wurde am 06.09.2026 freigegeben: eine
  Aufgaben-Tabelle für Co-Writer, Cover und Scoring, mit Gründen direkt an
  Auswahl und Status. Die Scoring-CLI/API-Zeile (10.09.2026, #844) ist am
  28.10.2026 mit den Zuständen (b) und (x) entfernt worden (#1974): der
  automatische Judge hat die App verlassen, die Tabelle hat zwei Zeilen.
  Backend-Voraussetzungen: #316 (echter Provider-Status) und #315 (Judge
  providerneutral). Der Abschnitt „#1500 — VRAM und Kapazität" wurde am
  17.10.2026 freigegeben: die Worker-Karte mit VRAM-Zeile und der Liste der
  geladenen Modelle, auf der Songseite „Waiting for GPU…" und „Loading model…"
  mit Streifen und vergangener Zeit, der abgefangene Speicherfehler als „Too
  long for the GPU right now" und „nicht verfügbar" — ohne Vorab-Prüfung. Der Abschnitt „Cleanup“ (#1784)
  wurde am 22.10.2026 freigegeben.
- `album-browsing.html` — Album-/Playlist-Browsing nach dem Öffnen (#348).
  Erste Fassung freigegeben am 01.09.2026, nach dem Ausprobieren eines
  bedienbaren Prototyps: die Kachelwand bleibt bestehen und schrumpft beim
  Öffnen eines Albums zu einer kinetisch durchblätterbaren Reihe. Mini-Cover
  in der Leiste links hängen an #229; die Mobilbreite ist als offene Frage
  markiert, nicht gelöst. Seit 15.10.2026 (#1354) ist Zustand (g) die eine
  Sortierung — A–Z oder Last played — für Library, Playlists und die Liste
  links; „Added“ und die gemischte Wand sind weg, das Bild dazu steht in
  `navigation.html` (i). Wo ihre Rahmen einen Brotkrumenpfad, einen
  Shuffle-Knopf auf Album- oder Playlistseite oder eine Zeile „All albums“
  zeigen, gilt ebenfalls `navigation.html` (i).
- `song-page.html` — die Songseite „At the Take“ (#1804, #1815): Desktop 1440
  und Telefon 390. Freigegeben am 22.10.2026. Besitzer der Desktop-Songseite
  und der Recipe-Karte (geschlossen als eine Zeile „Recipe ›“, geöffnet mit
  den Tabs Song · Generate · Engine) sowie von Repaint und Cover als
  Aufgabenkarte am Take. Seit 23.10.2026 (#1825) auch der Takes pro Version
  gefaltet in der Listen-Spalte samt Bestätigung „Delete N“; „Takes per
  version“ überschreibt die flachen Take-Gruppen in `song-versions.html` und
  den Takes-Kopf in `song-page-phone.html`.
- `now-playing.html` — Now Playing öffnet auf dem, was zählt (#1816, #1826).
  Freigegeben am 23.10.2026 (Operator: „ok bilder passen“). Besitzer des Tabs,
  auf dem Now Playing öffnet (ein Take in der Schlange: This take, mehrere:
  Queue), des Namens „Use seed“ und von „Pick album takes“ / „Done“ im Walk;
  Telefon 390 und Desktop 1440.
- `song-editor-take.html` — eingefrorener früherer Stand (#230, freigegeben am
  03.09.2026): Repaint/Cover als Zeilenaktionen am Take. Überholt: die
  Take-Zeile gehört seit 20.09.2026 `song-page-phone.html` (sechs-zeiliges
  Menü), Repaint und Cover am Take seit 22.10.2026 `song-page.html`.
- `song-page-phone.html` — die Telefon-Songseite (#914). Freigegeben
  20.09.2026 (Operator: „looks good" / „fine" mit den Rulings in #914 und
  #924). Besitzer der Telefon-Songseite; überschreibt Zustand (f) in
  `navigation.html` für die Songseite (keine Albumzeile mit Prev/Next) und die
  Take-Zeile in `song-editor-take.html` auf beiden Breiten (sechs-zeiliges
  Menü, keine beschrifteten Zeilenaktionen).
- `song-versions.html` — Versionen auf der Songseite (#1245). Freigegeben
  02.10.2026 (Operator: „ja passen! die bilder!"). Erweitert
  `song-page-phone.html` auf beiden Breiten: eine Version antippen lädt sie als
  Entwurf in den Edit-Tab, kein Nur-Lesen-Zustand; die Take-Gruppen und Now
  Playing verlinken auf ihre Version.
- `vocabulary.html` — das Komponentenvokabular (#924). Freigegeben
  20.09.2026 (Operator: „looks good" / „fine" mit den Rulings in #914 und
  #924). Besitzer jeder Komponentenform; jede UI-Lane zitiert sie, Farbwerte
  sind Tokens: die Familie in appkit, Farbe und Domäne der App in `app.css`, Bedeutungen sind geregelt.
- `share-player.html` — die geteilten Seiten (#1374): geteilter Song, Take,
  Album und Playlist. Freigegeben am 15.10.2026 (Operator: „bei shuffle deine
  empfehlung! und dann go!“), eingefroren am 16.10.2026 (#1432). Besitzer
  dieser vier Seiten, am Telefon und am Desktop: jede geteilte Seite ist der
  Player (Cover, Titel, ▶, Slider, Lyrics, bei Album und Playlist die Songs),
  Play in Violett (#924). Überschreibt den Share-Seiten-Rahmen (f) in
  `album-cover.html`. Die 16 gerulten Zeilen von #1374 stehen in der Datei; die
  Vorher-Screenshots sind nicht übernommen (sie bleiben im Artefakt). Offen:
  die Sammlungs-h1, entschieden in Slice 6 gegen dieses Bild.
- Der Agent-Service (#1895, #1476 „The pictures must show"). Freigegeben am
  26.10.2026 (Operator: „das Bild ist gut", „alles deine Empfehlung"), mit
  Q4 b und Q5 a; der Operator hat Q4 b am 27.10.2026 überholt (agent-runtime#494,
  #1949): Die Gesprächszeile der Co-Writer-Spalte lautet „Co-writer ·
  conversation since Tue", ohne Modell;
  endet ein Zug, weil Keycloak nicht mehr erneuert, steht dort „Sign in again
  to use the co-writer" mit Sign-in-Link, und der Rest von songmaker arbeitet
  weiter (Q5 b, die ganze App meldet ab, ist verworfen); Q13 gilt mit ihrem
  Default a. Besitzer: `admin-models.html` (Abschnitt „Neu · #1895",
  Zustände w bis y′: fünf Spalten, Co-Writer-Zeile „Set by the agent service"
  ohne Status, Cover und Scoring „not available yet"), `song-page.html` (D5b, D7a–d) und
  `song-page-phone.html` (7c–7e; die Gesprächszeile in Frame 7 ist ersetzt),
  `album-cover.html` („Suggest closed", Punkt 8; `album-browsing.html` zeigt
  C2–C9 als den Zustand, der mit Bildläufen zurückkommt, und I1 liest
  „upload") und `now-playing.html` („Coherence not available").
- KI-Kennzeichnung nach Art. 50 der KI-Verordnung (#1906), gesegnet vom
  Operator am 27.10.2026 (P1 bis P5). Wortlaut gerult (E3, Operator 19.10.2026):
  „KI-generiert“ am Song oder Album und „Du schreibst mit einer KI“ im
  Co-Writer, immer sichtbar, ohne Schalter. Das Abzeichen steht in der Zeile,
  die nennt, was läuft (hinter „v4 · take 7“ oder dem Namen), und bricht bei 390
  in eine eigene zentrierte Zeile um, wenn diese Zeile lang ist; die Co-Writer-Zeile
  steht in einer eigenen Zeile unter der Kopfzeile. Der Vorlesetext ist reiner
  Text mit `lang="de"`, das Symbol ist verborgen. Die deutschen Worte bleiben in
  der englischen App. Dateien: `share-player.html` (Abschnitt 8),
  `now-playing.html` (Abschnitt 5), `song-page.html` (Abschnitt „You write with
  an AI“) und `song-page-phone.html` (7f).
- `sign-in.html` — Anmelden und Abgewiesen-Werden (#1715). Quelle:
  overnightworks/ui-console#6, Fassung 2, freigegeben vom Operator am
  19.10.2026, Artefakt https://claude.ai/artifact/6xvoJezFbApz7ygKfCe9we. Die
  Tafeln sind in presentators Aussehen gezeichnet; songmaker übernimmt Aufbau
  und Wortlaut in den eigenen Farben (Operator: „Gleicher Aufbau, App-Farben“).
  K12 (#1620) baut gegen diese Abschnitte: Weiterleitung, abgemeldet, kein
  Zugang, Anmeldung fehlgeschlagen, Personenmenü; die
  presentator-spezifischen Tafeln gelten nicht. Standard-Zuordnung der
  Abweisungen: `ACCOUNT_DEACTIVATED` → „No access“; `FOREIGN_ISSUER` und
  `USERNAME_TAKEN` → „Login failed“. Das Verhalten gehört dem webauth-README,
  Abschnitt „Signed out and refused“.
- `about.html` — die About-Seite (Settings › About): welcher Release und
  welcher Commit laufen (#2008). Freigegeben am 29.10.2026 (Operator: „ja bild
  passt“).
- `references.html` — Referenzaufnahmen: ansehen, abspielen, behalten (♥),
  löschen und die angekündigte automatische Löschung unbenutzter (⏳), verwaltet
  unter Settings › References und gewählt in der Zeile „Reference track“ des
  Recipes (#1988). Freigegeben am 29.10.2026 (Operator: „passt für mich! alles
  wie empfohlen!“); die neun offenen Entscheidungen sind wie empfohlen gerult
  und auf #1988 festgehalten.
