# #533 – Backend für Album-Cover-Vorschläge

**Leser/Entscheidung:** Builder und Reviewer setzen C1 von #229 als zwei
vorab geschnittene Slices um, ohne einen zweiten Cover- oder Provider-Owner zu
schaffen. Vertrag: #533 und #229; Zustände und Wortlaut:
docs/design/album-cover.html; CLI-Nachweis:
 /tmp/claude-1000/-home-felix-hummert-git-songmaker/b3634502-0150-4c8a-93e5-9818e2d499a2/scratchpad/exp-229-out.md.

Jede Referenz auf bestehenden Code ist ein **Code-Beleg** für die Entscheidung;
sie ist kein Auftrag, die dortige Verantwortung zu kopieren.

## Vertrag und persistenter Schnitt

- Album.cover_key bleibt der einzige Verweis auf das ausgewählte Cover. Der
  vorhandene Cover-Writer bleibt für Upload, Varianten und die bestehende
  Share-Route Besitzer; es gibt weder cover_path noch eine zweite öffentliche
  Cover-Route. **Code-Beleg:** Der Upload schreibt mit write_album_cover und
  setzt danach nur cover_key (src/songmaker_cli/album_api.py:343-361); die
  Share-Route liest denselben Schlüssel
  (src/songmaker_cli/sharing_api.py:268-288).
- Eine neue AlbumCoverSuggestion-Tabelle gehört zum Album und enthält eine
  nicht erratbare ID, job_id, den **relativ zum Audio-Volume** gespeicherten
  PNG-Pfad und created_at; Job erhält für JobType.COVER ein indiziertes
  album_id-FK mit ondelete=CASCADE. Jeder Pfad liegt ausschließlich als
  `cover-suggestions/{album_id}/{suggestion_id}.png` unter dem Audio-Volume:
  dieser Geschwisterbaum von `covers/` wird durch einen eigenen
  Suggestion-Cleanup-Owner entfernt. Damit kann DELETE `/cover` mit seinem
  bestehenden `covers/{album_id}`-Cleanup keine Vorschläge berühren. Der neue
  Owner löst jeden gespeicherten Pfad über `canonical_audio_path` auf und
  entfernt nur in diesem Baum eingeschlossene Dateien bzw. Album-Verzeichnisse.
  Die Tabelle ist das dauerhafte Ergebnis einer Gruppe, nicht ein
  Ergebnis-JSON: drei Dateien müssen nach Reload wählbar bleiben. Die Migration
  fügt Beziehungen und Indizes ohne Backfill hinzu; beim endgültigen
  Album-Löschen löschen DB-Cascade und ein Commit-nachgelagerter
  Suggestion-Datei-Cleanup die Vorschlagsdateien — sowohl beim Retention-Reaper
  als auch beim Hard-Delete eines Nutzers. **Code-Beleg:** Job hat bisher nur
  user_id und song_id (src/songmaker_cli/db/models.py:321-340), und create_job
  kann folglich bislang kein Album verknüpfen
  (src/songmaker_cli/db/queries/jobs.py:28-34). Der bestehende
  `remove_album_cover_files`-Owner löscht dagegen vollständig
  `covers/{album_id}` (src/songmaker_cli/covers.py:226-228, 437-452); die zwei
  Hard-Delete-Pfade rufen ihn nach Commit auf
  (src/songmaker_cli/cleanup.py:80-85,
  src/songmaker_cli/admin_api.py:226-233), und `canonical_audio_path` ist der
  vorhandene Volume-Containment-Owner (src/songmaker_cli/audio_paths.py:67-76).
- „Discard all“ löscht ausschließlich die Vorschlagszeilen und ihre Dateien
  erst nach Commit; es fasst nie das durch cover_key ausgewählte Bild an.
  DELETE /cover bleibt ausschließlich das Entfernen des gewählten Covers.
  **Code-Beleg:** Der bestehende Delete setzt nur cover_key=None und räumt
  danach die Cover-Dateien auf (src/songmaker_cli/album_api.py:364-377).

## Vertrag, API und Rechte

