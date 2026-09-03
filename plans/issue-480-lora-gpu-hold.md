# #480 — GPU-Hold während LoRA-Training

Entscheidung: Ein ACE-Step-Worker lässt LoRA erst nach seinen bereits
zugelassenen Generierungen exklusiv trainieren. Während des Holds bleibt jede
nicht zugelassene Generierung ehrlich `queued`; sie teilt weder GPU noch
ARQ-Slot mit dem Training.

## Grenzen und belegte Ausgangslage

- Redis ist Owner der Occupancy. Der neue Hold ist
  `songmaker:acestep:hold:{worker_id}`; Heartbeat, `/loaded_models`, Admin und
  UI sind ausschließlich Projektionen. Kein Flag im Heartbeat-JSON und kein
  fusionierter Queue-/Hold-Key: `publish_once()` überschreibt das JSON alle 5 s
  (`src/acestep_worker/heartbeat.py:54-58`), der Queue-Key ist ein Integer
  ohne TTL (`src/songmaker_cli/acestep_state.py:76-87`).
- Es gibt keinen zweiten Reaper und keine S3-Timeränderung. Der einzige
  periodische Job-Reaper ist `stale_job_reaper_loop`
  (`src/songmaker_cli/lifecycle.py:434-437`); `ModelCache.acquire_for_use()`
  bleibt allein Eviction-Schutz (`src/acestep_worker/model_cache.py:208-215`).
- S4a baut nach #479, weil es dessen stabilen LoRA-Langläufervertrag konsumiert,
  ohne Zeitgrenzen, Heartbeat-Kadenz oder Epochen zu kopieren. S4b baut nach
  S4a und #481, weil #481 die Queued-Flächen in `SongDetailView`/`TakesList`
  verändert; es übernimmt deren gelandete Beschriftung statt sie zu duplizieren.

### Korrekturen gegen den heutigen Code

- **Kein Online-Worker ist nicht „alle gehalten“.**
  `scheduler._pick_from()` wirft bei einer leeren Liste `NoCapacityError`
  (`src/songmaker_cli/scheduler.py:167-172`), und
  `run_generation_job()` sammelt diesen Fehler heute als fehlgeschlagenen
  Versuch (`src/songmaker_cli/jobs/generation.py:736-780`). Der neue Picker
  muss daher erst die ungekürzte Online-Liste prüfen: nur ihre Leere bleibt
  `NoCapacityError`; eine nichtleere Liste, aus der der Hold-Filter alle
  Kandidaten entfernt, liefert den eigenen, nichtfehlerhaften
  `AllWorkersHeld`-Ausgang. Damit wird eine gehaltene Ein-GPU nicht als
  offline oder als fehlgeschlagene Generation fehlinterpretiert.
- **Der Reserve-Token muss die tatsächlichen Phasen überleben.**
  LoRA ruft heute nach `pick_worker()` `/load_model` mit
  `DispatchOptions.load_model_timeout_seconds` auf
  (`src/songmaker_cli/jobs/lora_training.py:129-140`); dieser Wert ist 600 s
  (`src/songmaker_cli/constants.py:405`) und der gegenwärtige Request trägt
  keinen Token. `HeartbeatLoop.publish_once()` schreibt nur das Worker-JSON
  alle fünf Sekunden (`src/acestep_worker/heartbeat.py:54-70`) und darf deshalb
  keinen Hold verlängern: das hielte einen Hold auch ohne gebundenen Job am
  Leben. Die Renewal-Handover unten läuft parallel zum Load und endet am
  gebundenen Worker-Task, nicht am Heartbeat.
- **Warten ist ein neuer ARQ-Umschlag, kein Retry und kein Poll im Slot.**
  `MusicWorkerSettings` registriert die beiden Funktionen ohne eigenes
  `max_tries` (`src/songmaker_cli/music_worker.py:139-143`); ARQs
  Worker-Default ist fünf Versuche. `arq.Retry` wäre also nach fünf
  5-s-Polls terminal. `ArqRedis.enqueue_job(..., _defer_by=...)` legt dagegen
  einen neuen Umschlag mit einer neuen ARQ-ID an (ARQ 0.27,
  `arq/connections.py:119-171`) und die laufende Funktion kann zurückkehren.
  Das ist nötig, weil LoRA heute noch vor jeder Workerwahl `RUNNING` setzt und
  den Dataset-Ordner materialisiert (`lora_training.py:424-455`).

