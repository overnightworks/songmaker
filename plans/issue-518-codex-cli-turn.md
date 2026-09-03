# #518 – Codex-Co-Writer über die Abo-Anmeldung

**Leser/Entscheidung:** Builder und Reviewer bauen R3 ohne API-Key-Fallback,
Credential-Duplikat oder stillen Werkzeugeinsatz. Vertrag: #518; Schnitt und
Sicherheitsrahmen: #321; Vorbild: #497; Credential-Owner: #350.

## Befund und Schnitt

- #497 besitzt den gemeinsamen Spawn-Owner `agent_cli.run_cli_bounded`:
  `scrubbed_env()`, begrenztes I/O, Prozessgruppen-Reap, `CliLineChannel`,
  Prompt-Dateien und private Arbeitsverzeichnisse. Codex ergänzt nur
  Konstanten, `cowriter/codex_cli_adapter.py`, den Codex-Zweig in
  `cowriter/dispatch.py` sowie Parser-/Flag-Regeln; kein zweiter `Popen` oder
  Prompt-Owner.
- `~/.codex/auth.json` hat nur `auth_mode`, `tokens.id_token`,
  `tokens.access_token`, `tokens.refresh_token`, `tokens.account_id` und
  `last_refresh` (Feldnamen, keine Werte). #350 spiegelt das Dokument
  in-place, hält `refresh_token` leer und nullt `OPENAI_API_KEY`.
- Der neue, alleinige Codex-Discriminator ist
  `_codex_cli_access_token_is_present()` in `cowriter/dispatch.py`, mit
  `CODEX_CLI_AUTH_FILE = "/home/songmaker/.codex/auth.json"` in
  `constants.py`, analog zu Groks `_grok_cli_token_is_present()`. Ein
  nichtleeres String-`tokens.access_token` wählt CLI. Fehlende Datei, `{}`
  und fehlendes/leeres Feld wählen den bisherigen API-Key-Weg; unlesbare Datei,
  ungültiges JSON, kein Objekt oder ein nicht-String-Feld ergeben
  `ProviderUnavailableError("codex", "codex_cli_error")`, niemals HTTP.
  Das ist kein Aufruf von `codex_cli_login()` (`codex login status` ist nur
  Katalog-/Statusprobe). Ein vorhandenes, aber abgelaufenes Token bleibt CLI
  und fällt im Turn niemals auf HTTP zurück.

## Umsetzung

**Entschiedenes argv:** Der gepinnte Codex-Aufruf enthält sowohl
`--skip-git-repo-check` als auch `--ignore-user-config`: Der private
`TemporaryDirectory`-cwd ist kein Git-Repository und würde ohne die erste Flag
vor jedem JSONL-Event mit „Not inside a trusted directory“ scheitern; die zweite
unterbindet lokale `config.toml`-Defaults. Der Command-Test pinnt beide Flags.
Unbekannte `item.type`-Werte, etwa `todo_list` oder Plan-Updates, bleiben
bewusst `codex_cli_stream_protocol_error`.

1. **Codex-Adapter und vollständiges argv:**
   `stream_codex_cli_turn()` flacht System und Nachrichten mit
   `_flatten_messages()` und `_stdin_prompt()` aus `claude.provider` ab und
   übergibt sie als `stdin_payload` an genau dieses argv:

   ```text
   codex exec --json --sandbox read-only --skip-git-repo-check
   --ignore-user-config --ignore-rules --ephemeral -c approval_policy="never"
   -c mcp_servers={} --model <model> -
   ```

   `_build_codex_cli_command(model)` gibt diese Reihenfolge als Tuple zurück;
   der Test pinnt sie inklusive `--model <model>` vor dem terminalen `-`.
   `--ephemeral` wurde mit `codex exec --help` am 03.09.2026 bestätigt und
   verhindert neben dem privaten cwd persistierte Session-Dateien. Wie
   `stream_grok_cli_turn()` erzeugt der Adapter ein
   `TemporaryDirectory(prefix="songmaker-codex-cli-")`, übergibt dessen
   privaten Pfad als `cwd` an `run_cli_bounded` und räumt ihn erst nach dem
   reaped Runner auf. `scrubbed_env()` entfernt `OPENAI_API_KEY`;
   `--ignore-user-config`, `--ignore-rules` und `mcp_servers={}` schließen
   konfiguriertes MCP. Der Adapter besitzt
   `CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES` (nicht den 64-KiB-Probe-Default
   `CLI_OUTPUT_READ_LIMIT_BYTES`): derselbe 4-MiB-Turn-Bound wie
   `GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES`, an
   `run_cli_bounded(..., output_read_limit_bytes=...)` übergeben, trägt
   Reasoning/JSONL ohne unbeschränktes Lesen.