- POST /api/albums/{album_id}/cover bleibt der unveränderte Multipart-Upload.
  Neu ist PUT /api/albums/{album_id}/cover **nur** mit Pydantic-JSON
  { "suggestion_id": "…" }: Es löst genau die geschützte Vorschlags-ID auf,
  liest deren validiertes PNG und schreibt über write_album_cover; beide Pfade
  antworten mit AlbumResponse.from_orm() über den vorhandenen
  _single_album_response. Dies korrigiert die erste Fassung des Plans, die
  irrtümlich Upload auf PUT verschoben hätte. **Code-Beleg:** Upload ist heute
  explizit POST (src/songmaker_cli/album_api.py:343-361) und die Response baut
  bereits AlbumResponse.from_orm()
  (src/songmaker_cli/album_api.py:79-90).
- POST /api/albums/{album_id}/cover-suggestions prüft erst check_album_access,
  committet danach — wie `unique_album_id` — die ausschließlich von Auth
  veränderte Session, nimmt erst dann einen eigenen Album-Schlüssel unter BEGIN
  IMMEDIATE/Postgres-Advisory-Lock, zählt JobType.COVER für dieses Album seit
  **UTC-Tagesbeginn** (auch fehlgeschlagene Versuche), erzeugt
  create_job(..., album_id=album.id), committet und startet danach die
  Hintergrund-Task. Bei zehn Versuchen ist der elfte 429; ein schon aktiver
  Cover-Job desselben Albums ist 409 und wird nicht gezählt. Die validierte
  Settings-Konfiguration hat Standard 10; sie ist kein pro Nutzer
  einstellbares Stundenlimit. **Code-Beleg:** check_album_access versteckt
  fremde Alben mit 404 (src/songmaker_cli/api_helpers.py:418-423),
  _begin_exclusive ist der bestehende transaktionale Lock-Owner
  (src/songmaker_cli/api_helpers.py:99-110); `unique_album_id` committet vor
  dem Lock, damit SQLite und Postgres dieselbe Check-then-act-Grenze erhalten
  (src/songmaker_cli/api_helpers.py:308-324), aber
  create_job_with_rate_limit kennt nur Generate/Score/Chat und zählt pro
  Nutzer/Stunde (src/songmaker_cli/api_helpers.py:192-285). Daher wird
  dieser Helper bewusst nicht wiederverwendet.
- GET /api/albums/{album_id}/cover-suggestions liefert ein ausdrücklich
  benanntes CoverSuggestionsResponse.from_orm: letzten Cover-Job als
  JobResponse.from_orm, sortierte Vorschläge (ID und geschützte URL),
  used_today und daily_limit, damit das Bild „1 of 10 today“ ohne zweiten
  Endpunkt darstellen kann. Er gibt auch einen terminalen Fehlerzustand ohne
  Vorschläge zurück.
- GET /api/albums/{album_id}/cover-suggestions/{suggestion_id} liefert die
  PNG-Bytes, nach check_album_access, mit einer vom Server konstruierten
  Pfadauflösung. Fremde, fehlende und Traversal-Werte erhalten gleichartig 404;
  Details werden nur intern geloggt. Weder ein Dateipfad noch eine
  /shared/.../cover-suggestions-Route werden veröffentlicht. **Code-Beleg:**
  Der private Cover-GET prüft Zugriff vor der Dateiauflösung
  (src/songmaker_cli/album_api.py:317-340), während die einzige öffentliche
  Album-Cover-Route GET /shared/{slug}/cover ist
  (src/songmaker_cli/sharing_api.py:268-289). CoverRejectedError-422 darf in
  der neuen Datei-Route und im Share nicht nach außen durchsickern.
- DELETE /api/albums/{album_id}/cover-suggestions implementiert „Discard all“.
  Alle privaten GET/PUT/DELETE-Routen erlauben Besitzer oder Admin und
  antworten für Fremde 404. Die einzige öffentliche Route bleibt
  GET /shared/{slug}/cover; nach Auswahl liest sie den gleichen cover_key.
  **Code-Beleg:** check_album_access codiert Besitzer/Admin/404 bereits
  zentral (src/songmaker_cli/api_helpers.py:418-423).

## Job-Muster im Web-Prozess

- cover ist JobType.COVER, aber **kein** JobFunction und keine ARQ- oder
  MusicWorker-Funktion. Nach dem Commit startet der Web-Prozess eine betreute
  Background-Task nach dem Vorbild des Chat-Jobs; liveness_signal=None.
  Ergänzt werden STALE_JOB_THRESHOLDS[JobType.COVER] und
  worker_liveness_by_job_type(...)[JobType.COVER] = UNKNOWN, damit der
  bestehende Reaper die Task beobachtet. **Code-Beleg:** JobFunction und der
  Scoring-Worker koppeln nur echte ARQ-Funktionen an Worker
  (src/songmaker_cli/constants.py:604-609,
  src/songmaker_cli/scoring_worker.py:27-44); die Codex-Binärdatei und ihr
  Login-Mirror sind dagegen nur bei songmaker-web gemountet
  (docker-compose.yml:102-144), während die Liveness-Abbildung Chat als
  UNKNOWN führt (src/songmaker_cli/worker_liveness.py:162-177).
