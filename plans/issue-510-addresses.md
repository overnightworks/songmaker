# #510 — URL-Grammatik aus `libraryContext`

Leser: der Builder der nächsten Scheibe. Entscheidung: reine, synchrone
Adressregeln erhalten einen einzigen Owner, ohne den Store zu laden.

## Ziel und Schnitt

`frontend/src/lib/routes/addresses.ts` wird der Owner für URL-Grammatik. Es
importiert weder `$lib/stores/*` noch `$lib/api/*`; es kennt keine History,
keinen Browser und keine Ressourcenauflösung. Es baut, erkennt und liest nur
Library-Adressen:

- `albumRoutePath`, `songRoutePath`, `takeRoutePath`, `playlistRoutePath`;
- `isAlbumRoutePath`, `isSongRoutePath`, `isTakeRoutePath`,
  `isPlaylistRoutePath` und die daraus abgeleitete, bisher private
  `libraryRouteShape`/`LibraryRouteShape`;
- die vorhandene Query-Grammatik als kleine pure Helfer: `?song=<id>` mit
  optionalem `&gen=<id>` lesen sowie den Legacy-Fallback und den temporären
  `?gen=<id>`-Anhang bauen.

Die Builder behalten `encodeURIComponent`; die Erkennung bleibt absichtlich
strukturell (ein Song-/Take-Pfad zählt weiter auch als Album-/Song-Pfad).
Slugs, IDs und Take-Nummern werden hier weder gegen API-Daten aufgelöst noch
neu validiert.

`libraryContext.ts` importiert diese Regeln. `libraryHistoryUrl` bleibt dort:
es entscheidet anhand von `LibraryHistoryState`, `songList` und `playlistList`,
welche der reinen Adressen gerade gilt, und ruft dann nur die neuen Builder auf.
Auch `writeLibraryHistory` bleibt Owner des SvelteKit-Transports, benutzt für
seine Crossing-Entscheidung aber `libraryRouteShape` aus `addresses.ts`.

## Importentscheidung

Es gibt keinen dauerhaften Doppel-Export. Nach dieser Scheibe exportiert
`libraryContext.ts` keine URL-Builder/-Prädikate mehr; alle direkten Nutzer
importieren sie von `$lib/routes/addresses`:

- `lib/stores/navigation.ts`: Workspace- und Rename-Prädikate;
- `(library)/album/[slug]/[song]/+page.svelte` und
  `.../[song]/take/[n]/+page.svelte`: Fehler-Links;
- `(library)/+page.svelte`: Legacy-Query über den neuen Leser statt zwei
  ad-hoc-`searchParams.get`-Aufrufe;
- `libraryContext.ts`: Adapter und Route-Crossing; die übrigen Importeure von
  `libraryContext` bleiben unverändert, weil sie Store-, History- oder
  Auflösungs-Exports beziehen.

Die Namen werden nicht übergangsweise aus dem Store re-exportiert: diese
Scheibe ändert die genannten Importstellen zusammen mit dem Ownerwechsel.

## Tests und Nachweis

| Ziel | Zieltest |
| --- | --- |
| Reine Pfade, Escaping und Hierarchie-Erkennung | Neuer `lib/routes/addresses.test.ts`; tabellarisch je Adressform: Builder-Eingabe/URL sowie gültige und ungültige Pfade. |
| Legacy-`song`/`gen` und der ausstehende Take-Anhang | Dieselbe Tabelle mit Eingabe-`URLSearchParams` bzw. IDs und erwarteter Query-Adresse; `gen` ohne `song` bleibt kein öffnungsfähiger Legacy-Link. |
| Store-abhängige Adresswahl | `libraryContext.test.ts` behält `libraryHistoryUrl`-Fälle (bekannter/unbekannter Song bzw. Playlist) und nutzt nur die neue Grammatik indirekt. |
| SvelteKit-Crossing und echte Auflösung | `libraryContext.test.ts` behält die `goto`-Crossing-Suite und alle `open*Address`-/Legacy-Auflösungsfälle; die bestehenden Routen- und Navigationstests bleiben Integrationsnachweis. |

Der Builder verschiebt die heutigen vier `is*RoutePath`-Describe-Blöcke und
den Playlist-Builder-Test aus `libraryContext.test.ts` in die Tabelle; die
übrigen vorhandenen Assertions werden nicht dupliziert. Danach ausführen:
`pnpm --dir frontend test -- lib/routes/addresses.test.ts lib/stores/libraryContext.test.ts lib/stores/navigation.test.ts`, anschließend `pnpm --dir frontend check` und die vollständige Frontend-Test-Suite.

## Bewusst nicht in dieser Scheibe

In `libraryContext.ts` bleiben History-Schema und -Validierung
(`LibraryHistoryState`, Root-/Wall-State), der History-Transport
(`writeLibraryHistory`, Queue, `goto`/History-API), Netzwerk- und
Store-Auflösung (`open*Address`, `resolveLegacySongQueryAddress`, Fetches) sowie
Filter-, Surface- und Scroll-State. Eine nächste, separat geplante Scheibe
kann zuerst History-Schema/Transport von der Ressourcenauflösung trennen;
Filter/Scroll bleiben danach ein eigener Store-Schnitt.

## Risiko

SvelteKit erkennt einen Routenwechsel nur über `goto`; ein falscher oder
anders klassifizierter `libraryRouteShape` würde einen rohen History-Write auf
einem anderen Route-File erlauben. Deshalb übernimmt die neue Grammatik die
existierenden Shape-Regeln unverändert und die Crossing-Integrationstests
bleiben am Navigation-Store. Der reine Modulimport darf keine Browser-, Svelte-
oder API-Abhängigkeit einführen; das wird beim Review über die Importliste und
die isolierte Grammatik-Testdatei geprüft.
