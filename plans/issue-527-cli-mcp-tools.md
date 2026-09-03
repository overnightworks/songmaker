# #527 – MCP-Songwerkzeuge in Grok- und Codex-CLI-Turns

**Leser/Entscheidung:** Builder und Reviewer entscheiden, wie die beiden
Subscription-CLI-Wege dieselbe begrenzte Songwerkzeug-Oberfläche wie Claude
erhalten, ohne neue Geheimnis- oder Prozess-Owner. Vertrag: #527; E1 und
R4-Schnitt: #321; Sicherheitsowner: `docs/security.md`.

## Festgelegter Schnitt

- `claude/provider.py` bleibt alleiniger Owner der kanonischen, elf Namen
  `mcp__songmaker__*`. Die bisher private erwartete Menge wird als ausdrücklich
  nutzbare Konstante freigegeben; Grok- und Codex-Gate importieren sie, sie
  schreiben keine zweite Liste. Der vorhandene Drift-Test gegen
  `mcp_server/server.py` bleibt der Beweis für diese eine Wahrheit.
- Ein kleiner gemeinsamer Profil-Staging-Owner für die beiden Adapter erzeugt
  je Turn ein `0700`-Profil und räumt es erst ab, nachdem `run_cli_bounded`
  den vollständigen Prozessbaum gereapt hat. Er besitzt die zwei TOML-Formate,
  aber weder Prompt noch Spawn oder Stream-Parsing.
- Für Grok setzt er `GROK_HOME`, für Codex `CODEX_HOME`. Je Profil schreibt er
  `config.toml` mit Modus `0600`, registriert genau den stdio-Server
  `python -m songmaker_cli.mcp_server` und legt nur dessen nötige
  `DATABASE_URL`- und `SONGMAKER_MCP_USER_ID`-Werte in die Datei. Der
  Geheimniswert steht nie in argv, Ereignis, Log oder Exception.
- Das gesetzte Home verdeckt die Anmeldung. Deshalb kopiert der Owner die
  bereits read-only gemountete, von #350 redigierte `auth.json` in das
  Profil, ebenfalls `0600`; er liest keine Feldwerte und erzeugt keine dritte
  Dauer-Kopie. Der Spiegel bleibt Host-Refresh-Owner und enthält keinen
  Refresh-Token. Fehlendes, unlesbares oder nicht kopierbares Mirror ist ein
  benannter CLI-Fehler, kein API-Fallback innerhalb des Turns.
- `agent_cli.run_cli_bounded` bleibt der einzige Prozess-, Deadline-,
  Output-Limit- und Reap-Owner. Die Adapter liefern ihm Profil-Umgebung,
  privaten Arbeitsordner und ihre vollständige Kommandoform.

## Werkzeug-Gate

- Vor jedem MCP-Turn prüft der jeweilige Adapter den aufgelösten CLI-Build;
  die Probe nutzt dasselbe profilierte MCP-Setup wie der Turn und beendet den
  Prozess nach dem ersten belegbaren Startereignis. Sie ruft nie ein Werkzeug
  auf und benutzt den Probe-User wie Claude.
- Der Parser extrahiert ausschließlich die vom Provider angekündigten
  MCP-Namen, normalisiert eine dokumentierte Grok-`songmaker__name`-Schreibweise
  auf die Claude-Kanonik und vergleicht dann Gleichheit mit der importierten
  Elf-Menge. Fehlend, zusätzlich, fremd, unparsebar oder ohne bestätigte
  MCP-Verbindung ist fail-closed. Ein echter Mismatch bleibt je aufgelöstem
  Build dauerhaft gecacht; ein nicht beurteilbarer Probe-Fehler erhält nur den
  vorhandenen kurzen Fehler-TTL. Single-flight, Symlink-Auflösung und
  Zombie-Behandlung folgen dem Claude-Gate, nicht einer neuen Parallel-Logik.