- Der Job sendet Heartbeats unmittelbar vor dem Start, während des blockierend
  in asyncio.to_thread(run_cli_bounded) laufenden CLI-Aufrufs und nach dessen
  Reap. Pro Vorschlag ist der Fortschritt exakt 1/3, 2/3, 3/3; completed
  bedeutet genau drei dauerhaft gespeicherte, validierte PNGs. Fehler löschen
  die unvollständige Gruppe, setzen FAILED, nie PARTIAL, und hinterlegen nur
  einen festen UI-Grund. **Code-Beleg:** _touch_heartbeat arbeitet über eine
  eigene DB-Session (src/songmaker_cli/jobs/_runtime.py:105-115) und Chat
  besitzt bereits eine periodische Inline-Heartbeat-Task
  (src/songmaker_cli/jobs/_runtime.py:118-145).
- Die Settings benennen und validieren die Reihenfolge
  CLI_DEADLINE_SECONDS=88 < COVER_HEARTBEAT_STALE_SECONDS=120 <
  COVER_JOB_BUDGET_SECONDS=300 für drei serielle Aufrufe (zuzüglich des
  begrenzten Reap-Grace). validate_job_timeout_orders prüft diese Ungleichung
  beim Start. **Code-Beleg:** Die bestehende Settings-Validierung erzwingt
  bereits das entsprechende SSE < reaper < arq-Muster
  (src/songmaker_cli/settings.py:123-149); die Reaper-Policy ist zentral in
  STALE_JOB_THRESHOLDS (src/songmaker_cli/constants.py:612-674).
- Neue typisierte Cover-Fehler gehen durch _sanitize_error und eine
  Cover-Allowlist: mindestens **“Codex CLI is not logged in. Sign in on the
  operator host, then try again.”**, **“Image tool blocked. Ask an
  administrator to enable the image tool.”** sowie ein fester Satz für
  unbekannten CLI-/Timeout-/Artefaktfehler. Rohes stderr, Prompt,
  Providerdiagnosen, Benutzer-, Konto-, Token- und Pfaddaten bleiben im
  internen Log. **Code-Beleg:** _sanitize_error loggt die Rohursache und gibt
  nur klassifizierte Texte frei (src/songmaker_cli/jobs/_runtime.py:62-78).

## Codex-Bildadapter und Prompt

Die fünf Punkte dieses Abschnitts ersetzen den falschen CWD-Artefaktweg der
ersten Planfassung. Der Host-Versuch erzeugte das Bild unter
$CODEX_HOME/generated_images/...; das PNG im CWD entstand nur durch ein
command_execution mit Bash/ffmpeg. Deshalb darf der Server weder einen
modellgenannten Pfad noch CWD-Dateien aus diesem Versuch vertrauen.

1. Ein eigenes Bild-Entry im Codex-Adapter besitzt die Spawn-Entscheidung und
   nutzt ausschließlich run_cli_bounded; es teilt keinen neuen Prozess-Owner.
   `run_cli_bounded` erhält dafür einen expliziten, nur für den Kindprozess
   geltenden `extra_env`-Parameter: Es baut `scrubbed_env()` und ergänzt allein
   diese Werte, statt `os.environ` zu mutieren. Der Bildadapter übergibt daran
   ausschließlich sein privates `CODEX_HOME`. **Code-Beleg:** Der Co-Writer
   ruft diesen begrenzten Runner schon aus asyncio.to_thread auf
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:41-58), aber der Runner
   übergibt heute fest `env=scrubbed_env()` an Popen
   (src/songmaker_cli/agent_cli.py:306-321, 421-428); ohne diesen schmalen
   Parameter wäre die geforderte Isolation nicht durchsetzbar.
