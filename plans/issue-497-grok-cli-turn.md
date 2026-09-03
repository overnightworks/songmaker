# #497 – Grok-Co-Writer über die Abo-Anmeldung

**Leser/Entscheidung:** Builder und Reviewer setzen R1 um, ohne zweiten
Credential-Owner oder verdeckten API-Fallback. Vertrag: #497; E1/E2 und
Sicherheitsrahmen: #321; Sicherheits-Owner: `docs/security.md`.

## Befund, der den Schnitt bestimmt

- `~/.grok/auth.json` trägt Zugriff in `key`, Erneuerung in `refresh_token`
  und die Frist in `expires_at`; auf diesem Host sind es 21.600 Sekunden
  (sechs Stunden) ab `create_time`. `GROK_HOME` ist nicht gesetzt; gesetzt
  ersetzt es das gesamte Profil.
- Der #350-Owner existiert: `mirror_agent_cli_credentials.py` schreibt
  `grok.json` in-place, behält den Zugriff, leert `refresh_token` und lehnt
  unbekannte Felder ab. Path-Watcher (Änderung/Ersetzung) und 10-Minuten-Timer
  halten ihn aktuell; Compose mountet nur die read-only-Kopie.
- `grok --help` belegt `--prompt-file`, `--output-format streaming-json`,
  `--deny` und `--max-turns`. NDJSON enthält u.a. `text`, `tool_call`,
  `tool_call_update`, `available_commands`, `usage` und `end`.
- `agent_cli.grok_cli_status()` leitet den Login dagegen aus `grok models`
  ab. Das ist weiterhin Katalog-/Diagnoseinformation, aber ausdrücklich
  **nicht** der Turn-Dispatcher: ein abgelaufenes, noch vorhandenes Login
  darf nicht als „kein CLI-Login“ in den API-Key-Weg fallen.

## Umsetzung

1. **Ein gemeinsamer Spawn-Owner:** `agent_cli.py` erweitert
   `run_cli_bounded`, ohne seine bestehenden Lesearten `read="all"` und
   `read="first_line"` zu ändern, um einen begrenzten stdout-Zeilenkanal und
   eine thread-sichere Abbruchanforderung. Nur der Runner besitzt bereinigte
   Umgebung, `start_new_session`, begrenztes Lesen/Schreiben, TERM/KILL der
   Prozessgruppe und Reap – auch bei Deadline, Kanalüberlauf oder Abbruch.
   Ausschließlich wenn ein Caller Prompt-**Bytes** übergibt, erzeugt der
   Runner eine private `0600`-Prompt-Datei, ersetzt den dafür vorgesehenen
   argv-Pfad und entfernt die Datei im `finally`; ohne Bytes gibt es keine
   Datei. Der Adapter kann nur Abbruch anfordern und das Ergebnis abwarten;
   er verwendet weder `Popen` noch eigene Reap-Logik. Claude-Proben behalten
   ihre bisherige stdin-Nutzlast. Claude-Streaming-Spawn, Pooling,
   Tool-Policy und Parser bleiben in `claude/provider.py`.
2. **Kanal-/Abbruchvertrag:** Der neue Kanal ist ein Zusatz zu den
   Read-Modi: Der Runner sendet ganze, größenbegrenzte stdout-Zeilen in einen
   begrenzten Kanal und schließt ihn erst mit seinem eindeutigen
   `CliRunOutcome`. Eine Consumer-Cancellation setzt die Abbruchanforderung
   und wartet den Runner ab. Bei Timeout, Abbruch, Überlauf, Spawn-/I/O-Fehler
   oder unvollständigem Prozess gibt es kein `FinalEvent`; bereits gepufferte,
   noch nicht gelesene Zeilen werden verworfen. Bei Policy-, Protokoll- oder
   CLI-Fehlern wirft der Adapter `ProviderUnavailableError("grok", "<code>")`
   statt ein Event zu liefern; bei Client-Cancellation liefert er nichts mehr.
