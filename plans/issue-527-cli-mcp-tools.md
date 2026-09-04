# #527 – MCP-Songwerkzeuge in Grok- und Codex-CLI-Turns

**Leser/Entscheidung:** Builder und Reviewer entscheiden, ob ein
Subscription-CLI-Turn dieselbe begrenzte Songwerkzeug-Oberfläche wie Claude
sicher erreichen kann. Vertrag: #527; E1 und R4-Schnitt: #321;
Sicherheitsowner: `docs/security.md`.

## Ergebnis des Host-Experiments vom 04.09.2026

Das Experiment lief mit einem wegwerfbaren, lokalen stdio-MCP-Server `echo`;
er kennt genau dieses Werkzeug, keine Datenbank und keine Songdaten. Jedes
Profil war `0700`; die Auth-Datei wurde byteweise kopiert und auf `0600`
gesetzt. Zugangsdaten und Werkzeug-Nutzlasten gehören weder in diesen Plan
noch in Logs.

Grok nutzte dieselbe Prompt-Übergabe wie der Produktionsadapter:

```text
GROK_HOME=<tmp>/grok grok mcp add echo -- /usr/bin/python3 <echo-server>
GROK_HOME=<tmp>/grok grok --prompt-file <prompt-file> \
  --output-format streaming-json --allow 'MCPTool(echo__*)' --max-turns <n> \
  --no-subagents --disable-web-search
```

Grok 1.0.5 meldete dreimal dieselben 25 Builtins:
`run_terminal_command`, `read_file`, `search_replace`, `list_dir`, `grep`,
`kill_command_or_subagent`, `todo_write`,
`get_command_or_subagent_output`, `spawn_subagent`, `scheduler_create`,
`scheduler_delete`, `scheduler_list`, `monitor`, `search_tool`, `use_tool`,
`workflow`, `enter_plan_mode`, `exit_plan_mode`, `ask_user_question`,
`image_gen`, `image_edit`, `image_to_video`, `reference_to_video` und
`write`, außerdem eine nichtleere Slash-Command-Liste. Erst nach
`initialize`, `notifications/initialized` und `tools/list` erschien
`echo__echo`; der äußere Aufruf ist `tool_call` `use_tool` mit
`rawInput.tool_name = "echo__echo"`.

| geprüfte Form | Ergebnis |
| --- | --- |
| Nur `--allow 'MCPTool(echo__*)'` mit `--prompt-file` | Der Turn führte zuerst `search_tool` `completed` aus, dann `echo__echo` `completed`; bei `--max-turns 2` kam `max_turns_reached`/`end.cancelled`, kein Final. Allow begrenzt Builtins nicht. |
| `--deny read_file` | `read_file` blieb sichtbar und der erzwungene Aufruf auf `/dev/null` wurde `completed`: der rohe Ereignisname ist keine Grok-Regelsyntax. |
| `--deny Read` | Die Builtin-Liste blieb sichtbar; derselbe Aufruf wurde als `tool_call_update` `failed` mit „Denied by permission policy: deny rule on read“ beendet. Die Regelklasse blockiert Ausführung, nicht die Anzeige. |
| `--disallowed-tools <alle 25 Namen>` | 21 Namen verschwanden; `run_terminal_command`, `kill_command_or_subagent`, `get_command_or_subagent_output` und `spawn_subagent` blieben. Statt `read_file` lief danach `run_terminal_command` mit `cat /dev/null` `completed`. Die Namens-Deny ist nicht vollständig. |
| Codex 0.147.0, `approval_policy="never"` | `thread.started`, `turn.started`, serverseitig `initialize`/`tools/list`, aber keine Namen im JSON-Stream. Der MCP-Aufruf endete ohne Prompt als „user cancelled MCP tool call“, ohne `tools/call`. `codex exec --help` bietet weder Tool-Allow/Deny noch `--max-turns` oder `--prompt-file`; der Produktionsadapter verwendet deshalb wie das Experiment stdin über `-`. |

**Folge:** Die aktuelle Grok-Messung widerlegt eine aktivierbare explizite
Builtin-Deny: weder rohe Namen noch `--disallowed-tools` erzwingen sie
vollständig, und der erlaubte Echo-Turn führt vorher ein Builtin aus. Codex
liefert weder Namen-Zeugen noch Deny-Form. Beide Adapter bleiben darum
`*_cli_tool_surface_unverified`; es gibt keinen HTTP-Ersatz. Ein späterer
CLI-Build darf erst nach allen unten genannten Host-Zeugen aktiviert werden.