2. Das feste argv folgt _build_codex_cli_command, verwendet aber
   --sandbox workspace-write, --json, --ephemeral, leeres MCP und
   Stdin-Prompt. Der JSON-Gate akzeptiert nur image_gen sowie erwartete
   Lifecycle-/Text-Events; command_execution, Netz-, MCP-, Datei- und jedes
   unbekannte Tool-Event beendet den Aufruf mit dem festen „Image tool
   blocked…“-Fehler. **Code-Beleg:** Der vorhandene Adapter setzt noch
   read-only, --ignore-user-config, --ignore-rules, --ephemeral und
   mcp_servers={} (src/songmaker_cli/cowriter/codex_cli_adapter.py:117-136)
   und blockiert unbekannte item.*-Typen bereits fail-closed
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:70-101).
3. Jeder Aufruf erhält ein privates temporäres Arbeitsverzeichnis und setzt
   CODEX_HOME über `extra_env` darauf; ausschließlich der nötige, redigierte
   auth.json-Login-Mirror wird dorthin kopiert. Nach Reap sucht der Server per
   Glob **genau ein** PNG nur unter diesem privaten CODEX_HOME-Baum
   (einschließlich generated_images), niemals anhand eines JSONL-Pfads oder
   unter dem globalen Container-Home. Die beibehaltenen
   --ignore-user-config/--ignore-rules verhindern dabei fremde
   Nutzerkonfiguration und Tools; die Abweichung vom Experiment ist absichtlich,
   weil sein CWD-Erfolg genau auf dem danach verbotenen Shell-Tool beruhte.
   **Code-Beleg:** Der Co-Writer nutzt bereits ein TemporaryDirectory als CWD
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:48-58); der reale
   Login-Mirror liegt jedoch global unter /home/songmaker/.codex/auth.json
   (docker-compose.yml:134-142), weshalb ein privates CODEX_HOME eine
   explizite Kopie und die child-lokale Runner-Umgebung braucht.
4. Erst **nach** erfolgreichem Reap normalisiert Pillow das einzig gefundene
   Artefakt zu einem quadratischen, metadatenfreien RGB/RGBA-PNG mit exakt
   1024×1024 Pixeln. Der Writer prüft Größe, PNG-Signatur, Dekodierbarkeit und
   einen im Vorschlagsverzeichnis eingeschlossenen Zielpfad. Fehlendes,
   mehrfaches, außerhalb liegendes oder ungültiges Material ist der feste
   Artefaktfehler. **Code-Beleg:** Der vorhandene Adapter wartet schon in Erfolg
   und Fehlerpfad auf den Runner-Reap
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:102-114); die bestehende
   Cover-HTTP-Grenze übersetzt abgelehnte Medien bereits kontrolliert
   (src/songmaker_cli/album_api.py:353-357).
5. Der deterministische Prompt geht über **stdin, nie argv**, und besteht nur
   aus Albumtitel, Künstler sowie nach track_number geordneten Stil-Prompts
   und Lyrics-Auszügen. Pro Song gelten höchstens 500 Zeichen je Stil und
   Lyrics, insgesamt ein benannter Gesamt-Charaktergrenzwert; alle Werte sind
   als Daten zitiert, nicht als Anweisung. Leere Albumfelder bleiben leer;
   Benutzer-, Konto-, Pfad-, Token-, Fehler- und Providerdaten sind verboten.
   **Code-Beleg:** Der aktuelle Adapter baut sein Prompt als Bytes und übergibt
   es als stdin_payload, nicht als Argument
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:45-57), während der finale
   -Parameter Stdin ausdrücklich markiert
   (src/songmaker_cli/cowriter/codex_cli_adapter.py:117-136).

## Provider-Weg

Der Cover-Job fragt genau **eine** schmale Codex-Weg-Funktion beim
Dispatch-/Katalog-Owner ab: heute entscheidet sie über das Vorliegen des
gespiegelten CLI-Access-Tokens, #532 ersetzt ausschließlich diese Entscheidung
durch die Admin-Einstellung. Der Bildadapter erhält die entschiedene Methode,
entnimmt oder konfiguriert keine Credentials und hat keinen OpenAI-Images-
Fallback. Lautet die Entscheidung nicht CODEX_CLI, schlägt der Job mit einem
benannten festen Grund fehl; „not logged in“ erscheint nur für den gewählten
CLI-Weg ohne Login. **Code-Beleg:** Der heutige Dispatch nimmt bei Token die
CLI und fällt sonst auf die OpenAI-Chat-API zurück
(src/songmaker_cli/cowriter/dispatch.py:81-104); der Katalog kennt CODEX_CLI
als Setup-Methode (src/songmaker_cli/cowriter/catalog.py:76-85,
src/songmaker_cli/cowriter/catalog.py:360-370). Die neue Cover-Funktion muss
diesen existierenden Owner erweitern, statt die alte Chat-Fallbacklogik
wiederzuverwenden.