- **Ein Generate-Job kann mehrere Takes umfassen.** `GenerateRequest.count` ist
  auf 1–10 begrenzt (`src/songmaker_cli/api_models/songs.py:557-560`). S4a
  admittiert deshalb genau einmal atomar vor dem Aufbau und hält diese
  Occupancy für die ganze Take-Serie; der finale Cleanup macht einmal `DECR`.
  Zwischen Takes gibt es kein `DECR`. Ein Hold-/Admit-409 vor dem ersten
  `RUNNING` ist ein nichtfehlerhafter Defer mit DB-Status `queued` und neuem
  ARQ-Umschlag; nach erfolgreichem Serien-Admit kann dieser Konflikt innerhalb
  des Jobs nicht mehr auftreten.

## S4a — Redis-Occupancy, Hold und Scheduling

### Vertrag

LoRA-Reserve gelingt nur, wenn der Queue-Zähler des gewählten Workers 0 ist
und im Reserve-Zeitpunkt keine Generierung im Zustand `QUEUED` in der DB
wartet. Die DB-Zähl-Query gehört unmittelbar vor den Reserve-Aufruf; eine
danach eintreffende Generierung trifft den Hold und wartet ohnehin dahinter.

1. Reserve gewinnt nur atomar, wenn der Queue-Zähler des Workers fehlt oder 0
   und kein Hold besteht. Admit gewinnt nur atomar, wenn kein Hold besteht;
   es erhöht dann den Queue-Zähler. Zwei konkurrierende Aufrufe können nicht
   beide gewinnen.
2. `POST /gpu_hold/reserve` liefert `{token}` oder 409; `renew` und `release`
   akzeptieren nur denselben Token. Der Hold-Key enthält den nicht erratbaren
   Token und heißt `songmaker:acestep:hold:{worker_id}`. Er hat
   `EX = HeartbeatLoop`-TTL (heute 15 s), und jede Erneuerung hat
   die bestehende 5-s-Heartbeat-Kadenz (also strikt unter TTL).
3. Nach einem erfolgreichen Reserve startet der LoRA-Job sofort einen eigenen
   Renewal-Task mit der 5-s-Kadenz und hält ihn **parallel** über
   `/load_model` (bis 600 s) und bis das Worker-`/tasks/train_lora` den
   Token angenommen hat. `TrainLoraRequest.hold_token` ist Pflicht: der
   Endpoint vergleicht ihn mit dem Hold-Key und startet vor seiner erfolgreichen
   Antwort den tokengebundenen Worker-Renewal-Task. Erst diese Antwort ist die
   Handover-Grenze; danach beendet der Job seinen Renewal-Task. Verliert der
   Job die Submit-Antwort, fragt er den internen Handover-Status ab und folgt
   mit dessen Task-ID demselben Training statt einen möglicherweise laufenden
   Worker-Task als fehlgeschlagen zu markieren. Der Worker
   erneuert ausschließlich während seines gebundenen `train_lora`-Tasks und
   gibt im selben `finally` tokengebunden frei. Weder `HeartbeatLoop` noch
   `/load_model` erneuert. Stirbt der Job vor der Handover-Antwort, endet sein
   Task und die TTL läuft aus; nach dem Handover ist nur der tatsächlich
   laufende Worker-Task Owner und räumt im `finally`. Jeder Token-Mismatch/409
   beendet den betreffenden Ablauf statt still weiterzulaufen. Ein alter Token
   nach Restart darf weder renewen noch Training starten; Worker-Startup löscht
   Queue- **und** Hold-Key; `/generate` liefert bei Hold 409.