## Ziel und Architektur

- `claude/provider.py` bleibt der alleinige Owner der kanonischen elf
  `mcp__songmaker__*`-Namen. Die bisher private Konstante wird gezielt
  importierbar; ihr Literal und der vorhandene Drift-Test gegen
  `mcp_server/server.py` bleiben bestehen. Adapter führen keine zweite Liste.
- `grok_cli_adapter.py` besitzt mit Kommentar „Owner: Grok-CLI-Adapter,
  gemessen 2026-09-04, Grok 1.0.5“ genau eine benannte
  `GROK_1_0_5_BUILTIN_DENY_NAMES`-Konstante mit den oben gemessenen 25
  Ereignisnamen. `codex_cli_adapter.py` besitzt analog
  `CODEX_0_147_0_BUILTIN_DENY_NAMES = frozenset()` mit dem Kommentar, dass
  Codex 0.147.0 keinen Namen-Zeugen und keine Deny-Form liefert. Leer heißt
  nicht erlaubt: Der Codex-Gate kann damit nie einen unbekannten Builtin
  akzeptieren. Die Adapter übergeben diese Mengen nur an das gemeinsame Gate;
  sie duplizieren weder die elf MCP-Namen noch Caches.
- Der bestehende Claude-Gate-Owner wird verallgemeinert, statt Grok und Codex
  eigene Caches oder Sonden zu geben: `_tool_surface_key()` und
  `_verify_tool_surface_async()` parametrisieren auf aufgelösten Binary-Build,
  erwartete MCP-Menge, benannte Builtin-Deny-Menge, profilierten Probe-Befehl
  und Parser. Single-flight,
  Symlink-Auflösung, kurzer Probe-Fehler-TTL, langer Zombie-TTL und dauerhafter
  Mismatch-Cache bleiben genau dort. Grok und Codex schreiben
  `_tool_surface_health_state` nicht.
- Die Probe verwendet das Produktionsprofil, Probe-User
  `tool-surface-probe`, keinen Werkzeugaufruf und keine Songdaten. Sie beendet
  nach dem vollständigen **belegbaren** `available_commands`-Zeugen, nicht
  nach der ersten Ausgabezeile: Grok sendet Builtin-Listen vor der MCP-Liste.
  Der Parser hat ein festes kleines Ereignis-/Bytebudget und bleibt fail-closed,
  wenn die Verbindung oder eine vollständige Menge ausbleibt. Claude behält
  seinen bestehenden `read="first_line"`-Pfad. Codex hat nach dem gemessenen
  Stream keinen Namen-Zeugen und bleibt deshalb unverified; eine spätere
  Alternative muss denselben Namen-Zeugen liefern, nicht eine zweite,
  vertrauenswürdige Liste erfinden.
- Nach einer dokumentierten Grok-Normalisierung
  `songmaker__name` → `mcp__songmaker__name` gilt Mengengleichheit mit den
  elf Claude-Namen. Das Gate akzeptiert pro Build genau dann, wenn diese Menge
  exakt ist **und** jeder gemeldete Nicht-MCP-Toolname in der übergebenen
  Deny-Menge steht; ein fehlender, zusätzlicher oder unbekannter Builtin ist
  dauerhafter Mismatch und verweigert den Turn. Eine nichtleere
  Slash-Command-Liste ist ebenfalls dauerhafter Mismatch, bis eine gemessene,
  vollständige Deny dafür vorliegt. Mitgliedschaft in der Liste genügt nicht
  zur Aktivierung: Die aktuelle Grok-Liste bleibt absichtlich unverified, weil
  ihre vollständige Ausführungs-Deny widerlegt ist. So wird aus einer
  beobachteten Liste keine vertrauenswürdige Blocklist.

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

- Groks Produktions- **und** Probe-argv verwenden ausschließlich
  `--prompt-file <songmaker-private-prompt>`, `--allow
  'MCPTool(songmaker__*)'`, die aus der benannten Deny-Konstante ableitbaren,
  dokumentierten `--deny`-Regeln, `--no-subagents` und
  `--disable-web-search`; `--single`, `--tools ''`, `--deny '*'` und
  `--always-approve` sind verboten. Die Roh-Namen selbst werden nicht als
  Regel ausgegeben, weil `--deny read_file` unwirksam gemessen ist. Für 1.0.5
  gibt es keine vollständige Übersetzung mit einem `failed`-Pin für alle 25
  Namen; der Gate verweigert daher jeden Grok-Turn, statt eine geschätzte
  Turn-Grenze zu setzen. Erst ein neuer Host-Zeuge darf eine Grenze und eine
  aktivierbare Deny-Übersetzung festlegen.