2. **JSONL-Allow-/Block-Liste statt Zustandsautomat:**
   `_parse_codex_line()` validiert eine Objektzeile; die konsumierende Schleife
   behandelt nur diese vollständige Oberfläche aus dem Codex-JSONL-Vertrag:

   - `thread.started` und `turn.started` werden als Beobachtungen erlaubt;
   - `item.completed` mit `item.type == "agent_message"` verlangt Text,
     sammelt ihn und sendet ausschließlich `AssistantTextEvent`;
   - `item.completed` mit `item.type == "reasoning"` wird verworfen;
   - `turn.completed` verlangt `usage` und markiert den Erfolg;
   - jedes `item.*` mit `item.type` in der geschlossenen Block-Liste
     `command_execution`, `mcp_tool_call`, `web_search`, `file_change`
     beendet den Kanal via `request_abort()`, reapt und ergibt
     `codex_cli_tool_call_blocked` ohne `FinalEvent`.

   Alle übrigen Typen, nicht passende Formen, defektes UTF-8/JSON und ein
   fehlendes erfolgreiches `turn.completed` ergeben
   `codex_cli_stream_protocol_error`. Es gibt bewusst keine Reihenfolge-FSM:
   die Allow-/Block-Liste ist gegenüber zusätzlichen zulässigen Beobachtungen
   robust, aber für unbekannte bzw. Werkzeug-Items fail-closed. Nach dem
   Outcome `COMPLETE` mit Returncode 0 und genau einem Erfolg endet der Adapter
   mit genau einem `FinalEvent`; ein zweites `turn.completed` ist ein
   Protokollfehler. Er loggt keine Event-Payloads.

3. **Fehlerklassifikation ohne Diagnosetext:**
   Top-Level-`error` und `turn.failed` nehmen jeweils nur ihre `message` zur
   internen Klassifikation an und fordern den Runner-Abbruch an. Zusammen mit
   intern gehaltenem `CliRunOutcome.stderr` prüft `_contains_auth_failure()`
   die Marker `401`, `unauthorized`, `unauthenticated`. Trifft einer zu —
   auch bei `error: Reconnecting … 401 Unauthorized` ohne `turn.failed` —
   wird `ProviderUnavailableError("codex", "cli_login_expired")` geworfen;
   sonst `ProviderUnavailableError("codex", "codex_cli_error")`.
   `_raise_for_codex_outcome()` fasst Streamfehler, nicht erfolgreichen Runner,
   fehlendes Ende und Returncode zusammen. Logging enthält höchstens
   Returncode und `len(stderr)`, nie Message, stderr, Prompt, Chat, SSE oder
   Exception-Diagnosetext. Der Dispatcher propagiert den Codex-Fehler aus dem
   CLI-Zweig; er ruft anschließend keinen HTTP-Adapter auf.

4. **Gemeinsamer #497-Reviewrest — Prompt-Datei/Kanalschluss:**
   In `agent_cli._run_cli_bounded()` liegt `_unlink_prompt_file()` heute im
   `finally` vor `_publish_bounded_outcome()` und
   `CliLineChannel._close()`. Die Umsetzung fängt dort jedes andere `OSError`
   als `FileNotFoundError`, ersetzt das vorhandene Outcome durch ein
   fehlgeschlagenes `CliRunOutcome` mit `reason=CliRunReason.IO_ERROR`,
   `complete=False` und `io_error=exc`, publiziert dieses Ergebnis und schließt
   danach den Kanal. `FileNotFoundError` bleibt idempotent. Damit kann kein
   Consumer hinter `channel.receive()` hängen, auch wenn das Unlinken scheitert.
   Der Codex-stdin-Weg erzeugt keine Prompt-Datei, beweist aber den gemeinsamen
   Runner-Vertrag.

5. **Experiment richtig eingeordnet:** Das Host-Experiment vom 03.09.2026
   (`env -u OPENAI_API_KEY codex exec --json` mit den oben verfügbaren Gates
   und „Antworte nur OK“) endete 0; es sah `thread.started`, `turn.started`,
   `item.completed`/`agent_message` und `turn.completed`, Textlänge 2. Es
   belegt ausschließlich diesen Glückspfad ohne API-Key. Die vorhandenen Flags
   ersetzen den Stream-Gate nicht; dessen Item-Typen kommen aus dem
   JSONL-Vertrag, nicht aus diesem einen Lauf.