4. LoRA prüft vor jedem Anlauf nur Online-/Hold-Ausgang und Lua-Reserve. Bei
   `AllWorkersHeld` oder Reserve-409 bleibt der DB-Job `queued`, setzt weder
   `RUNNING` noch LoRA-Status noch Dataset-Kopie, und legt einen neuen
   Musik-Queue-Umschlag mit denselben Funktionsargumenten, ohne `_job_id`, über
   `enqueue_job(..., _queue_name=ARQ_MUSIC_QUEUE_NAME,
   _defer_by=GPU_HOLD_POLL_INTERVAL_SECONDS)` an; dann kehrt sie zurück.
   Dieser slotfreie Pass wartet höchstens bis
   `STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].queued_seconds`; danach schlägt
   er ohne Lease mit `Generation queue did not drain before LoRA training could
   start` fehl. Erst nach gewonnenem Reserve folgen `RUNNING`, Materialisierung,
   Load und Training. Es gibt weder `asyncio.sleep` im ARQ-Job noch `arq.Retry`;
   dadurch kann ein 1100-s-Drain weder `music_max_jobs`/`arq_job_timeout`
   belegen noch am ARQ-Default `max_tries=5` sterben.
5. `pick_worker` unterscheidet anhand der ungekürzten Online-Liste
   `NoCapacityError` von `AllWorkersHeld`; erst danach filtert er den
   Redis-Hold-Key, nicht den 5-s-Heartbeat-Spiegel. Freie Online-Worker gehen
   vor. Der neue All-held-Ausgang setzt niemals einen Fehler; er führt in den
   Defer-Pfad. Der Wait-Pfad setzt `Job.queue_reason` auf `Waiting for LoRA
   training on this GPU.` und löscht ihn bei Admit, echtem Fehler oder Cancel.
6. Generate wählt/admittiert **einmal pro Job** vor dem heutigen ersten
   `_update_job(..., RUNNING)` in `run_generation_job()` und vor dem
   arbeitsintensiven Aufbau. Der atomare Lua-Admit erhöht die Queue-Occupancy
   einmal vor dem `for i in range(count)`-Loop; dieselbe Occupancy bleibt für
   alle Takes bestehen und wird im finalen Cleanup erst nach dem letzten Take
   bzw. bei Abbruch einmalig freigegeben. Es gibt kein `DECR` zwischen Takes,
   sodass ein gleichzeitig wartendes LoRA-Training nicht zwischen Take 1 und
   Take 2 reservieren kann. `AllWorkersHeld` oder ein Lua-Admit-409 **vor dem
   ersten `RUNNING`** setzt den Grund, enqueuet `JobFunction.GENERATE` mit den
   vollständigen ursprünglichen Argumenten und
   `_queue_name=ARQ_MUSIC_QUEUE_NAME,
   _defer_by=GPU_HOLD_POLL_INTERVAL_SECONDS` (ohne `_job_id`) und kehrt
   nichtfehlerhaft zurück; der DB-Job bleibt `queued`. Nach erfolgreichem
   Serien-Admit kann ein Admit-Konflikt im selben Job nicht mehr auftreten.
   Ein wirklich leerer Online-Pool folgt weiterhin dem bestehenden
   `NoCapacityError`-Fehlerpfad. `music_max_jobs` und `arq_job_timeout` gelten
   damit nur für echte Arbeit, nicht für Hold-Warten.

### Dateien und Umsetzung

- `src/songmaker_cli/acestep_state.py`, `scheduler.py`: gleicher Lua-Text über
  Queue- und Hold-Key für Admit/Reserve/Renew/Release; Scheduler ist Zulasser,
  kein Hold-Owner. `pick_worker` erhält den ausdrücklichen
  `AllWorkersHeld`-Ausgang, nachdem er die volle Online-Liste gegen
  `NoCapacityError` abgegrenzt und erst dann Redis-Holds gefiltert hat.
  `dispatch_generation` wird in Auswahl/Lua-Admit und die Arbeit auf dem
  bereits zugelassenen Worker getrennt, damit das heutige unbedingte
  `pick_worker(); incr_queue_depth()` (`scheduler.py:437-440`) nicht am Hold
  vorbei erhöht. Ein Gleichheitstest sichert den paketübergreifenden
  Key-/Script-Vertrag.
- `src/acestep_worker/heartbeat.py`, `wrapper.py`, `models.py`: Hold-Key,
  Reserve/Renew/Release-Endpoints, tokengebundenes `train_lora`, 409-Generate,
  Startup-DEL und Worker-Renewal nur während des gebundenen Tasks.
