// Generated from the en catalog by design-catalogs. Do not edit.

export const language = "en";
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
};
export type Key = keyof Words;
