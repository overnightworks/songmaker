# #527 – MCP-Songwerkzeuge in Grok- und Codex-CLI-Turns

**Leser/Entscheidung:** Builder und Reviewer entscheiden, ob ein
Subscription-CLI-Turn dieselbe begrenzte Songwerkzeug-Oberfläche wie Claude
sicher erreichen kann. Vertrag: #527; E1 und R4-Schnitt: #321;
Sicherheitsowner: `docs/security.md`.

## Ergebnis des Host-Experiments vom 04.09.2026

Das Experiment lief nur mit einem wegwerfbaren, lokalen stdio-MCP-Server
`echo`; er kennt genau das Werkzeug `echo`, keine Datenbank und keine
Songdaten. Für jede CLI entstand ein eigenes `0700`-Home. Die vorhandene
Auth-Datei wurde als Bytes hineinkopiert und anschließend auf `0600` gesetzt;
`config.toml` war ebenfalls `0600`. Das Profil und alle Aufzeichnungen wurden
nach der Messung entfernt. Weder Zugangsdaten noch Werkzeug-Nutzlasten gehören
in diese Datei, Logs oder den Plan.

Die folgenden Befehle sind die reproduzierbare Messform; `<tmp>` steht für das
wegwerfbare Profil und `<echo-server>` für den lokalen Server:

```text
GROK_HOME=<tmp>/grok grok mcp add echo -- /usr/bin/python3 <echo-server>
GROK_HOME=<tmp>/grok grok --single 'Call the echo tool with hello and answer OK' \
  --output-format streaming-json --allow 'MCPTool(echo__*)' --max-turns <n> \
  --no-subagents --disable-web-search

CODEX_HOME=<tmp>/codex codex mcp add echo -- /usr/bin/python3 <echo-server>
printf '%s' 'Call the echo tool with hello and answer OK' | \
  CODEX_HOME=<tmp>/codex codex exec --json --sandbox read-only \
  --skip-git-repo-check --ignore-rules --ephemeral \
  -c 'approval_policy="never"' -
```

| CLI | Startereignis und Verbindung | Allow ohne Prompt | Deny-Vorrang | Turn-Grenze |
| --- | --- | --- | --- | --- |
| Grok 1.0.5 | Erstes `available_commands` listet nur Builtins; nach `initialize`, `notifications/initialized`, `tools/list` folgt ein weiteres `available_commands` mit `echo__echo`. Der MCP-Aufruf erscheint außen als `tool_call` `use_tool`; sein `rawInput.tool_name` ist `echo__echo`. | `--allow 'MCPTool(echo__*)'` ließ den explizit erzwungenen lokalen Aufruf ohne Interaktionsprompt laufen (`tools/call`, danach `tool_call_update` `completed`). Der normale Satz allein kann vorher Builtins wählen und ist daher kein Allow-Beweis. | Mit derselben Allow-Form plus `--deny '*'` wurde der explizite MCP-Aufruf als `use_tool` versucht, aber `failed`; der Server erhielt kein `tools/call`. Deny gewinnt. | `--max-turns 1` schafft Aufruf, aber keine Antwort (`max_turns_reached`, `end.cancelled`); mit `2` kommen Aufruf und Textantwort zustande. Die Produktgrenze muss daher mindestens zwei Turns sein, nicht eins. |
| Codex 0.147.0 | Erstes JSON-Ereignis ist `thread.started`, dann `turn.started`; die CLI gibt keine Werkzeugliste aus. Der Server erhielt zwar `initialize`, `notifications/initialized`, `tools/list`, aber die Namen stehen nicht im CLI-Stream. | Die registrierte Konfiguration erzeugte `item.started`/`item.completed` für `mcp_tool_call`, doch bei `approval_policy="never"` endete der Aufruf ohne Prompt als „user cancelled MCP tool call“; kein `tools/call` erreichte den Server. Das ist keine erlaubte Werkzeugnutzung. | Codex bietet keine Tool-Allow/Deny-Flagform. `-c 'mcp_servers.echo.enabled=false'` verhinderte jede MCP-Verbindung; dies ist nur ein Konfigurations-Disable, kein Vorrangbeweis. | `codex exec --help` bietet kein `--max-turns`; dafür gibt es keine zu behauptende Produktgrenze. |

**Folge:** Der Bau schaltet keinen Provider auf Werkzeugnutzung, solange ein
echter, sicherer Start die jeweilige vollständige Oberfläche und einen
automatisch erlaubten Aufruf nicht belegt. Der aktuelle Codex-Befund endet als
`codex_cli_tool_surface_unverified`. Für Grok bleibt der Anbieter ebenfalls
`grok_cli_tool_surface_unverified`, bis die Allow-Form die beworbenen Builtins
unreachbar macht; die Messung zeigt, dass bloßes Listen der Builtins nicht als
harmlos angenommen werden darf. Es gibt keinen Ersatz über die HTTP-API.