## Beweis und Schnitt

**C1a – vor dem ersten Edit, zuerst:** Migration mit Job.album_id und
AlbumCoverSuggestion, Query-/Cleanup-Owner, Tageslimit mit Album-Lock, Rechte,
fünf API-Routen und Pydantic-/Frontend-Typen. C1a ist fertig, wenn POST-Upload
unverändert bleibt, PUT nur JSON-Suggestion akzeptiert,
CoverSuggestionsResponse letzten Job/Vorschläge/used_today/Limit liefert, und
Fremde inklusive Vorschlagsdatei 404 erhalten.

Vor dem C1a-Dispatch berichtigt der Head außerdem den Körper von #533 auf
denselben HTTP-Vertrag (POST ist und bleibt Upload; PUT nimmt ausschließlich
`suggestion_id`), damit die Plan- und Issue-Verträge nicht auseinanderlaufen.

**C1b – hängt an C1a:** Web-Background-Job, Prompt, Codex-Bildadapter,
CODEX_HOME-Isolierung, Dateiübernahme, Heartbeats und Sanitizing. C1b ist
fertig, wenn drei erfolgreiche Dateien vorhanden sind oder bei Fehler keine
Gruppe; #533 schließt erst mit beiden Slices und dem Live-Proof.

- API-Tests beweisen 1/3 bis 3/3, genau drei 1024-PNGs, UTC-Tag und den
  serialisierten elften Versuch (429), aktiven Doppelstart (409), used_today,
  Tageslimit, Discard ohne Verlust von cover_key und die 404-Gleichheit für
  fremd/fehlend/Traversal. Auswahl und Upload setzen beide über den bestehenden
  Writer cover_key; Entfernen stellt die Initiale wieder her;
  /shared/{slug}/cover zeigt genau das ausgewählte Bild und es existiert keine
  öffentliche Suggestions-Route.
- Job-/Adapter-Tests belegen Web-Job statt ARQ, JobType.COVER mit
  liveness_signal=None, Reaper-Schwelle, vor/während/nach-Heartbeat,
  Deadline-Reaper-Budget-Reihenfolge, Reap vor Übernahme sowie die drei
  Vorschlags-Atomizität. Sie pinnen das feste argv inklusive workspace-write,
  privaten CWD und child-lokalem `extra_env`-CODEX_HOME, kopierten Login-Mirror,
  Stdin-Prompt mit
  Einzel-/Gesamtlimits, Datenquotierung, optionalem `image_gen`- sowie den
  erwarteten Lifecycle-/Text-Events und Fehler für command_execution/Netz/MCP/
  Datei/unbekannt. Sie verlangen nicht, dass ein `image_gen`-Event erscheint:
  der dokumentierte erfolgreiche Versuch enthielt nur agent_message und
  command_execution. Sie erzwingen außerdem
  Server-Glob statt JSONL-Pfad sowie Ablehnung von fehlenden, mehreren,
  falschen, zu großen, nicht dekodierbaren und Traversal-Artefakten.
- Persistenz-/Cleanup-Tests erzwingen den Geschwisterpfad
  `cover-suggestions/{album_id}/…` außerhalb von `covers/`, seine kanonische
  Volume-Containment-Prüfung, Discard-all nach Commit sowie die Entfernung
  nach Commit aus beiden bestehenden Album-Hard-Delete-Pfaden (Retention und
  Nutzer-Hard-Delete). Ein DELETE `/cover` darf die Vorschläge dabei nicht
  entfernen.
- Modell-/Schnitt-Tests erzwingen _sanitize_error für beide Musikertexte und
  alle Cover-Fehler, AlbumResponse.from_orm, CoverSuggestionsResponse.from_orm
  und generate_types.py --check.
- Live-Abnahme nach dem Bau: Ein archiviertes Proof-Album erzeugt im laufenden
  Stack drei Dateien; der Besitzer wählt eine, ersetzt sie per bestehendem
  Upload und entfernt sie wieder. Das Album wird anschließend gemäß
  Repository-Regel archiviert, nicht gelöscht.