- Das reale Ereignisprotokoll ist vor dem Bau nochmals zu bezeugen: Der
  04.09.-Dummyversuch meldete bei Grok nur `available_commands` mit eingebauten
  Werkzeugen und bei Codex nur Thread-/Turn-Lebenszyklus. Er bezeugt daher
  weder eine Elf-Liste noch eine Verbindungsbestätigung. Fehlt nach einem
  harmlosen, echten MCP-Start weiterhin ein solcher Zeuge, endet die Arbeit
  fail-closed als `*_cli_tool_surface_unverified`; kein Test oder Requirement
  behauptet dann Fähigkeiten, die die CLI nicht meldet.

## Kommando- und Ereignisvertrag

- Grok nutzt die gemessene `--allow 'MCPTool(songmaker__*)'`-Form, einen
  einzelnen Turn, keine Subagents und kein Web. Die Blocklist wird anhand der
  realen Vorrangregeln geprüft: `--deny '*'` darf die Allowlist nicht selbst
  überstimmen. Eingebaute Werkzeuge sind über die CLI-native Allow/Tools-Form
  abwesend oder verboten; eine spätere fremde Ankündigung ist trotzdem Gate-
  Mismatch, nie eine vertrauenswürdige Blocklist-Behauptung.
- Codex lädt nur das gestagte `CODEX_HOME` (also kein
  `--ignore-user-config` und kein `mcp_servers={}`), behält `--ignore-rules`,
  privaten CWD, `--sandbox read-only`, `--ephemeral` und
  `approval_policy="never"`. Der Builder belegt die Codex-spezifische
  MCP-Approval-Form vor dem Umschalten; `never` bedeutet nur automatische
  Entscheidung, nicht Werkzeuglosigkeit.
- Grok mappt `tool_call` und `tool_call_update` mit validierter ID, Name,
  Status sowie sicherer Input-/Output-Darstellung auf die vorhandenen
  `ToolCallEvent`/`ToolResultEvent`-Chat-Ereignisse. Codex mappt seine
  `mcp_tool_call`-Item-Lebenszyklen äquivalent. Der Claude-Adapter ist der
  Vergleichsowner für Reihenfolge, finale Antwort und Fehlerverhalten; rohe
  Tool-Nutzlasten, Prompts und stderr werden nicht geloggt.
- Ein unbekanntes, unvollständiges oder außerhalb der elf Namen liegendes
  Werkzeugereignis bricht ab, reapt und liefert keinen `FinalEvent`.

## Tests und Abnahme

- Adapter-Tests mit gefälschter CLI beweisen je Provider: exakte Staging-Dateien
  und `0600`, redigierte Auth-Kopie, Aufräumen erst nach Reap, richtige
  Umgebung/Argumente und keine Geheimnisse im beobachtbaren Aufruf.
- Sie beweisen das Gate: erste gültige Oberfläche, fehlendes/zusätzliches/fremdes
  Werkzeug, fehlende Verbindung, unparsebares Ereignis, Dauer-Cache pro Build
  und wiederholbarer Probe-Fehler. Eine Änderung der Serverregistrierung lässt
  weiterhin den gemeinsamen Elf-Namen-Test scheitern.
- Stream-Tests pinnen die erlaubten Tool-Start/-Update/-Resultat-Ereignisse als
  Chat-Ereignisse, Text plus genau ein Final, und jeden fremden/defekten Ablauf
  als benannten Fehler ohne Final. Dispatch- und Conversation-Tests sichern,
  dass kein CLI-Fehler in HTTP wechselt und keine Teilantwort persistiert wird.
- `REQ-COWRITER-12` und `REQ-COWRITER-13` werden nur dann als erfüllt markiert,
  wenn der echte Gate-Zeuge und ein nach Deploy vom Head gefahrener Grok-Turn
  ein Werkzeug am eigenen Song erfolgreich nutzt. Andernfalls bleiben sie
  ausdrücklich offen; ein Dummy-Listing oder eine gefälschte CLI genügt nicht.

## Bewusst nicht

Kein Admin-Schalter/UI (R2), kein Codex-CLI-Katalog (R5), keine Judge- oder
HTTP-API-Änderung, kein Credential-Refresh/Mirror-Umbau, keine neue MCP-
Serverfunktion, keine Songdaten im Probeweg und kein Live-Song-Schreibtest
durch diesen Plan-Task.