## Ziel und Architektur

- `claude/provider.py` bleibt der alleinige Owner der kanonischen elf
  `mcp__songmaker__*`-Namen. Die bisher private Konstante wird gezielt
  importierbar; ihr Literal und der vorhandene Drift-Test gegen
  `mcp_server/server.py` bleiben bestehen. Adapter führen keine zweite Liste.
- Der bestehende Claude-Gate-Owner wird verallgemeinert, statt Grok und Codex
  eigene Caches oder Sonden zu geben: `_tool_surface_key()` und
  `_verify_tool_surface_async()` parametrisieren auf aufgelösten Binary-Build,
  erwartete Menge, profilierten Probe-Befehl und Parser. Single-flight,
  Symlink-Auflösung, kurzer Probe-Fehler-TTL, langer Zombie-TTL und dauerhafter
  Mismatch-Cache bleiben genau dort. Grok und Codex schreiben
  `_tool_surface_health_state` nicht.
- Die Probe verwendet das Produktionsprofil, Probe-User
  `tool-surface-probe`, keinen Werkzeugaufruf und keine Songdaten. Sie beendet
  nach dem ersten **belegbaren Verbindungsevent**, nicht blind nach der ersten
  Ausgabezeile: Grok sendet nachweislich zwei Builtin-Listen vor seiner
  MCP-Liste. Der Parser hat ein festes kleines Ereignis-/Bytebudget und bleibt
  fail-closed, wenn die Verbindung oder eine vollständige Menge ausbleibt.
  Claude behält seinen bestehenden `read="first_line"`-Pfad. Codex hat nach
  dem gemessenen Stream keinen Namen-Zeugen und bleibt deshalb unverified;
  eine spätere Alternative muss denselben Namen-Zeugen liefern, nicht eine
  zweite, vertrauenswürdige Liste erfinden.
- Nach einer dokumentierten Grok-Normalisierung
  `songmaker__name` → `mcp__songmaker__name` gilt Mengengleichheit mit den
  elf Claude-Namen. Fehlende, zusätzliche oder fremde MCP-Namen sind
  dauerhafter Mismatch. Angezeigte Builtins sind nur dann kein E2-Delta, wenn
  der gemessene Allow-Mechanismus sie tatsächlich unerreichbar macht;
  sie sind nie eine vertrauenswürdige Blocklist.

## Profil, Geheimnisse und Prozessgrenzen

- Ein neues kleines Staging-Modul ist einziger Owner der `0700`-Profile,
  `config.toml`-Formate, Auth-Kopien und des Aufräumens. Es besitzt weder
  Prompt, Spawn noch Event-Parsing.
- Die MCP-Umgebung wird nicht als zweites Zwei-Key-Dict erfunden. Der
  Environment-Teil von Claudes `_build_mcp_config(user_id)` wird in
  `provider.py` als schmaler gemeinsamer Helfer herausgezogen und von
  `_build_mcp_config` sowie dem Stager benutzt. Damit enthält jede
  Registrierung genau `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`,
  `SONGMAKER_INTERNAL_TOKEN` und `SONGMAKER_MCP_USER_ID`; die drei nicht
  benötigten Settings bleiben dort Platzhalter. `DATABASE_URL` steht nie in
  argv, Prozessumgebung, Ereignissen, Logs oder Exceptions.
- Das Staging kopiert das vorhandene, read-only gemountete Auth-Mirror als
  Bytes, setzt danach ausdrücklich `0600` (ein Mount kann `0444` sein) und
  liest keine Felder. Fehlend, unlesbar oder nicht kopierbar ist ein benannter
  CLI-Fehler ohne API-Fallback. Der Mirror bleibt Refresh-Owner und erzeugt
  keine weitere Dauer-Kopie.
- `agent_cli.run_cli_bounded` bleibt einziger Owner von Prozessgruppe,
  Deadline, Output-Limit und Reap. Es erhält nur einen optionalen
  Environment-Overlay über `scrubbed_env()`; ausschließlich `GROK_HOME` bzw.
  `CODEX_HOME` wird ergänzt. Der Stager räumt erst ab, nachdem dieser Owner
  den Prozessbaum gereapt hat, einschließlich seiner Zombie-Behandlung.

## Provider-Vertrag und Ereignisse

- Grok verwendet ausschließlich die gemessene Allow-Form
  `--allow 'MCPTool(songmaker__*)'`; `--deny '*'` ist ausdrücklich verboten,
  weil es Allow überstimmt. `--no-subagents` und `--disable-web-search`
  bleiben. Die Turn-Grenze wird erst nach einer erneuten Messung mit dem
  echten Songmaker-Server auf mindestens zwei festgelegt; `1` ist widerlegt.
  `--always-approve` wird nicht verwendet.
