export const RAIL_SEARCH_LABEL = 'Search or go to…';
export const RAIL_SEARCH_CLEAR_LABEL = 'Clear search';
// The rail's own accessible name — the one navigation landmark that stands on
// every private route, settings included.
export const RAIL_NAV_LABEL = 'Primary';
export const RAIL_SETTINGS_LABEL = 'Settings';
export const RAIL_CONTEXT_NO_TAKES = '—';
// Remembers whether the rail's Settings disclosure was left open, so it
// doesn't snap shut the moment the viewer navigates back into the library.
export const RAIL_SETTINGS_OPEN_STORAGE_KEY = 'songmaker.rail-settings-open';
// The LIBRARY and PLAYLISTS groups' own nested navigation landmarks --
// distinct accessible names so a flow (or a screen reader) can tell them
// apart from the rail's outer RAIL_NAV_LABEL and from each other.
export const RAIL_LIBRARY_NAV_LABEL = 'Library albums';
export const RAIL_PLAYLISTS_NAV_LABEL = 'Rail playlists';
// Shown when ensureAllAlbumsLoaded fails outright, so a library the rail
// could not reach at all does not look like one that is merely empty.
export const RAIL_LIBRARY_LOAD_ERROR = "Couldn't load your library";
