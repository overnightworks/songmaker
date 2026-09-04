# #533 – Backend für Album-Cover-Vorschläge

**Leser/Entscheidung:** Builder und Reviewer setzen C1 von #229 um, ohne einen
zweiten Cover- oder Provider-Owner zu schaffen. Vertrag: #533 und #229;
Zustände und Wortlaut: `docs/design/album-cover.html`; Codex-Nachweis:
`/tmp/claude-1000/-home-felix-hummert-git-songmaker/b3634502-0150-4c8a-93e5-9818e2d499a2/scratchpad/exp-229-out.md`.

## Schnitt

- `Album.cover_key` bleibt der einzige Verweis auf das ausgewählte Cover. Der
  vorhandene Cover-Writer bleibt auch für Upload, Varianten und die bestehende
  Share-Route Besitzer; kein `cover_path` und keine zweite öffentliche
  Cover-Route.
- Eine neue, persistente Vorschlags-Tabelle gehört zum Album und enthält eine
  nicht erratbare ID, `job_id`, den im Audio-Volume relativ gespeicherten
  PNG-Pfad und den Erzeugungszeitpunkt. `Job` erhält für Typ `cover` einen
  `album_id`-Bezug; sein Status, Fortschritt und Fehler bleiben die alleinige
  Zustandsquelle der laufenden Gruppe. Ein Job-Ergebnis-JSON ersetzt diese
  Tabelle nicht: drei Dateien müssen nach Reload auswählbar bleiben.
- Die Migration ergänzt diese Beziehungen und Indizes ohne Backfill. Sie
  löscht Vorschläge beim endgültigen Album-Löschen und entfernt ihre Dateien
  nur nach dem DB-Commit; „Discard all“ entfernt nur diese Vorschläge, nie das
  ausgewählte `cover_key`-Cover.

## Erzeugung und Dateien

- `cover` ist ein eigener Job-/ARQ-Funktionstyp im Musik-Worker, mit eigener
  Reaper-Schwelle in `STALE_JOB_THRESHOLDS`, Worker-Timeout-Reihenfolge und
  Heartbeat vor, während und nach jedem CLI-Aufruf. Fortschritt ist exakt
  `1/3`, `2/3`, `3/3`; `completed` bedeutet stets drei fertige Vorschläge.
- Der Job baut einen begrenzten, deterministischen Prompt aus Albumtitel,
  Künstler sowie den nach Tracknummer geordneten Stil-Prompts und Lyrics-
  Auszügen seiner Songs. Leere Albumfelder bleiben leer; weder Benutzer-,
  Konto-, Pfad-, Token- noch Fehlerdaten gelangen in den Prompt.
- Es gibt drei isolierte Codex-Bildaufrufe, je einen pro Vorschlag, damit ein
  Aufruf genau einen Fortschrittsschritt und eine Datei besitzt. Ein Fehler
  verwirft die unvollständige Gruppe und beendet den Job mit einem festen,
  UI-tauglichen Grund; kein Teil-Erfolg als wählbares „drei Vorschläge“.
- Der Bildadapter nutzt den gemeinsamen begrenzten Spawn-Owner, aber einen
  privaten Temporary-CWD, `--ephemeral`, JSON-Protokoll und ein geschlossenes
  Werkzeug-Gate: nur `image_gen`; jedes Kommando-, Netz-, MCP-, Datei- oder
  unbekannte Tool-Event bricht fehl. Er akzeptiert ausschließlich das erwartete
  PNG-Artefakt innerhalb dieses CWD, nie eine globale oder vom Modell genannte
  Pfadangabe, und übernimmt es erst nach dem Reap.
- Pillow ist vorhanden und normalisiert das Artefakt serverseitig zu einem
  quadratischen, metadatenfreien RGB/RGBA-PNG mit genau 1024×1024 Pixeln. Der
  Writer prüft Größe, Signatur, Dekodierbarkeit und einen auf das
  Vorschlagsverzeichnis eingeschlossenen Zielpfad; fehlende, mehrere,
  außerhalb liegende oder ungültige Artefakte sind ein benannter Jobfehler.
