// Generated from the en catalog by design-catalogs. Do not edit.

export const language = "en";
const numberFormat = new Intl.NumberFormat("en");
const pluralRules = new Intl.PluralRules("en");
// prettier-ignore
export type Words = {
    readonly "coverProblem.busy": string;
    readonly "coverProblem.budgetSpent": string;
    readonly "coverProblem.notEnabled": string;
    readonly "coverProblem.unavailable": string;
    readonly "coverProblem.signInAgain": string;
    readonly "cowriterProblem.busy": string;
    readonly "cowriterProblem.budgetSpent": string;
    readonly "cowriterProblem.notEnabled": string;
    readonly "cowriterProblem.signInAgain": string;
    readonly "cowriterProblem.unavailable": string;
    readonly "cowriterProblem.noAnswer": string;
    readonly "problemLine.logIn": string;
    readonly "problemLine.tryAgain": string;
    readonly "homeWrite.label": string;
    readonly "homeWrite.empty": string;
    readonly "homeWrite.loading": string;
    readonly "homeWrite.error": string;
    readonly "homeWrite.openSong": (gaps: { readonly title: string }) => string;
    readonly "homeWrite.workCreated": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workLyrics": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workStyle": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workRenamed": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workTake": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workCowriter": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workEdited": (gaps: { readonly time: string }) => string;
    readonly "homeListen.label": string;
    readonly "homeListen.empty": string;
    readonly "homeListen.loading": string;
    readonly "homeListen.error": string;
    readonly "homeListen.openAlbum": (gaps: { readonly title: string }) => string;
    readonly "homeListen.openPlaylist": (gaps: { readonly title: string }) => string;
    readonly "homeListen.albumCover": (gaps: { readonly title: string }) => string;
    readonly "homeListen.playlistCover": (gaps: { readonly title: string }) => string;
    readonly "homeListen.albumPlaying": (gaps: { readonly number: string; readonly total: string }) => string;
    readonly "homeListen.playlistPlaying": (gaps: { readonly number: string; readonly total: string }) => string;
    readonly "homeListen.albumStopped": (gaps: { readonly number: string }) => string;
    readonly "homeListen.playlistStopped": (gaps: { readonly number: string }) => string;
    readonly "homeListen.albumPlayed": (gaps: { readonly time: string }) => string;
    readonly "homeListen.playlistPlayed": (gaps: { readonly time: string }) => string;
    readonly "phoneTabs.nav": string;
    readonly "places.home": string;
    readonly "places.library": string;
    readonly "places.playlists": string;
    readonly "phoneAppBar.searchOpen": string;
    readonly "phoneAppBar.searchSheet": string;
    readonly "phoneAppBar.searchClose": string;
    readonly "rail.nav": string;
    readonly "rail.collapse": string;
    readonly "rail.expand": string;
    readonly "rail.resize": string;
    readonly "rail.playlistsNav": string;
    readonly "places.settings": string;
    readonly "rail.settingsNav": string;
    readonly "rail.libraryNav": string;
    readonly "rail.libraryLoading": string;
    readonly "rail.retry": string;
    readonly "rail.libraryLoadError": string;
    readonly "rail.albumCover": (gaps: { readonly title: string }) => string;
    readonly "rail.trackTakes": (count: number) => string;
    readonly "rail.trackTakesPick": (count: number) => string;
    readonly "railSearch.field": string;
    readonly "railSearch.clear": string;
    readonly "railSearch.searching": string;
    readonly "railSearch.failed": string;
    readonly "railSearch.retry": string;
    readonly "railSearch.results": string;
    readonly "railSearch.noResults": (gaps: { readonly query: string }) => string;
    readonly "railSearch.groupAlbums": string;
    readonly "railSearch.groupSongs": string;
    readonly "railSearch.groupPlaylists": string;
    readonly "railSearch.groupPages": string;
    readonly "railSearch.kindAlbum": string;
    readonly "railSearch.kindSong": string;
    readonly "railSearch.kindPlaylist": string;
    readonly "railSearch.kindPage": string;
    readonly "railSearch.songCount": (count: number) => string;
    readonly "pageBack.backTo": (gaps: { readonly page: string }) => string;
    readonly "pageBack.album": string;
    readonly "pageBack.playlist": string;
    readonly "pageBack.song": string;
    readonly "pageBack.previousPage": string;
    readonly "settingsSections.generation": string;
    readonly "settingsSections.voices": string;
    readonly "settingsSections.references": string;
    readonly "settingsSections.admin": string;
    readonly "settingsSections.about": string;
    readonly "settingsPage.documentTitle": (gaps: { readonly app: string }) => string;
    readonly "settingsPage.nav": string;
    readonly "settingsPage.adminOnly": string;
    readonly "libraryWall.heading": (gaps: { readonly count: number; readonly page: string }) => string;
    readonly "libraryWall.sortAlbums": string;
    readonly "libraryWall.sortPlaylists": string;
    readonly "libraryWall.orderTitle": string;
    readonly "libraryWall.orderPlayed": string;
    readonly "libraryWall.libraryLoading": string;
    readonly "libraryWall.libraryFailed": string;
    readonly "libraryWall.libraryEmpty": (gaps: { readonly home: string }) => string;
    readonly "libraryWall.playlistsLoading": string;
    readonly "libraryWall.playlistsFailed": string;
    readonly "libraryWall.playlistsEmpty": (gaps: { readonly home: string }) => string;
    readonly "libraryWall.retry": string;
    readonly "libraryWall.openAlbum": (gaps: { readonly title: string }) => string;
    readonly "libraryWall.openPlaylist": (gaps: { readonly title: string }) => string;
    readonly "libraryWall.albumCover": (gaps: { readonly title: string }) => string;
    readonly "libraryWall.playlistCover": (gaps: { readonly title: string }) => string;
    readonly "libraryWall.songCount": (count: number) => string;
    readonly "libraryWorkspace.loading": string;
    readonly "libraryWorkspace.retry": string;
    readonly "addressPage.loadingAlbum": string;
    readonly "addressPage.loadingSong": string;
    readonly "addressPage.loadingTake": string;
    readonly "addressPage.loadingPlaylist": string;
    readonly "addressPage.noSuchAlbum": string;
    readonly "addressPage.noSuchSong": string;
    readonly "addressPage.noSuchTake": string;
    readonly "addressPage.noSuchPlaylist": string;
    readonly "addressPage.albumUnknown": string;
    readonly "addressPage.songUnknown": string;
    readonly "addressPage.takeUnknown": string;
    readonly "addressPage.playlistUnknown": string;
    readonly "addressPage.albumUnreachable": string;
    readonly "addressPage.songUnreachable": string;
    readonly "addressPage.takeUnreachable": string;
    readonly "addressPage.playlistUnreachable": string;
    readonly "addressPage.backToLibrary": string;
    readonly "addressPage.backToAlbum": string;
    readonly "addressPage.backToSong": string;
    readonly "addressPage.tryAgain": string;
    readonly "homeList.retry": string;
    readonly "songMove.heading": string;
    readonly "songMove.back": string;
    readonly "songMove.filterLabel": string;
    readonly "songMove.filterPlaceholder": string;
    readonly "songMove.loading": string;
    readonly "songMove.noOtherAlbum": string;
    readonly "songMove.noMatch": string;
    readonly "songMove.albumCover": (gaps: { readonly title: string }) => string;
    readonly "songMove.retry": string;
    readonly "songMove.libraryLoadError": string;
    readonly "songMove.notMoved": (gaps: { readonly reason: string }) => string;
    readonly "songMove.albumGone": string;
    readonly "songMove.noConnection": string;
    readonly "songMove.failedReason": string;
    readonly "songMove.sharedTitle": string;
    readonly "songMove.sharedMessage": (gaps: { readonly album: string; readonly song: string }) => string;
    readonly "songMove.confirm": string;
    readonly "songMove.moved": (gaps: { readonly album: string }) => string;
};
// prettier-ignore
export const words: Words = {
    "coverProblem.busy": "Cover suggestions are busy. Try again when Suggest opens.",
    "coverProblem.budgetSpent": "The budget for cover suggestions is used up. Try again later.",
    "coverProblem.notEnabled": "Cover suggestions are not enabled for your account. Ask an admin to enable them.",
    "coverProblem.unavailable": "Cover suggestions are unavailable right now. Try again later.",
    "coverProblem.signInAgain": "Log in again to get cover suggestions",
    "cowriterProblem.busy": "The co-writer is busy",
    "cowriterProblem.budgetSpent": "The co-writer's budget is used up. Try again later.",
    "cowriterProblem.notEnabled": "The co-writer is not enabled for your account",
    "cowriterProblem.signInAgain": "Log in again to use the co-writer",
    "cowriterProblem.unavailable": "The co-writer is unavailable",
    "cowriterProblem.noAnswer": "The co-writer did not answer. Try again.",
    "problemLine.logIn": "Log in",
    "problemLine.tryAgain": "Try again",
    "homeWrite.label": "Write",
    "homeWrite.empty": "Songs you work on will appear here.",
    "homeWrite.loading": "Loading Write…",
    "homeWrite.error": "Could not load Write.",
    "homeWrite.openSong": (gaps: { readonly title: string }) => "Open song " + gaps.title,
    "homeWrite.workCreated": (gaps: { readonly time: string }) => "new song · " + gaps.time,
    "homeWrite.workLyrics": (gaps: { readonly time: string }) => "lyrics edited · " + gaps.time,
    "homeWrite.workStyle": (gaps: { readonly time: string }) => "style edited · " + gaps.time,
    "homeWrite.workRenamed": (gaps: { readonly time: string }) => "renamed · " + gaps.time,
    "homeWrite.workTake": (gaps: { readonly time: string }) => "new take · " + gaps.time,
    "homeWrite.workCowriter": (gaps: { readonly time: string }) => "co-writer · " + gaps.time,
    "homeWrite.workEdited": (gaps: { readonly time: string }) => "edited · " + gaps.time,
    "homeListen.label": "Listen",
    "homeListen.empty": "Albums and playlists you play will appear here.",
    "homeListen.loading": "Loading Listen…",
    "homeListen.error": "Could not load Listen.",
    "homeListen.openAlbum": (gaps: { readonly title: string }) => "Open album " + gaps.title,
    "homeListen.openPlaylist": (gaps: { readonly title: string }) => "Open playlist " + gaps.title,
    "homeListen.albumCover": (gaps: { readonly title: string }) => "album cover for " + gaps.title,
    "homeListen.playlistCover": (gaps: { readonly title: string }) => "playlist cover for " + gaps.title,
    "homeListen.albumPlaying": (gaps: { readonly number: string; readonly total: string }) => "Album · playing · song " + gaps.number + " of " + gaps.total,
    "homeListen.playlistPlaying": (gaps: { readonly number: string; readonly total: string }) => "Playlist · playing · song " + gaps.number + " of " + gaps.total,
    "homeListen.albumStopped": (gaps: { readonly number: string }) => "Album · stopped at song " + gaps.number,
    "homeListen.playlistStopped": (gaps: { readonly number: string }) => "Playlist · stopped at song " + gaps.number,
    "homeListen.albumPlayed": (gaps: { readonly time: string }) => "Album · played " + gaps.time,
    "homeListen.playlistPlayed": (gaps: { readonly time: string }) => "Playlist · played " + gaps.time,
    "phoneTabs.nav": "Places",
    "places.home": "Home",
    "places.library": "Library",
    "places.playlists": "Playlists",
    "phoneAppBar.searchOpen": "Search",
    "phoneAppBar.searchSheet": "Search",
    "phoneAppBar.searchClose": "Close search",
    "rail.nav": "Primary",
    "rail.collapse": "Collapse rail",
    "rail.expand": "Expand rail",
    "rail.resize": "Resize rail",
    "rail.playlistsNav": "Rail playlists",
    "places.settings": "Settings",
    "rail.settingsNav": "Settings sections",
    "rail.libraryNav": "Library albums",
    "rail.libraryLoading": "Loading albums…",
    "rail.retry": "Retry",
    "rail.libraryLoadError": "Couldn't load your library",
    "rail.albumCover": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "rail.trackTakes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "rail.trackTakesPick": (count: number) => ({
        zero: numberFormat.format(count) + " takes · pick",
        one: numberFormat.format(count) + " take · pick",
        two: numberFormat.format(count) + " takes · pick",
        few: numberFormat.format(count) + " takes · pick",
        many: numberFormat.format(count) + " takes · pick",
        other: numberFormat.format(count) + " takes · pick",
    })[pluralRules.select(count)],
    "railSearch.field": "Search or go to…",
    "railSearch.clear": "Clear search",
    "railSearch.searching": "Searching…",
    "railSearch.failed": "Search failed",
    "railSearch.retry": "Retry",
    "railSearch.results": "Search results",
    "railSearch.noResults": (gaps: { readonly query: string }) => "No results for “" + gaps.query + "”.",
    "railSearch.groupAlbums": "Albums",
    "railSearch.groupSongs": "Songs",
    "railSearch.groupPlaylists": "Playlists",
    "railSearch.groupPages": "Pages",
    "railSearch.kindAlbum": "Album",
    "railSearch.kindSong": "Song",
    "railSearch.kindPlaylist": "Playlist",
    "railSearch.kindPage": "Page",
    "railSearch.songCount": (count: number) => ({
        zero: numberFormat.format(count) + " songs",
        one: numberFormat.format(count) + " song",
        two: numberFormat.format(count) + " songs",
        few: numberFormat.format(count) + " songs",
        many: numberFormat.format(count) + " songs",
        other: numberFormat.format(count) + " songs",
    })[pluralRules.select(count)],
    "pageBack.backTo": (gaps: { readonly page: string }) => "Back to " + gaps.page,
    "pageBack.album": "Album",
    "pageBack.playlist": "Playlist",
    "pageBack.song": "Song",
    "pageBack.previousPage": "Previous page",
    "settingsSections.generation": "Generation",
    "settingsSections.voices": "Voices",
    "settingsSections.references": "References",
    "settingsSections.admin": "Admin",
    "settingsSections.about": "About",
    "settingsPage.documentTitle": (gaps: { readonly app: string }) => "Settings — " + gaps.app,
    "settingsPage.nav": "Settings sections",
    "settingsPage.adminOnly": "admins only",
    "libraryWall.heading": (gaps: { readonly count: number; readonly page: string }) => gaps.page + " · " + numberFormat.format(gaps.count),
    "libraryWall.sortAlbums": "Sort albums",
    "libraryWall.sortPlaylists": "Sort playlists",
    "libraryWall.orderTitle": "A–Z",
    "libraryWall.orderPlayed": "Last played",
    "libraryWall.libraryLoading": "Loading library…",
    "libraryWall.libraryFailed": "Could not load library.",
    "libraryWall.libraryEmpty": (gaps: { readonly home: string }) => "No albums yet. + New on " + gaps.home + " makes one.",
    "libraryWall.playlistsLoading": "Loading playlists…",
    "libraryWall.playlistsFailed": "Failed to load playlists",
    "libraryWall.playlistsEmpty": (gaps: { readonly home: string }) => "No playlists yet. + New on " + gaps.home + " makes one.",
    "libraryWall.retry": "Retry",
    "libraryWall.openAlbum": (gaps: { readonly title: string }) => "Open album " + gaps.title,
    "libraryWall.openPlaylist": (gaps: { readonly title: string }) => "Open playlist " + gaps.title,
    "libraryWall.albumCover": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "libraryWall.playlistCover": (gaps: { readonly title: string }) => "Playlist cover for " + gaps.title,
    "libraryWall.songCount": (count: number) => ({
        zero: numberFormat.format(count) + " songs",
        one: numberFormat.format(count) + " song",
        two: numberFormat.format(count) + " songs",
        few: numberFormat.format(count) + " songs",
        many: numberFormat.format(count) + " songs",
        other: numberFormat.format(count) + " songs",
    })[pluralRules.select(count)],
    "libraryWorkspace.loading": "Loading...",
    "libraryWorkspace.retry": "Retry",
    "addressPage.loadingAlbum": "Loading album...",
    "addressPage.loadingSong": "Loading song...",
    "addressPage.loadingTake": "Loading take...",
    "addressPage.loadingPlaylist": "Loading playlist...",
    "addressPage.noSuchAlbum": "No such album",
    "addressPage.noSuchSong": "No such song",
    "addressPage.noSuchTake": "No such take",
    "addressPage.noSuchPlaylist": "No such playlist",
    "addressPage.albumUnknown": "This address does not name an album in your library.",
    "addressPage.songUnknown": "This address does not name a song in this album.",
    "addressPage.takeUnknown": "This address does not name a take of this song.",
    "addressPage.playlistUnknown": "This address does not name a playlist in your library.",
    "addressPage.albumUnreachable": "This album could not be loaded.",
    "addressPage.songUnreachable": "This song could not be loaded.",
    "addressPage.takeUnreachable": "This take could not be loaded.",
    "addressPage.playlistUnreachable": "This playlist could not be loaded.",
    "addressPage.backToLibrary": "Back to the library",
    "addressPage.backToAlbum": "Back to the album",
    "addressPage.backToSong": "Back to the song",
    "addressPage.tryAgain": "Try again",
    "homeList.retry": "Retry",
    "songMove.heading": "Move to",
    "songMove.back": "Back to song menu",
    "songMove.filterLabel": "Filter albums",
    "songMove.filterPlaceholder": "Filter",
    "songMove.loading": "Looking…",
    "songMove.noOtherAlbum": "No other album",
    "songMove.noMatch": "No album matches",
    "songMove.albumCover": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "songMove.retry": "Retry",
    "songMove.libraryLoadError": "Couldn't load your library",
    "songMove.notMoved": (gaps: { readonly reason: string }) => "Not moved · " + gaps.reason,
    "songMove.albumGone": "album gone",
    "songMove.noConnection": "no connection",
    "songMove.failedReason": "something went wrong",
    "songMove.sharedTitle": "Move to a shared album?",
    "songMove.sharedMessage": (gaps: { readonly album: string; readonly song: string }) => gaps.song + " appears on " + gaps.album + "'s public page",
    "songMove.confirm": "Move",
    "songMove.moved": (gaps: { readonly album: string }) => "Moved to " + gaps.album,
};
export type Key = keyof Words;