3. **Grok-Adapter:** Neu `cowriter/grok_cli_adapter.py`. Er nutzt die
   bestehende Claude-Formatierung `_flatten_messages` plus `_stdin_prompt`
   (Systempräfix); es entsteht kein dritter Flacher. Er übergibt diesen Inhalt
   ausschließlich als Bytes an die Runner-Prompt-Datei und pinnt das argv auf
   `grok --prompt-file <private-path> --output-format streaming-json --deny
   '*' --max-turns 1 --no-subagents --disable-web-search --model <model>`:
   `--prompt-file` allein ist Single-Turn, daher ist `-p` verboten. Der Runner
   startet Grok außerhalb des App-Trees (wie das Flag-Experiment in `/tmp`).
   Grok-spezifisch bleiben Flags und NDJSON-Parser; Gedanken-, Nutzungs- und
   Signaturinhalte erreichen weder Chat noch Log. Der Runner erfasst Grok-
   `stderr` intern getrennt von stdout, ausschließlich für die
   Fehlerklassifikation; sein Rohinhalt erreicht weder Chat, SSE/Exception
   noch Log. Bei einem CLI-Fehler darf ein Log – wie bei Claude – nur
   Returncode und stderr-Länge enthalten.
4. **NDJSON-Vertrag und Werkzeug-Gate:** Jede Zeile muss UTF-8-JSON-Objekt
   mit String-`type` sein. Akzeptiert sind `text` mit String-`data` (wird
   `AssistantTextEvent`), `end` mit String-`stopReason` sowie korrekt
   geformte, ignorierte `thought`, `usage`, `available_commands` und
   `plan`-Beobachtungen. Ein `error` braucht String-`message` und ist kein
   Beobachtungs-Event. Enthält seine `message` **oder** das intern erfasste,
   unstrukturierte stderr 401, OIDC oder `unauthenticated`, wirft der Adapter
   `ProviderUnavailableError("grok", "cli_login_expired")`; jedes andere
   `error`-Event und jeder andere CLI-Fehler wird
   `ProviderUnavailableError("grok", "grok_cli_error")`. Die geprüften
   Diagnosetexte werden dabei nie weitergegeben. Genau ein `end` plus
   erfolgreicher vollständiger Runner-Abschluss erzeugt danach ein
   `FinalEvent`; ein vollständiger oder unvollständiger Lauf ohne `end` ist
   niemals erfolgreich, sondern derselbe benannte Fehler (`cli_login_expired`
   bei Auth-Markierung, sonst `grok_cli_error`). Ungültige Form, unbekannter
   Typ oder zweites `end` sind
   `ProviderUnavailableError("grok", "grok_cli_stream_protocol_error")`:
   Abbruch anfordern, reapen lassen, nie ein Finale. Jedes `tool_call` oder
   `tool_call_update` – auch mit sonst fehlerhafter Nutzlast – ist
   `ProviderUnavailableError("grok", "grok_cli_tool_call_blocked")` mit
   derselben Semantik. Eine angekündigte Werkzeugliste ist kein Aufruf. Es
   gibt weder MCP-Konfiguration noch Songwerkzeuge.
5. **Spiegel und Ablauf:** Kein neuer Watcher, keine Kopie des Refresh-Tokens:
   #350 bleibt alleiniger Host-Refresh-Owner. Ergänze den Verhaltensnachweis
   „aktualisiertes Host-`key` erscheint im Spiegel, `refresh_token` bleibt
   leer“. OIDC/401 oder abgelaufenes gespiegeltes Login wird
   `cli_login_expired`; der ausgewählte CLI-Turn endet dort, nie über Key.
6. **Dispatch bis R2:** Nur für den Grok-Zweig von
   `stream_cowriter_turn` liest `dispatch.py` vor dem Turn das gemountete
   `/home/songmaker/.grok/auth.json`: ein nichtleerer String-`key` in einem
   Realm wählt die CLI, `{}` oder kein Token erlauben den `XAI_API_KEY`-Weg;
   fehlen beide, folgt der benannte Nichtverfügbarkeitsfehler. Die
   `grok models`-Probe ist kein Diskriminator. Ein vorhandenes, aber
   abgelaufenes/OIDC-401-Login geht in die CLI und endet als
   `ProviderUnavailableError("grok", "cli_login_expired")`, nie über HTTP;
   jeder weitere CLI-Fehler startet ebenfalls keinen HTTP-Turn. R1 ändert
   weder Codex noch `call_provider_once` (beide Judges bleiben Key-basiert)
   und berührt `cowriter/catalog.py` nicht; der CLI-Katalog gehört
   ausdrücklich zu R5.
