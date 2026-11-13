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
    readonly "newPlace.face": string;
    readonly "newPlace.menuLabel": string;
    readonly "newPlace.menuClose": (gaps: { readonly library: string }) => string;
    readonly "newPlace.album": string;
    readonly "newPlace.playlist": string;
    readonly "newPlace.create": string;
    readonly "newPlace.offline": string;
    readonly "newAlbum.cardLabel": string;
    readonly "newAlbum.close": string;
    readonly "newAlbum.titleLabel": string;
    readonly "newAlbum.artistLabel": string;
    readonly "newAlbum.artistOptional": string;
    readonly "newAlbum.hint": string;
    readonly "newAlbum.failed": string;
    readonly "newAlbum.refused": string;
    readonly "newPlaylist.cardLabel": string;
    readonly "newPlaylist.close": string;
    readonly "newPlaylist.nameLabel": string;
    readonly "newPlaylist.hint": string;
    readonly "newPlaylist.failed": string;
    readonly "newPlaylist.refused": string;
    readonly "newSong.rowLabel": string;
    readonly "newSong.cardLabel": (gaps: { readonly album: string }) => string;
    readonly "newSong.close": string;
    readonly "newSong.titleLabel": string;
    readonly "newSong.hint": string;
    readonly "newSong.failed": string;
    readonly "newSong.refused": string;
    readonly "referenceMenu.label": string;
    readonly "referenceMenu.close": string;
    readonly "referenceMenu.showTakes": string;
    readonly "referenceMenu.delete": string;
    readonly "referenceMenu.inUse": string;
    readonly "newPlace.heading": (gaps: { readonly library: string }) => readonly (string | { readonly marker: "strong"; readonly text: string })[];
    readonly "takeRefusal.archived": string;
    readonly "modelRefusal.unavailable": (gaps: { readonly model: string }) => string;
    readonly "songMenu.label": string;
    readonly "songMenu.close": string;
    readonly "songMenu.heading": (gaps: { readonly title: string }) => string;
    readonly "songMenu.save": string;
    readonly "songMenu.rename": string;
    readonly "songMenu.addToPlaylist": string;
    readonly "songMenu.move": string;
    readonly "songMenu.delete": string;
    readonly "takeMenu.label": string;
    readonly "takeMenu.close": string;
    readonly "takeMenu.headingWithVersion": (gaps: { readonly take: string; readonly version: string }) => string;
    readonly "takeMenu.heading": (gaps: { readonly take: string }) => string;
    readonly "takeMenu.repaint": string;
    readonly "takeMenu.cover": string;
    readonly "takeMenu.useSeed": string;
    readonly "takeMenu.restore": string;
    readonly "takeMenu.addToPlaylist": string;
    readonly "takeMenu.share": string;
    readonly "takeMenu.shareOn": string;
    readonly "takeMenu.shareOff": string;
    readonly "takeMenu.delete": string;
    readonly "collectionMenu.label": string;
    readonly "collectionMenu.close": string;
    readonly "collectionMenu.albumHeading": (gaps: { readonly title: string }) => string;
    readonly "collectionMenu.playlistHeading": (gaps: { readonly title: string }) => string;
    readonly "collectionMenu.editDetails": string;
    readonly "collectionMenu.cover": string;
    readonly "collectionMenu.coverHint": string;
    readonly "collectionMenu.curate": string;
    readonly "collectionMenu.addToPlaylist": string;
    readonly "collectionMenu.archive": string;
    readonly "collectionMenu.albumShare": string;
    readonly "collectionMenu.playlistShare": string;
    readonly "collectionMenu.shareOn": string;
    readonly "collectionMenu.shareOff": string;
    readonly "collectionMenu.upload": string;
    readonly "collectionMenu.removeCover": string;
    readonly "collectionMenu.rename": string;
    readonly "collectionMenu.albumDelete": string;
    readonly "collectionMenu.playlistDelete": string;
    readonly "albumPage.loading": string;
    readonly "albumPage.retry": string;
    readonly "albumPage.noSongs": string;
    readonly "albumPage.coverAlt": (gaps: { readonly title: string }) => string;
    readonly "albumPage.coverAltFallback": string;
    readonly "albumPage.songTakes": (count: number) => string;
    readonly "albumPage.coverUploadFailed": string;
    readonly "albumPage.coverDiscardFailed": string;
    readonly "albumPage.coverRemoved": string;
    readonly "albumPage.coverRemoveFailed": string;
    readonly "albumPage.yearWhole": string;
    readonly "albumPage.yearRange": (gaps: { readonly max: string; readonly min: string }) => string;
    readonly "albumPage.deleted": string;
    readonly "albumPage.restored": string;
    readonly "albumPage.restoreFailed": string;
    readonly "albumPage.deleteFailed": string;
    readonly "albumPage.archived": string;
    readonly "albumPage.unarchived": string;
    readonly "albumPage.unarchiveFailed": string;
    readonly "albumPage.archiveFailed": string;
    readonly "albumPage.addedSkipped": (gaps: { readonly added: string; readonly skipped: string }) => string;
    readonly "albumPage.addedToPlaylist": string;
    readonly "albumPage.addFailed": string;
    readonly "albumPage.songsLoadFailed": string;
    readonly "albumPage.deleteTitle": (gaps: { readonly title: string }) => string;
    readonly "albumPage.deleteSongs": (count: number, gaps: { readonly titles: string }) => string;
    readonly "albumPage.deleteTakes": (count: number) => string;
    readonly "albumPage.deleteHistory": string;
    readonly "albumPage.deleteConfirm": string;
    readonly "albumCover.add": string;
    readonly "albumCover.edit": string;
    readonly "albumCover.editing": string;
    readonly "albumCover.editingClose": string;
    readonly "albumCover.upload": string;
    readonly "albumCover.suggest": string;
    readonly "albumCover.suggestAnother": string;
    readonly "albumCover.use": string;
    readonly "albumCover.remove": string;
    readonly "albumCover.previousSuggestion": string;
    readonly "albumCover.nextSuggestion": string;
    readonly "albumCover.suggestionsLoading": string;
    readonly "albumCover.suggesting": string;
    readonly "albumCover.suggestionFailedTitle": string;
    readonly "albumCover.suggestionFailedFallback": string;
    readonly "albumCover.throttledFallback": string;
    readonly "albumCover.suggestionsRetry": string;
    readonly "albumCover.alt": (gaps: { readonly title: string }) => string;
    readonly "albumCover.suggestionAlt": (gaps: { readonly title: string }) => string;
    readonly "albumCover.suggestionPosition": (gaps: { readonly shown: string; readonly total: string }) => string;
    readonly "albumCover.stageLabel": (gaps: { readonly shown: string; readonly total: string }) => string;
    readonly "albumCover.saved": string;
    readonly "albumDetails.close": string;
    readonly "albumDetails.title": string;
    readonly "albumDetails.subtitle": string;
    readonly "albumDetails.year": string;
    readonly "albumDetails.save": string;
    readonly "albumDetails.titleRequired": string;
    readonly "albumDetails.saved": string;
    readonly "albumDetails.saveFailed": string;
    readonly "coverMark.waiting": (count: number) => string;
    readonly "coverMark.runningName": (gaps: { readonly label: string }) => string;
    readonly "coverMark.waitingName": (gaps: { readonly label: string; readonly waiting: string }) => string;
    readonly "collectionHeader.songCount": (count: number) => string;
    readonly "songPage.coverAlt": (gaps: { readonly title: string }) => string;
    readonly "songPage.coverAltAlbum": (gaps: { readonly title: string }) => string;
    readonly "songPage.coverAltBare": string;
    readonly "songPage.coverUpload": string;
    readonly "songPage.coverReplace": string;
    readonly "songPage.trackOf": (gaps: { readonly position: string; readonly total: string }) => string;
    readonly "songPage.save": string;
    readonly "songPage.saveName": string;
    readonly "songPage.unsavedTitle": string;
    readonly "songPage.unsavedMessage": string;
    readonly "songPage.unsavedSave": string;
    readonly "songPage.unsavedDiscard": string;
    readonly "songPage.coverSaved": string;
    readonly "songPage.coverUploadFailed": string;
    readonly "songPage.coverRemoved": string;
    readonly "songPage.coverRemoveFailed": string;
    readonly "songPage.renamed": string;
    readonly "songPage.renameFailed": string;
    readonly "songPage.deleted": string;
    readonly "songPage.undo": string;
    readonly "songPage.restored": string;
    readonly "songPage.restoreFailed": string;
    readonly "songPage.deleteFailed": string;
    readonly "songPage.takeDeleted": string;
    readonly "songPage.addedToPlaylist": string;
    readonly "songPage.addToPlaylistFailed": string;
    readonly "songPage.savedVersion": (gaps: { readonly number: string }) => string;
    readonly "songPage.saveFailed": string;
    readonly "songPage.deleteTitle": (gaps: { readonly title: string }) => string;
    readonly "songPage.deleteTakes": (count: number) => string;
    readonly "songPage.deleteVersions": (count: number) => string;
    readonly "songPage.deleteHistory": string;
    readonly "songPage.deleteConfirm": string;
    readonly "songPage.expiry": (count: number, gaps: { readonly when: string }) => string;
    readonly "songPage.expirySoon": string;
    readonly "songPage.expiryDays": (count: number) => string;
    readonly "songHeader.title": string;
    readonly "songHeader.editTitle": string;
    readonly "songHeader.albumNavigation": string;
    readonly "songHeader.previous": string;
    readonly "songHeader.next": string;
    readonly "songHeader.removeCover": string;
    readonly "songTabs.label": string;
    readonly "songTabs.edit": string;
    readonly "songTabs.takes": string;
    readonly "songTabs.cowriter": string;
    readonly "writeColumn.lyrics": string;
    readonly "writeColumn.stylePrompt": string;
    readonly "writeColumn.loadedFrom": (gaps: { readonly number: string }) => string;
    readonly "versions.name": (gaps: { readonly number: string }) => string;
    readonly "versions.chipDraft": (gaps: { readonly number: string }) => string;
    readonly "versions.chipName": (gaps: { readonly chip: string }) => string;
    readonly "versions.heading": string;
    readonly "versions.close": string;
    readonly "versions.current": string;
    readonly "versions.picked": string;
    readonly "versions.noLyrics": string;
    readonly "versions.noTakes": string;
    readonly "versions.takes": (count: number) => string;
    readonly "versions.deleteName": (gaps: { readonly number: string }) => string;
    readonly "versions.deleteTitle": (gaps: { readonly number: string }) => string;
    readonly "versions.deleteTitleTakes": (count: number, gaps: { readonly number: string }) => string;
    readonly "versions.deleteConfirm": string;
    readonly "versions.deletePick": (count: number) => string;
    readonly "versions.deleteDraftGoes": string;
    readonly "versions.deleteEmptiesEditor": string;
    readonly "versions.deleteLoadUndoGoes": string;
    readonly "versions.deleteReplacedBy": (gaps: { readonly number: string }) => string;
    readonly "versions.deleteLoadedDraftGoes": (gaps: { readonly number: string }) => string;
    readonly "versions.deleteLoadedDraftReplaced": (gaps: { readonly loadedFrom: string; readonly replacedBy: string }) => string;
    readonly "versions.deleted": (gaps: { readonly number: string }) => string;
    readonly "versions.replaceTitle": string;
    readonly "versions.replaceMessage": (gaps: { readonly number: string }) => string;
    readonly "versions.replaceConfirm": string;
    readonly "versions.loaded": (gaps: { readonly number: string }) => string;
    readonly "versions.alreadyDraft": (gaps: { readonly number: string }) => string;
    readonly "versions.undo": string;
    readonly "editableTitle.hint": string;
    readonly "collectionHeader.titleAlbum": string;
    readonly "collectionHeader.titlePlaylist": string;
    readonly "collectionHeader.editTitleAlbum": string;
    readonly "collectionHeader.editTitlePlaylist": string;
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
    "newPlace.face": "New",
    "newPlace.menuLabel": "New album or playlist",
    "newPlace.menuClose": (gaps: { readonly library: string }) => "Close New in " + gaps.library,
    "newPlace.album": "Album",
    "newPlace.playlist": "Playlist",
    "newPlace.create": "Create",
    "newPlace.offline": "You're offline, so nothing was created. Try again once you're back online.",
    "newAlbum.cardLabel": "New album",
    "newAlbum.close": "Close new album",
    "newAlbum.titleLabel": "Title",
    "newAlbum.artistLabel": "Artist",
    "newAlbum.artistOptional": "optional",
    "newAlbum.hint": "Opens the album; add songs there.",
    "newAlbum.failed": "The album could not be created. Try again.",
    "newAlbum.refused": "The album could not be created.",
    "newPlaylist.cardLabel": "New playlist",
    "newPlaylist.close": "Close new playlist",
    "newPlaylist.nameLabel": "Name",
    "newPlaylist.hint": "Opens the playlist; add songs from any album.",
    "newPlaylist.failed": "The playlist could not be created. Try again.",
    "newPlaylist.refused": "The playlist could not be created.",
    "newSong.rowLabel": "New song",
    "newSong.cardLabel": (gaps: { readonly album: string }) => "New song in " + gaps.album,
    "newSong.close": "Close new song",
    "newSong.titleLabel": "Title",
    "newSong.hint": "Opens the song on Write.",
    "newSong.failed": "The song could not be created. Try again.",
    "newSong.refused": "The song could not be created.",
    "referenceMenu.label": "Reference menu",
    "referenceMenu.close": "Close menu",
    "referenceMenu.showTakes": "Show takes",
    "referenceMenu.delete": "Delete",
    "referenceMenu.inUse": "In use",
    "newPlace.heading": (gaps: { readonly library: string }): readonly (string | { readonly marker: "strong"; readonly text: string })[] => ["New in ", { marker: "strong", text: gaps.library }],
    "takeRefusal.archived": "Restore this take first.",
    "modelRefusal.unavailable": (gaps: { readonly model: string }) => "Model '" + gaps.model + "' is not currently available",
    "songMenu.label": "Song menu",
    "songMenu.close": "Close menu",
    "songMenu.heading": (gaps: { readonly title: string }) => "Song · " + gaps.title,
    "songMenu.save": "Save version",
    "songMenu.rename": "Rename",
    "songMenu.addToPlaylist": "Add to playlist",
    "songMenu.move": "Move",
    "songMenu.delete": "Delete song",
    "takeMenu.label": "More",
    "takeMenu.close": "Close menu",
    "takeMenu.headingWithVersion": (gaps: { readonly take: string; readonly version: string }) => "Take · v" + gaps.version + " · " + gaps.take,
    "takeMenu.heading": (gaps: { readonly take: string }) => "Take · " + gaps.take,
    "takeMenu.repaint": "Repaint",
    "takeMenu.cover": "Cover",
    "takeMenu.useSeed": "Use seed",
    "takeMenu.restore": "Restore",
    "takeMenu.addToPlaylist": "Add to playlist",
    "takeMenu.share": "Share",
    "takeMenu.shareOn": "on",
    "takeMenu.shareOff": "off",
    "takeMenu.delete": "Delete",
    "collectionMenu.label": "More",
    "collectionMenu.close": "Close menu",
    "collectionMenu.albumHeading": (gaps: { readonly title: string }) => "Album · " + gaps.title,
    "collectionMenu.playlistHeading": (gaps: { readonly title: string }) => "Playlist · " + gaps.title,
    "collectionMenu.editDetails": "Edit details",
    "collectionMenu.cover": "Cover",
    "collectionMenu.coverHint": "upload · suggest",
    "collectionMenu.curate": "Pick album takes",
    "collectionMenu.addToPlaylist": "Add to playlist",
    "collectionMenu.archive": "Archive",
    "collectionMenu.albumShare": "Share",
    "collectionMenu.playlistShare": "Share playlist",
    "collectionMenu.shareOn": "on",
    "collectionMenu.shareOff": "off",
    "collectionMenu.upload": "Upload…",
    "collectionMenu.removeCover": "Remove cover",
    "collectionMenu.rename": "Rename",
    "collectionMenu.albumDelete": "Delete",
    "collectionMenu.playlistDelete": "Delete playlist",
    "albumPage.loading": "Loading albums…",
    "albumPage.retry": "Retry",
    "albumPage.noSongs": "No songs yet.",
    "albumPage.coverAlt": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "albumPage.coverAltFallback": "Album",
    "albumPage.songTakes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "albumPage.coverUploadFailed": "Cover upload failed",
    "albumPage.coverDiscardFailed": "Cover suggestions could not be discarded",
    "albumPage.coverRemoved": "Cover removed",
    "albumPage.coverRemoveFailed": "Cover remove failed",
    "albumPage.yearWhole": "Year must be a whole number",
    "albumPage.yearRange": (gaps: { readonly max: string; readonly min: string }) => "Year must be between " + gaps.min + " and " + gaps.max,
    "albumPage.deleted": "Album deleted",
    "albumPage.restored": "Album restored",
    "albumPage.restoreFailed": "Restore failed",
    "albumPage.deleteFailed": "Delete failed",
    "albumPage.archived": "Album archived",
    "albumPage.unarchived": "Album unarchived",
    "albumPage.unarchiveFailed": "Unarchive failed",
    "albumPage.archiveFailed": "Archive failed",
    "albumPage.addedSkipped": (gaps: { readonly added: string; readonly skipped: string }) => "Added " + gaps.added + ", skipped " + gaps.skipped,
    "albumPage.addedToPlaylist": "Added to playlist",
    "albumPage.addFailed": "Failed to add",
    "albumPage.songsLoadFailed": "Failed to load songs",
    "albumPage.deleteTitle": (gaps: { readonly title: string }) => "Delete \"" + gaps.title + "\"?",
    "albumPage.deleteSongs": (count: number, gaps: { readonly titles: string }) => ({
        zero: numberFormat.format(count) + " songs (" + gaps.titles + ")",
        one: numberFormat.format(count) + " song (" + gaps.titles + ")",
        two: numberFormat.format(count) + " songs (" + gaps.titles + ")",
        few: numberFormat.format(count) + " songs (" + gaps.titles + ")",
        many: numberFormat.format(count) + " songs (" + gaps.titles + ")",
        other: numberFormat.format(count) + " songs (" + gaps.titles + ")",
    })[pluralRules.select(count)],
    "albumPage.deleteTakes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "albumPage.deleteHistory": "All versions, scores, and chat history",
    "albumPage.deleteConfirm": "Delete Album",
    "albumCover.add": "Add cover",
    "albumCover.edit": "Edit cover",
    "albumCover.editing": "Cover editing",
    "albumCover.editingClose": "Close cover editing",
    "albumCover.upload": "Upload",
    "albumCover.suggest": "Suggest",
    "albumCover.suggestAnother": "Suggest another",
    "albumCover.use": "Use",
    "albumCover.remove": "Remove",
    "albumCover.previousSuggestion": "Previous suggestion",
    "albumCover.nextSuggestion": "Next suggestion",
    "albumCover.suggestionsLoading": "Loading cover suggestion…",
    "albumCover.suggesting": "Making a cover",
    "albumCover.suggestionFailedTitle": "Couldn’t make a cover suggestion",
    "albumCover.suggestionFailedFallback": "The cover suggestion failed. Try again.",
    "albumCover.throttledFallback": "Too many requests right now. Press Suggest again in a moment.",
    "albumCover.suggestionsRetry": "Try again",
    "albumCover.alt": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "albumCover.suggestionAlt": (gaps: { readonly title: string }) => "Cover suggestion for " + gaps.title,
    "albumCover.suggestionPosition": (gaps: { readonly shown: string; readonly total: string }) => gaps.shown + " / " + gaps.total,
    "albumCover.stageLabel": (gaps: { readonly shown: string; readonly total: string }) => "Cover suggestion " + gaps.shown + " of " + gaps.total,
    "albumCover.saved": "Cover saved",
    "albumDetails.close": "Close edit details",
    "albumDetails.title": "Title",
    "albumDetails.subtitle": "Subtitle",
    "albumDetails.year": "Year",
    "albumDetails.save": "Save",
    "albumDetails.titleRequired": "Title cannot be empty",
    "albumDetails.saved": "Details saved",
    "albumDetails.saveFailed": "Saving the details failed",
    "coverMark.waiting": (count: number) => ({
        zero: numberFormat.format(count) + " waiting",
        one: numberFormat.format(count) + " waiting",
        two: numberFormat.format(count) + " waiting",
        few: numberFormat.format(count) + " waiting",
        many: numberFormat.format(count) + " waiting",
        other: numberFormat.format(count) + " waiting",
    })[pluralRules.select(count)],
    "coverMark.runningName": (gaps: { readonly label: string }) => gaps.label + " · making a suggestion",
    "coverMark.waitingName": (gaps: { readonly label: string; readonly waiting: string }) => gaps.label + " · " + gaps.waiting,
    "collectionHeader.songCount": (count: number) => ({
        zero: numberFormat.format(count) + " songs",
        one: numberFormat.format(count) + " song",
        two: numberFormat.format(count) + " songs",
        few: numberFormat.format(count) + " songs",
        many: numberFormat.format(count) + " songs",
        other: numberFormat.format(count) + " songs",
    })[pluralRules.select(count)],
    "songPage.coverAlt": (gaps: { readonly title: string }) => "Song " + gaps.title,
    "songPage.coverAltAlbum": (gaps: { readonly title: string }) => "Album " + gaps.title,
    "songPage.coverAltBare": "Song",
    "songPage.coverUpload": "Upload song cover",
    "songPage.coverReplace": "Replace song cover",
    "songPage.trackOf": (gaps: { readonly position: string; readonly total: string }) => "Track " + gaps.position + " of " + gaps.total,
    "songPage.save": "Save",
    "songPage.saveName": "Save changes",
    "songPage.unsavedTitle": "Unsaved changes",
    "songPage.unsavedMessage": "Save this draft as a new version before leaving, or discard it?",
    "songPage.unsavedSave": "Save",
    "songPage.unsavedDiscard": "Discard",
    "songPage.coverSaved": "Cover saved",
    "songPage.coverUploadFailed": "Cover upload failed",
    "songPage.coverRemoved": "Cover removed",
    "songPage.coverRemoveFailed": "Cover remove failed",
    "songPage.renamed": "Song renamed",
    "songPage.renameFailed": "Rename failed",
    "songPage.deleted": "Song deleted",
    "songPage.undo": "Undo",
    "songPage.restored": "Song restored",
    "songPage.restoreFailed": "Restore failed",
    "songPage.deleteFailed": "Delete failed",
    "songPage.takeDeleted": "Take deleted",
    "songPage.addedToPlaylist": "Added to playlist",
    "songPage.addToPlaylistFailed": "Failed to add",
    "songPage.savedVersion": (gaps: { readonly number: string }) => "Saved version " + gaps.number,
    "songPage.saveFailed": "Save failed",
    "songPage.deleteTitle": (gaps: { readonly title: string }) => "Delete \"" + gaps.title + "\"?",
    "songPage.deleteTakes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "songPage.deleteVersions": (count: number) => ({
        zero: numberFormat.format(count) + " versions",
        one: numberFormat.format(count) + " version",
        two: numberFormat.format(count) + " versions",
        few: numberFormat.format(count) + " versions",
        many: numberFormat.format(count) + " versions",
        other: numberFormat.format(count) + " versions",
    })[pluralRules.select(count)],
    "songPage.deleteHistory": "All scores, ratings, and chat history",
    "songPage.deleteConfirm": "Delete Song",
    "songPage.expiry": (count: number, gaps: { readonly when: string }) => ({
        zero: numberFormat.format(count) + " takes expire " + gaps.when + " — pick or keep to preserve.",
        one: numberFormat.format(count) + " take expires " + gaps.when + " — pick or keep to preserve.",
        two: numberFormat.format(count) + " takes expire " + gaps.when + " — pick or keep to preserve.",
        few: numberFormat.format(count) + " takes expire " + gaps.when + " — pick or keep to preserve.",
        many: numberFormat.format(count) + " takes expire " + gaps.when + " — pick or keep to preserve.",
        other: numberFormat.format(count) + " takes expire " + gaps.when + " — pick or keep to preserve.",
    })[pluralRules.select(count)],
    "songPage.expirySoon": "soon",
    "songPage.expiryDays": (count: number) => ({
        zero: "in " + numberFormat.format(count) + " days",
        one: "in " + numberFormat.format(count) + " day",
        two: "in " + numberFormat.format(count) + " days",
        few: "in " + numberFormat.format(count) + " days",
        many: "in " + numberFormat.format(count) + " days",
        other: "in " + numberFormat.format(count) + " days",
    })[pluralRules.select(count)],
    "songHeader.title": "Song title",
    "songHeader.editTitle": "Edit song title",
    "songHeader.albumNavigation": "Album navigation",
    "songHeader.previous": "Previous song",
    "songHeader.next": "Next song",
    "songHeader.removeCover": "Remove song cover",
    "songTabs.label": "Editor tabs",
    "songTabs.edit": "Edit",
    "songTabs.takes": "Takes",
    "songTabs.cowriter": "Co-writer",
    "writeColumn.lyrics": "Lyrics",
    "writeColumn.stylePrompt": "Style Prompt",
    "writeColumn.loadedFrom": (gaps: { readonly number: string }) => "Loaded from v" + gaps.number,
    "versions.name": (gaps: { readonly number: string }) => "v" + gaps.number,
    "versions.chipDraft": (gaps: { readonly number: string }) => "v" + gaps.number + " · draft",
    "versions.chipName": (gaps: { readonly chip: string }) => "Versions: " + gaps.chip,
    "versions.heading": "Versions",
    "versions.close": "Close versions",
    "versions.current": "current",
    "versions.picked": "picked",
    "versions.noLyrics": "No lyrics",
    "versions.noTakes": "no takes",
    "versions.takes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "versions.deleteName": (gaps: { readonly number: string }) => "Delete v" + gaps.number,
    "versions.deleteTitle": (gaps: { readonly number: string }) => "Delete v" + gaps.number + "?",
    "versions.deleteTitleTakes": (count: number, gaps: { readonly number: string }) => ({
        zero: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " takes?",
        one: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " take?",
        two: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " takes?",
        few: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " takes?",
        many: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " takes?",
        other: "Delete v" + gaps.number + " and its " + numberFormat.format(count) + " takes?",
    })[pluralRules.select(count)],
    "versions.deleteConfirm": "Delete version",
    "versions.deletePick": (count: number) => ({
        zero: "The album pick is one of them.",
        one: "It is the album pick.",
        two: "The album pick is one of them.",
        few: "The album pick is one of them.",
        many: "The album pick is one of them.",
        other: "The album pick is one of them.",
    })[pluralRules.select(count)],
    "versions.deleteDraftGoes": "Your unsaved draft goes too.",
    "versions.deleteEmptiesEditor": "Its lyrics leave the editor, which will be empty.",
    "versions.deleteLoadUndoGoes": "Undo for your earlier draft goes too.",
    "versions.deleteReplacedBy": (gaps: { readonly number: string }) => "Its lyrics leave the editor; v" + gaps.number + " replaces them.",
    "versions.deleteLoadedDraftGoes": (gaps: { readonly number: string }) => "The draft loaded from v" + gaps.number + " goes too.",
    "versions.deleteLoadedDraftReplaced": (gaps: { readonly loadedFrom: string; readonly replacedBy: string }) => "The draft loaded from v" + gaps.loadedFrom + " leaves the editor; v" + gaps.replacedBy + " replaces it.",
    "versions.deleted": (gaps: { readonly number: string }) => "Deleted v" + gaps.number,
    "versions.replaceTitle": "Replace your unsaved draft?",
    "versions.replaceMessage": (gaps: { readonly number: string }) => "Your draft has changes that are not in any version. Loading v" + gaps.number + " replaces them. You can undo right after.",
    "versions.replaceConfirm": "Replace",
    "versions.loaded": (gaps: { readonly number: string }) => "v" + gaps.number + " loaded",
    "versions.alreadyDraft": (gaps: { readonly number: string }) => "v" + gaps.number + " is already the draft",
    "versions.undo": "Undo",
    "editableTitle.hint": "Click to edit",
    "collectionHeader.titleAlbum": "album title",
    "collectionHeader.titlePlaylist": "playlist title",
    "collectionHeader.editTitleAlbum": "Edit album title",
    "collectionHeader.editTitlePlaylist": "Edit playlist title",
};
export type Key = keyof Words;