- `src/songmaker_cli/jobs/lora_training.py`, `jobs/generation.py`,
  `music_worker.py`, `constants.py`: `GPU_HOLD_POLL_INTERVAL_SECONDS = 5`
  Sekunden wird als Konstante im `constants.py`-Owner definiert (belegt durch
  die 5-s-Heartbeat-Kadenz); queued Drain und Generate-Defer als
  frische `enqueue_job(..., _defer_by=...)`-Umschläge, nie als `Retry`;
  Token-Handover mit parallelem Job-Renewal über `load_model`, Worker-Renewal
  nur für den gebundenen Train-Task, und Admit-vor-RUNNING. Generate hält eine
  Queue-Occupancy über die ganze `count`-Serie und gibt sie nur im finalen
  Cleanup frei; ein Admit-409 vor RUNNING ist ein Defer. Der LoRA-Defer ist
  vor der heutigen `_update_job(..., RUNNING)` und `_materialize_dataset`, der
  Generate-Defer vor der heutigen Zeile 701; #479s eigene Uhren bleiben dort.
- `src/songmaker_cli/db/models.py`, `db/migrations/versions/*`,
  `db/queries/jobs.py`, `api_models/__init__.py` und `scripts/generate_types.py`:
  nullable `Job.queue_reason`, Migration, `JobResponse` und Frontend-Typ.
- `docs/acestep.md`: Redis-Tabelle ergänzt Hold-Key und 15-s-TTL: Worker/HTTP
  mutiert allein den Hold, der Scheduler führt den Generate-Admit aus und
  mutiert damit den Queue-Zähler. `docs/architecture.md`: Generate-Flow sagt:
  Lua-Admit führt INCR atomar aus; Hold → queued Defer, erst danach RUNNING.

### Tests und Done when

- `tests/test_acestep_state.py` und `tests/test_scheduler.py`: Occupancy gegen
  `fakeredis`/`eval`, nicht gegen das eval-lose `_InMemoryRedis`: beide
  Rennreihenfolgen, Token-Mismatch, TTL, Multi-Worker-Skip und kein INCR bei
  Hold. Ein Online-Pool ohne Worker bleibt `NoCapacityError`; ein einziger
  online gehaltener Worker liefert `AllWorkersHeld`, nicht den Fehler.
- `tests/test_acestep_worker_train_lora.py`, `tests/acestep_worker/test_heartbeat.py`
  und `test_wrapper.py`: Reserve/Renew/Release, Startup-DEL, alter Token,
  `/generate` 409 sowie Release bei Erfolg, Fehler und Cancel. Ein kontrolliert
  langsames `/load_model` beweist dabei parallele Job-Renews über mehr als eine
  Hold-TTL; `publish_once()` verlängert keinen Hold, und der Worker beginnt und
  beendet seinen Renewal-Task ausschließlich mit `train_lora`.
- `tests/test_jobs_lora_training.py`, `tests/test_jobs.py`,
  `test_lifecycle_job_reaper.py` und `test_music_worker.py`: ein Defer-Pass
  enqueuet mit `_defer_by`, ohne `_job_id`, kehrt zurück und materialisiert
  nichts. Eine logisch wiederholte 1100-s-Drain-Sequenz beweist weder
  `asyncio.sleep` noch `Retry`, keinen belegten ARQ-Slot und keinen
  `arq_job_timeout`/`max_tries`-Abbruch. Der Ein-GPU-Hold lässt Generate
  `queued` (nicht `FAILED`) und startet sie nach Release; beide Jobarten werden
  erst nach erfolgreichem Admit/Reserve `RUNNING`. Ein Job mit `count=3` hält
  dabei eine einzige Queue-Occupancy vom Serien-Admit bis zum finalen Cleanup:
  ein gleichzeitig wartendes Training wird zwischen den Takes nicht
  zugelassen und startet erst nach dem dritten Take. Ein Lua-Admit-409 vor dem
  ersten `RUNNING` bleibt ebenfalls `queued` und erzeugt einen neuen Defer-
  Umschlag statt `FAILED`/`PARTIAL`.
- Done when: alle sechs Vertragssätze, einschließlich Ein-GPU-Fall, sind an
  realen Grenzstellen bewiesen; der Reaper, `worker_liveness.py`, Cache-Schutz
  und #479s Konfiguration sind unverändert.