- Codex entfernt `--ignore-user-config` und `mcp_servers={}`, damit das
  gestagte `CODEX_HOME` geladen wird; privater CWD, `--ignore-rules`,
  `--sandbox read-only`, `--ephemeral` und `approval_policy="never"` bleiben.
  Sein Produktions- und Experiment-argv bleiben identisch und reichen den
  Prompt über stdin an `-`; eine Prompt-Datei-Unterstützung gibt es nicht.
  Weil diese Form den MCP-Aufruf abbrach und kein Allow/Deny-Mechanismus
  existiert, ist sie kein Aktivierungskriterium. Ohne Namen-Zeugen und sicheren
  Deny bleibt der Adapter fail-closed; der gefährliche Bypass ist keine Option.
- `dispatch.py` gibt `user_id` an beide CLI-Streamer weiter. Ein später
  verifizierter Grok-`tool_call`/`tool_call_update` und Codex-
  `mcp_tool_call` wird auf die bestehenden `ToolCallEvent` und
  `ToolResultEvent` abgebildet, mit kanonischem Namen
  `mcp__songmaker__…`, validierter ID und einer sicheren, begrenzten
  Input-/Output-Darstellung. Das Stream-Gate bricht bei **jedem** Grok-
  `tool_call` ausserhalb `mcp__songmaker__*` sofort ab: Nur `use_tool` mit
  gültigem `rawInput.tool_name`, das zu einem kanonischen Songmaker-Namen
  normalisiert, darf weiter. Jeder Builtin-Aufruf (auch ein bereits `failed`
  Deny-Aufruf), eine fremde MCP-Nennung oder ein unvollständiges Folgeereignis
  fordert Abort an, wartet auf den Reap des Bounded-Runners und emittiert kein
  `FinalEvent`. Für Codex gilt dieselbe Regel für jedes andere Tool-Item.
  `execute_cowriter_tool` bleibt ausschließlich HTTP-Executor.
- Ein unverified Gate, eine gestörte Staging-Datei oder ein Streamfehler bleibt
  ein benannter CLI-Fehler: kein HTTP-Wechsel und keine Teilantwort.

## Tests und Abnahme

| Satz | Beweis |
| --- | --- |
| Profil und Geheimnisse | Adapter-/Staging-Tests prüfen `0700`/`0600`, Byte-Kopie der Auth-Datei, komplette MCP-Env aus dem Claude-Owner, weder Geheimnis in argv noch Overlay/Ereignis/Exception und Löschen erst nach Reap. |
| Gemeinsames Gate | `test_claude_provider.py` plus Adaptertests prüfen exakt elf Namen sowie: jeder gemeldete Nicht-MCP-Toolname steht in der Provider-Parameter-Deny-Menge; fehlende, zusätzliche oder unbekannte Namen und jede Slash-Command-Liste sind dauerhafter Mismatch. Ferner: keine Verbindung, unparsebare oder budgetüberschreitende Ausgabe, Build-Key, Mismatch-Cache, Probe-Fehler-/Zombie-TTL und Single-flight. Der Serverregistrierungs-Drift-Test bleibt grün. |
| Command-Sätze | `test_grok_cli_adapter.py` pinnt die 25-namige, datierte Deny-Konstante, ausschließlich `MCPTool(songmaker__*)`, `--prompt-file` für Produktion und Probe sowie keine verbotenen Flags. Es pinnt die dokumentierte Regelübersetzung separat von der Namensliste: ein erzwungener `Read`-Builtin wird `failed`; ein nicht übersetzbarer oder unbelegter Name hält den Gate unverified. `test_codex_cli_adapter.py` pinnt `approval_policy="never"`, stdin-`-`, die leere datierte Deny-Konstante, kein `--ignore-user-config`/`mcp_servers={}` und das fail-closed Ergebnis. |
| Stream-Sätze | Gefälschte CLIs liefern erlaubte MCP-Start/Update/Resultat-Ereignisse; Tests erwarten passende `ToolCallEvent`/`ToolResultEvent`, Text und genau ein `FinalEvent`. Ein Builtin-`tool_call` mit `completed` **oder** `failed`, eine fremde MCP-Nennung oder eine defekte Folge erwartet Abort, Reap und keinen Final. |
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