7. **Sicherheitsdokument:** `docs/security.md` ergänzt nur sechs Stunden
   Zugriffsgültigkeit, #350 als Refresh-Owner und `cli_login_expired`; die
   vorhandene Redaktions- und Mount-Tabelle wird nicht dupliziert.

## Tests und Abnahme

- `tests/test_agent_cli.py`: Die bisherigen `all`- und `first_line`-Verträge
  bleiben grün; zusätzlich 0600-Prompt nur bei Bytes, gescrubbte Umgebung,
  Prozessgruppen-Reap bei Abschluss/Timeout/Abbruch, Kanalgrenze und dass nur
  der Runner nach einer Adapter-Abbruchanforderung terminiert/reapet.
- Neuer `tests/test_grok_cli_adapter.py`: Das vollständige argv entspricht
  exakt der oben genannten Reihenfolge (insbesondere `--prompt-file` ohne
  `-p`, `--output-format streaming-json`, `--deny '*'`, `--max-turns 1`,
  `--no-subagents`, `--disable-web-search` und `--model`); der Prompt ist
  Claude-kompatibel abgeflacht und der cwd ist nicht der App-Tree. Gefälschtes
  NDJSON wird Text plus genau ein Finale. `tool_call` und
  `tool_call_update` werfen `ProviderUnavailableError("grok", "<code>")`, reapen
  und liefern kein `FinalEvent`; ebenso ungültige/unklare Events, zwei `end`,
  Timeout und Abbruch. Ein NDJSON-`error` mit Auth-Markierung oder ein
  unvollständiger Lauf mit 401/OIDC/`unauthenticated`-Markierung wird
  `ProviderUnavailableError("grok", "cli_login_expired")`, andere
  `error`-Events, CLI-Fehler und ein Lauf ohne `end` werden
  `ProviderUnavailableError("grok", "grok_cli_error")`. E2 deckt die
  Mischform aus NDJSON-`error` und unstrukturierter stderr-401-Zeile ab: sie
  endet als `cli_login_expired`, ohne dass ihr Inhalt in Chat, SSE/Exception
  oder Logs erscheint (im Log höchstens Returncode und stderr-Länge).
- `tests/test_cowriter_dispatch.py`: Ein nichtleeres `key`-Token im
  gemounteten `auth.json` geht Key vor; `{}`/fehlendes Token nimmt den Key,
  fehlende beide ergeben den benannten Fehler. Ein vorhandenes abgelaufenes
  Login (auch mit `XAI_API_KEY`) nutzt die CLI und wird
  `cli_login_expired`, nie HTTP. Ein erfolgreicher CLI-Turn wird durch den
  Dispatcher gestreamt; kein CLI-Fehler wechselt innerhalb desselben Turns zu
  HTTP. Codex und `call_provider_once` bleiben unverändert.
- `tests/test_conversation_api.py`: Ein Adapterfehler nutzt den bestehenden
  Provider-Fehlerpfad; weder leere Assistant-Nachricht noch Final-SSE wird
  persistiert/gesendet.
- `tests/test_mirror_agent_cli_credentials.py` und Install-Tests: jeder
  Host-Refresh ersetzt den gespiegelten Zugriff in-place, hält den Refresh
  leer und Path/Timer beobachten `~/.grok/auth.json`.
- Live nach Deploy: ein Stack-Turn ohne `XAI_API_KEY` liefert Text; ein
  abgelaufenes Login und künstliches `tool_call` sind sichtbar benannt.

## Flag-Experiment (03.09.2026)