- Codex entfernt `--ignore-user-config` und `mcp_servers={}`, damit das
  gestagte `CODEX_HOME` geladen wird; privater CWD, `--ignore-rules`,
  `--sandbox read-only`, `--ephemeral` und `approval_policy="never"` bleiben.
  Weil diese Form beim Messlauf einen MCP-Aufruf abbrach, ist sie kein
  Aktivierungskriterium. Ohne einen sicheren, dokumentierten Allow-Mechanismus
  bleibt der Adapter fail-closed; der gefährliche Bypass ist keine Option.
- `dispatch.py` gibt `user_id` an beide CLI-Streamer weiter. Ein später
  verifizierter Grok-`tool_call`/`tool_call_update` und Codex-
  `mcp_tool_call` wird auf die bestehenden `ToolCallEvent` und
  `ToolResultEvent` abgebildet, mit kanonischem Namen
  `mcp__songmaker__…`, validierter ID und einer sicheren, begrenzten
  Input-/Output-Darstellung. Groks äußeres `use_tool` wird nur dann als MCP
  erkannt, wenn sein validierter `rawInput.tool_name` normalisiert werden
  kann. Fremde oder unvollständige Ereignisse aborten und reapen ohne
  `FinalEvent`. `execute_cowriter_tool` bleibt ausschließlich HTTP-Executor.
- Ein unverified Gate, eine gestörte Staging-Datei oder ein Streamfehler bleibt
  ein benannter CLI-Fehler: kein HTTP-Wechsel und keine Teilantwort.

## Tests und Abnahme

| Satz | Beweis |
| --- | --- |
| Profil und Geheimnisse | Adapter-/Staging-Tests prüfen `0700`/`0600`, Byte-Kopie der Auth-Datei, komplette MCP-Env aus dem Claude-Owner, weder Geheimnis in argv noch Overlay/Ereignis/Exception und Löschen erst nach Reap. |
| Gemeinsames Gate | `test_claude_provider.py` plus Adaptertests prüfen exakt elf Namen, fehlende/zusätzliche/fremde Namen, keine Verbindung, unparsebare oder budgetüberschreitende Ausgabe, Build-Key, dauerhaften Mismatch-Cache, kurzen Probe-Fehler-TTL, langen Zombie-TTL und Single-flight. Der Serverregistrierungs-Drift-Test bleibt grün. |
| Command-Sätze | `test_grok_cli_adapter.py` ersetzt Pins auf `--deny '*'` und „jedes Werkzeug blockiert“ durch die gemessene Allow-Form, keine Subagents/Web und eine belegte Turn-Grenze. `test_codex_cli_adapter.py` entfernt `--ignore-user-config` und `mcp_servers={}` und prüft das fail-closed Ergebnis bis ein echter Allow-Zeuge existiert. |
| Stream-Sätze | Gefälschte CLIs liefern erlaubte MCP-Start/Update/Resultat-Ereignisse; Tests erwarten passende `ToolCallEvent`/`ToolResultEvent`, Text und genau ein `FinalEvent`. Für fremde/defekte/abgebrochene Folgen erwarten sie benannten Fehler ohne Final. |
| Dispatch und Persistenz | `test_cowriter_dispatch.py` und Conversation-Tests prüfen die `user_id`-Weitergabe, kein CLI→HTTP-Fallback, keine Teilantwort und keine Persistenz nach Fehler. |
| Live-Abnahme | `REQ-COWRITER-12`/`13` bleiben offen, bis der Head nach Deploy den echten Gate-Zeugen und einen erfolgreichen lokalen Werkzeugturn am eigenen Song gefahren hat. Ein Dummy, eine gefälschte CLI oder diese Echo-Messung genügt nicht. |

## Scope, Schnitt zu #524 und bewusst nicht

Die Claim-Verengung umfasst nur
`cowriter/grok_cli_adapter.py`, `cowriter/codex_cli_adapter.py`, das neue
Staging-Modul, `cowriter/dispatch.py` (nur `user_id`), `agent_cli.py` (nur
Environment-Overlay), `claude/provider.py` (kanonische Konstante,
MCP-Env-Helfer und gemeinsames Gate), die zugehörigen Tests sowie die
betroffene Passage in `docs/security.md`. `constants.py`, der übrige
`cowriter/`-Baum und breite `tests`-Claims gehören nicht mehr dazu.

Nicht angefasst werden #524s Katalog, Save, `catalog.py`, `settings_api.py`
und Frontend, außerdem Admin/UI (R2), Codex-Katalog (R5), Judge- oder HTTP-API,
Credential-Refresh/Mirror-Umbau, neue MCP-Serverfunktion und jeder
Song-Schreibtest in dieser Plan-Arbeit.