## S4b — Sichtbarkeit ist eine Projektion

### Vertrag

1. Der Job-Stream liefert bei jedem sichtbaren Wechsel `queue_reason` **und**
   `queue_position`; ein Grundwechsel bei weiterem `queued` wird emittiert.
2. `SongDetailView` zeigt den Grund neben dem gelandeten Queued-Label und der
   Position, niemals als Fehler. Ein gehaltener Worker bleibt online; das
   Pool-/Admin-Bild sagt Hold/LoRA-Training statt fälschlich Idle.
3. Keine Sichtbarkeitsfläche schreibt, verlängert oder räumt Redis. Fehlt die
   Projektion, bleibt die Redis-Entscheidung korrekt.

### Dateien und Umsetzung

- `src/songmaker_cli/jobs_api.py`, `api_models/__init__.py`,
  `db/queries/jobs.py`, `scripts/generate_types.py`: Stream-Snapshot trägt
  Position und Grund, und dessen Dirty-Check beobachtet beide Felder.
- `frontend/src/lib/components/SongDetailView.svelte`,
  `editor/TakesList.svelte` und ihre Tests: Queued-Grund neben Label/Position.
- `src/acestep_worker/wrapper.py`, `src/songmaker_cli/api_models/workers.py`,
  `admin_api.py`, `frontend/src/lib/components/WorkerPoolPanel.svelte` und
  Tests: `training_hold` nur spiegeln; `_derive_worker_status` bleibt online.
- `docs/acestep.md`: Redis-Tabelle kennzeichnet Heartbeat/Admin als
  Hold-Projektion. `docs/architecture.md`: Generate-Flow unterscheidet Redis-
  Entscheidung von Stream/UI-Projektion.

### Tests und Done when

- `tests/test_jobs_api.py` beweist Position+Grund im initialen und folgenden
  SSE-Ereignis ohne Statuswechsel; `tests/test_generate_types.py` sichert den
  generierten Vertrag.
- `SongDetailView.test.ts`, `TakesList.test.ts`, `WorkerPoolPanel.test.ts` und
  Worker/Admin-Tests beweisen Queued-Text, Position, Hold statt Idle und online
  statt offline.
- Done when: ein Ein-GPU-Hold ist über Stream, Song-Detail und Pool/Admin
  ehrlich sichtbar, während S4a weiterhin allein die Redis-Wahrheit besitzt.

## Review-Auflösung 1–10

1. Einarbeitet: Zwei-Key-Lua, Token/TTL und kein JSON-/Key-Merge (S4a 1–2).
2. Einarbeitet: Reserve/Renew/Release, Token-Prüfung, 409 und Startup-DEL (S4a 3).
3. Einarbeitet: Load-paralleles Job-Renew, tokengeprüftes Handover und nur
   taskgebundenes Worker-Renew; `HeartbeatLoop` bleibt ohne Hold-Mutation (S4a 3).
4. Einarbeitet: frischer slotfreier ARQ-Umschlag mit `_defer_by`, nie `Retry`,
   und RUNNING nach Admit/Reserve (S4a 4, 6).
5. Einarbeitet: queued LoRA-Drain ohne Dataset-Kopie, ARQ-Slot oder S3-Uhr;
   die vorhandene Grenze bleibt Owner (S4a 4).
6. Einarbeitet: persistenter einzelner Owner `Job.queue_reason` und Stream/UI (S4a 5; S4b 1–2).
7. Einarbeitet: Redis-Hold-Filter mit getrenntem `AllWorkersHeld`-/
   `NoCapacityError`-Ausgang, Ein-GPU- und Admin-Projektion (S4a 5; S4b 2).
8. Einarbeitet: fakeredis/eval- und Lifecycle-/Defer-Testmatrix (S4a Tests).
9. Einarbeitet: beide genannten Doku-Deltas je Scheibe.
10. Einarbeitet: exakte Queue-/Drain-Definition in „Grenzen“ und S4a 4.
11. Einarbeitet: Mehrfach-Takes halten eine Occupancy über die gesamte Serie;
    Admit-409 vor `RUNNING` ist Defer. Codebeleg und Vertragstest stehen in
    „Grenzen“, S4a 6 und den S4a-Tests.