`env -u XAI_API_KEY grok -p 'Antworte nur OK' --deny '*' --max-turns 1
--output-format streaming-json --cwd /tmp` endete Exit 0 nach einem Turn.
Der Gegenversuch
`grok -p --prompt-file <datei>` scheitert mit „a value is required for
'--single <PROMPT>'“: `--prompt-file` ist selbst die Single-Turn-Option.
Trotz `--deny '*'` kündigte der Stream 24 eingebaute Werkzeuge an, enthielt
aber keinen `tool_call` und antwortete `Contract loaded.` und `OK`. Die Flag
ist akzeptiert, beweist aber keine werkzeugfreie Oberfläche; das Stream-Gate
ist deshalb zwingend.

## Codebelege für die eingearbeiteten Reviewpunkte

1. **Token-Dispatch statt Probe:** Compose mountet `grok.json` als
   `/home/songmaker/.grok/auth.json` (`docker-compose.yml`), und
   `_redact_grok` erhält den String `key`, leert aber `refresh_token`
   (`scripts/mirror_agent_cli_credentials.py`). Dagegen ruft
   `_probe_grok_status` über `grok_cli_status()` `grok models` auf
   (`src/songmaker_cli/agent_cli.py`); dieser Probeausfall darf keinen
   Key-Fallback auslösen.
2. **argv:** `claude/provider.py:_build_cli_cmd` zeigt, dass `-p` eine
   eigene Prompt-Option ist; das Live-Gegenexperiment oben belegt ihre
   Unvereinbarkeit mit `--prompt-file`. Der Grok-Plan pinnt deshalb die
   vollständige Single-Turn-Argumentliste ohne `-p`.
3. **NDJSON-Fehler und stderr:** `agent_cli.run_cli_bounded` startet bei
   `stderr="capture"` mit getrennten stdout-/stderr-Pipes und gibt beide
   getrennt im `CliRunOutcome` zurück; `_combined_cli_output` fasst sie nur
   für die Statusprobe zusammen (`src/songmaker_cli/agent_cli.py`). Der
   Grok-Adapter darf diese Zusammenführung nicht verwenden: Er klassifiziert
   die intern gehaltenen Diagnosen und verwirft ihren Text. Der bestehende
   Claude-Fehlerpfad protokolliert bei nichtnull Returncode ausschließlich
   `rc` und `len(stderr_bytes)` (`claude/provider.py`, ca. Zeilen 297–305);
   Grok übernimmt genau diese Nicht-Leak-Regel. `conversation_api.py`
   behandelt die vorhandene `ProviderUnavailableError` bereits generisch als
   503, daher bleibt die Fehlersignatur zweistellig und der Code in der
   Exception/Log-Nachricht.
4. **Spawn und Flatten:** `run_cli_bounded` besitzt heute `read="all"` und
   `read="first_line"` sowie `Popen(..., env=scrubbed_env(),
   start_new_session=True)` und den Gruppen-Reap (`agent_cli.py`);
   `claude/provider.py:_spawn_reserved_async_cli_process` ist hingegen der
   Claude-Streaming-Owner. `_flatten_messages` und `_stdin_prompt` dort
   definieren die bestehende Inhaltsform.
5. **Fehlerform:** `cowriter/errors.py:ProviderError.__init__` nimmt
   `(provider, message)` und `ProviderUnavailableError` erweitert sie ohne
   eigenen Konstruktor. Alle Grok-Codes stehen daher als
   `ProviderUnavailableError("grok", "<code>")`, nicht als umgebaute Klasse
   oder einzelnes Argument.

**Abweichungen vom zweiten Review:** keine. Die aus dem Review zusätzlich
abgeleitete Unterscheidung `{}`/fehlendes Token gegen vorhandenes abgelaufenes
Token ist als Dispatch- und Testvertrag festgeschrieben; die E2-Mischform
NDJSON-`error` plus stderr-401 ist nun ebenfalls explizit abgenommen.

## Dateien

Ändern: `src/songmaker_cli/agent_cli.py`, `claude/provider.py`, neuer
`cowriter/grok_cli_adapter.py`, `cowriter/dispatch.py`, die genannten Tests
und `docs/security.md`.

Bewusst nicht: `cowriter/catalog.py`, Judge-/Katalog-Erreichbarkeit und
CLI-Katalog (**R5**); MCP/Songwerkzeuge (**R4**); Admin-Schalter/UI (**R2**);
Codex-Turn (**R3**); API-Vertrags- oder Persistenzänderungen.