6. **Dokumentations-Owner:** `docs/security.md` erhält Spiegel-,
   Refresh-/Fehler-, argv-/Stream-Gate- und Nicht-Leak-Fakten;
   `docs/architecture.md` nur Dispatch-/Adapter-Owner. Keine Kopie der
   Mirror-Feldtabelle; #350 bleibt deren Quelle. `call_provider_once()` sowie
   Judge und Katalog bleiben API-Key-Owner, und R2 (Admin-Schalter/UI) sowie R4
   (MCP/Songwerkzeuge) bleiben außerhalb dieses Schnitts.

## Tests, Abnahme und Requirement-Ritual

- `tests/test_codex_cli_adapter.py` erhält die ACC-12-markierte Happy-Path-
  Sequenz und pinnt `_build_codex_cli_command()`, stdin, gescrubbte Umgebung,
  `--ephemeral`, privaten `TemporaryDirectory`-cwd und den expliziten
  4-MiB-`output_read_limit_bytes`. Parametrisierte Fälle decken alle vier
  geblockten `item.*`-Typen, `agent_message`, verworfenes `reasoning`,
  unbekannte/nicht passende Formen, defektes JSON, fehlendes und zweites
  `turn.completed`, Abbruch sowie Kanalüberlauf ab; blockierte oder defekte
  Sequenzen reapen und senden kein Finale. Ein begrenzter JSONL-Stream über
  dem Codex-Turn-Limit ergibt den Runner-Output-Limit-Fehler statt
  unbeschränktem Lesen.
- Dieselbe Adapter-Suite prüft Top-Level-`error`, `turn.failed` und stderr
  jeweils mit und ohne `401`/`unauthorized`/`unauthenticated`; insbesondere
  wird Reconnecting-401 zu `cli_login_expired`, nicht zu
  `codex_cli_stream_protocol_error`. `caplog` beweist, dass weder erfundener
  Diagnosetext noch stderr/Prompt in Log, SSE oder Exception auftauchen.
- `tests/test_cowriter_dispatch.py` ergänzt ACC-12 für den nichtleeren
  `tokens.access_token`-CLI-Dispatch und ACC-13 für den Codex-Fehler ohne
  HTTP-Fallback. Die Fälle fehlend, `{}` und leer wählen HTTP; unlesbar,
  ungültiges JSON, Nicht-Objekt und nicht-String werfen `codex_cli_error` und
  rufen HTTP nicht auf. Ein vorhandenes abgelaufenes Token — auch neben einem
  Key — nimmt CLI und endet `cli_login_expired`; der Stream wird wie bei Grok
  geschlossen weitergereicht.
- `tests/test_agent_cli.py` ergänzt zum normalen Prompt-Datei-Fall und
  `FileNotFoundError` ein anderes Unlink-`OSError`: beobachtet wird ein
  `IO_ERROR`-Outcome vor dem Kanalschluss und ein wartender Consumer erhält
  immer das Terminalergebnis. Die vorhandenen globalen Byte-Limit-Tests
  bleiben der Beleg für die gemeinsame Obergrenze; der neue Adaptertest pinnt
  zusätzlich seinen größeren, endlichen Turn-Wert.
- **REQ-Ritual:** In `docs/acceptance/acceptance.toml` werden
  `ACC-COWRITER-12` → `REQ-COWRITER-09` (Codex-CLI-Alleinweg) und
  `ACC-COWRITER-13` → `REQ-COWRITER-11` (benannter Codex-Fehler ohne
  HTTP-Fallback) als `integration`/`critical` ergänzt. Die zugehörigen
  `@pytest.mark.acceptance`-Tests, Manifestlisten in
  `tests/test_requirement_contract.py`, `docs/PRODUCT.md` und
  `check_requirements` werden aktualisiert. `REQ-COWRITER-10`, `-12` und
  `-13` erhalten keine erfundene Kante: Default bzw. bestehender Gesprächs-
  und Persistenzpfad ändern sich nicht und werden nicht als bewiesen ausgegeben.
- Nach Deploy beweisen ein Stack-Turn ohne `OPENAI_API_KEY`, ein simuliert
  abgelaufenes Spiegel-Login und ein gefälschtes Werkzeug-Event die drei
  benannten Ergebnisse.

## Bewusst nicht

Kein Admin-Schalter/UI (R2), kein MCP oder Songwerkzeug (R4), kein
Codex-CLI-Katalog (R5), keine Änderung an Judge/API-Calls oder Persistenz,
kein Refresh im Container und keine zweite Credential-Kopie.