- Feste Musikertexte sind mindestens: **“Codex CLI is not logged in. Sign in
  on the operator host, then try again.”** und **“Image tool blocked. Ask an
  administrator to enable the image tool.”** Rohes stderr, Prompt und
  Providerdiagnosen werden nur intern klassifiziert und nie zurückgegeben.

## API, Rechte und Grenze

- `POST /api/albums/{id}/cover-suggestions` prüft `check_album_access`, zählt
  unter derselben serialisierten Transaktion die Cover-Jobs dieses Albums seit
  Tagesbeginn und legt höchstens den konfigurierten Wert (Standard 10) an.
  Es liefert den `JobResponse` und enqueued erst nach Commit.
- `GET …/cover-suggestions` liefert den letzten Cover-Job samt Zustand und
  seinen Vorschlägen; jede Vorschlags-URL wird über einen geschützten
  Datei-Endpunkt ausgeliefert. `DELETE …/cover-suggestions` implementiert das
  im Bild gezeigte „Discard all“.
- `PUT …/cover` wählt per Pydantic-Request eine Vorschlags-ID oder ersetzt
  multipart per Upload; beide Pfade schreiben über den bestehenden
  Album-Cover-Writer und geben `AlbumResponse.from_orm()` zurück. `DELETE
  …/cover` entfernt weiter nur das gewählte Cover. Alle privaten GET/PUT/
  DELETE-Routen prüfen Eigentümer oder Admin und verbergen fremde Alben mit
  404. Die bestehende öffentliche `GET /shared/{slug}/cover` bleibt der
  alleinige Share-Ausgang und liest nach Auswahl den gleichen `cover_key`.
- Das Tageslimit ist eine validierte Settings-Konfiguration (Standard 10),
  nicht ein per Nutzer verstellbares Stundenlimit. Der Zähler zählt
  Erzeugungsversuche, auch fehlgeschlagene, pro Album und Kalendertag.

## Provider-Grenze

Heute fragt der Cover-Job den Dispatch-Owner nach Codex’ aktuellem Weg und
verwendet dessen CLI-vs.-API-Diskriminator; er entscheidet weder über
Credentials noch über einen API-Fallback. #532 ersetzt nur diese Entscheidung
durch die Admin-Einstellung. Der Bildadapter erhält die bereits entschiedene
Methode und meldet fehlende Anmeldung bzw. gesperrtes Werkzeug fest zurück.

## Beweis

- Vertrag 1/4/6: API-Test legt einen Cover-Job an, beobachtet Fortschritt und
  drei 1024-PNG-Vorschläge; Tageslimit und parallele Anfragen lassen keinen
  elften Versuch zu.
- Vertrag 2/3: Auswahl und Upload setzen den vorhandenen `cover_key`, Entfernen
  stellt die Initiale wieder her, und die vorhandene Share-Route liefert genau
  das gewählte Bild; Discard löscht nur Vorschläge.
- Vertrag 5: Eigentümer/Admin sind erlaubt, ein Fremder erhält 404. Eine
  gefälschte CLI pinnt argv, `--ephemeral`, privaten CWD, den reinen
  `image_gen`-Gate und einen Prompt ohne Geheimnisse oder Benutzerkontext.
- Adapter-/Jobtests erzwingen die zwei festen Fehlertexte, Heartbeats,
  Reaper-Schwelle, Reap vor Übernahme sowie Ablehnung von Artefakt-, Format-,
  Größen- und Traversalfehlern. API-Modelle nutzen `from_orm`; die generierten
  Frontend-Typen werden geprüft.
- Live-Abnahme nach dem Bau: ein archiviertes Proof-Album erzeugt im laufenden
  Stack drei Dateien; Besitzer wählt eine, ersetzt sie und entfernt sie wieder.

## Baugrenze

Wenn der Bau nicht deutlich unter einer Stunde bleibt, vor dem ersten Edit in
zwei eigene Items schneiden: **C1a** Migration, Vorschlags-Querys,
Rechte/Endpunkte und Typen; **C1b** `cover`-Worker, Prompt, Codex-Bildadapter,
Dateiübernahme und deren Tests. C1b hängt an C1a; #533 schließt erst mit beiden
Slices und der Live-Abnahme.
