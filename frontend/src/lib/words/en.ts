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
    readonly "playlistPage.coverAlt": (gaps: { readonly title: string }) => string;
    readonly "playlistPage.coverAltEmpty": string;
    readonly "playlistPage.loading": string;
    readonly "playlistPage.empty": string;
    readonly "playlistPage.retry": string;
    readonly "playlistPage.loadError": string;
    readonly "playlistPage.entryMore": (gaps: { readonly title: string }) => string;
    readonly "playlistPage.moveUp": string;
    readonly "playlistPage.moveDown": string;
    readonly "playlistPage.remove": string;
    readonly "playlistPage.deleted": string;
    readonly "playlistPage.deleteFailed": string;
    readonly "playlistPage.renameFailed": string;
    readonly "playlistPage.coverSaved": string;
    readonly "playlistPage.coverSaveFailed": string;
    readonly "playlistPage.coverRemoved": string;
    readonly "playlistPage.coverRemoveFailed": string;
    readonly "playlistPage.removeFailed": string;
    readonly "playlistPage.reorderFailed": string;
    readonly "playlistPage.deleteTitle": (gaps: { readonly title: string }) => string;
    readonly "playlistPage.songCount": (count: number) => string;
    readonly "playlistPage.deleteConfirm": string;
    readonly "playlistPicker.label": string;
    readonly "playlistPicker.heading": string;
    readonly "playlistPicker.loading": string;
    readonly "playlistPicker.error": string;
    readonly "playlistPicker.retry": string;
    readonly "playlistPicker.newPlaceholder": string;
    readonly "playlistPicker.add": string;
    readonly "playlistPicker.createFailed": string;
    readonly "songRow.openInEditor": (gaps: { readonly title: string }) => string;
    readonly "homeWrite.openInEditor": (gaps: { readonly title: string }) => string;
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
    readonly "recipe.panel": string;
    readonly "recipe.panelChanged": string;
    readonly "recipe.tabsLabel": string;
    readonly "recipe.close": string;
    readonly "recipe.tabSong": string;
    readonly "recipe.tabGenerate": string;
    readonly "recipe.tabEngine": string;
    readonly "recipe.savedWithVersion": string;
    readonly "recipe.resetAll": string;
    readonly "recipe.resetAuto": string;
    readonly "recipe.resetEmpty": string;
    readonly "recipe.resetNone": string;
    readonly "recipe.resetReference": string;
    readonly "recipe.resetModel": string;
    readonly "recipe.resetTakes": string;
    readonly "recipe.resetPreset": string;
    readonly "recipe.bpm": string;
    readonly "recipe.duration": string;
    readonly "recipe.key": string;
    readonly "recipe.auto": string;
    readonly "recipe.empty": string;
    readonly "recipe.none": string;
    readonly "recipe.model": string;
    readonly "recipe.modelLoading": string;
    readonly "recipe.modelLoaded": string;
    readonly "recipe.takes": string;
    readonly "recipe.retry": string;
    readonly "recipe.defaultsError": string;
    readonly "recipe.engineEmptyHint": string;
    readonly "recipe.preset": string;
    readonly "recipe.presetDefault": string;
    readonly "recipe.presetCustom": string;
    readonly "recipe.presetShared": (gaps: { readonly name: string }) => string;
    readonly "recipe.presetNamePlaceholder": string;
    readonly "recipe.presetSave": string;
    readonly "recipe.presetCancel": string;
    readonly "recipe.presetSaveError": string;
    readonly "recipe.saveAsPreset": string;
    readonly "recipe.managePresets": string;
    readonly "referencePicker.label": string;
    readonly "referencePicker.chosen": (gaps: { readonly name: string }) => string;
    readonly "referencePicker.none": string;
    readonly "referencePicker.play": (gaps: { readonly name: string }) => string;
    readonly "referencePicker.pause": (gaps: { readonly name: string }) => string;
    readonly "referencePicker.loading": string;
    readonly "referencePicker.loadError": string;
    readonly "referencePicker.playError": string;
    readonly "referencePicker.retry": string;
    readonly "referencePicker.upload": string;
    readonly "referencePicker.uploading": string;
    readonly "referencePicker.uploadError": string;
    readonly "referencePicker.all": string;
    readonly "voicePicker.label": string;
    readonly "voicePicker.mobileLabel": (gaps: { readonly mode: string }) => string;
    readonly "voicePicker.none": string;
    readonly "voicePicker.create": string;
    readonly "voicePicker.stateNotForModel": string;
    readonly "voicePicker.stateDeleted": string;
    readonly "voicePicker.stateDraft": string;
    readonly "voicePicker.stateTraining": string;
    readonly "voicePicker.stateFailed": string;
    readonly "voicePicker.chosenUnavailable": (gaps: { readonly name: string; readonly state: string }) => string;
    readonly "voicePicker.optionUnavailable": (gaps: { readonly state: string }) => string;
    readonly "referenceExpiry.deletesOn": (gaps: { readonly date: string }) => string;
    readonly "referenceExpiry.daysLeft": (count: number) => string;
    readonly "paramField.inferenceSteps": string;
    readonly "paramField.guidanceScale": string;
    readonly "paramField.shift": string;
    readonly "paramField.cfgIntervalStart": string;
    readonly "paramField.cfgIntervalEnd": string;
    readonly "paramField.velocityNorm": string;
    readonly "paramField.velocityEma": string;
    readonly "paramField.latentShift": string;
    readonly "paramField.latentRescale": string;
    readonly "paramField.lmCodeStrength": string;
    readonly "paramField.inferMethod": string;
    readonly "paramField.sampler": string;
    readonly "paramField.adaptiveDualGuidance": string;
    readonly "paramField.temperature": string;
    readonly "paramField.topK": string;
    readonly "paramField.topP": string;
    readonly "paramField.cfgScale": string;
    readonly "paramField.repetitionPenalty": string;
    readonly "paramField.batchSize": string;
    readonly "paramField.thinking": string;
    readonly "paramField.cotCaption": string;
    readonly "paramField.cotLanguage": string;
    readonly "paramField.negativePrompt": string;
    readonly "paramField.negativePromptPlaceholder": string;
    readonly "paramField.sectionDit": string;
    readonly "paramField.sectionLm": string;
    readonly "paramField.defaultOption": string;
    readonly "paramField.defaultOptionValue": (gaps: { readonly value: string }) => string;
    readonly "paramField.defaultMissing": (gaps: { readonly key: string }) => string;
    readonly "paramField.resetTitle": string;
    readonly "paramField.resetLabel": (gaps: { readonly field: string }) => string;
    readonly "voiceRefusal.deleted": string;
    readonly "voiceRefusal.modifyDuringTraining": (gaps: { readonly status: string }) => string;
    readonly "voiceRefusal.deleteDuringTraining": (gaps: { readonly status: string }) => string;
    readonly "voiceRefusal.alreadyTraining": (gaps: { readonly status: string }) => string;
    readonly "voiceRefusal.notReady": (gaps: { readonly status: string }) => string;
    readonly "voiceRefusal.nameRequired": string;
    readonly "voiceRefusal.limit": (gaps: { readonly limit: string }) => string;
    readonly "voiceRefusal.slugConflict": (gaps: { readonly name: string }) => string;
    readonly "voiceRefusal.sampleLimit": (gaps: { readonly maximum: string }) => string;
    readonly "voiceRefusal.captionRequired": string;
    readonly "voiceRefusal.lyricsRequired": string;
    readonly "voiceRefusal.captionEmpty": string;
    readonly "voiceRefusal.lyricsEmpty": string;
    readonly "voiceRefusal.unsupportedFormat": (gaps: { readonly accepted: string; readonly extension: string }) => string;
    readonly "voiceRefusal.fileTooLarge": (gaps: { readonly maxMb: string }) => string;
    readonly "voiceRefusal.fileEmpty": string;
    readonly "voiceRefusal.tooFewSamples": (gaps: { readonly have: string; readonly minimum: string }) => string;
    readonly "voiceRefusal.samplesIncomplete": string;
    readonly "voiceRefusal.trainingQueueFull": (gaps: { readonly waiting: string }) => string;
    readonly "generationRefusal.sourceNoAudio": string;
    readonly "generationRefusal.ffmpegMissing": string;
    readonly "generationRefusal.wavConversionFailed": string;
    readonly "generationRefusal.noLinkedVersion": string;
    readonly "generationRefusal.needsLyricsAndPrompt": string;
    readonly "generationRefusal.repaintRange": string;
    readonly "generationRefusal.workerNotRunning": string;
    readonly "jobRefusal.queueUnavailable": string;
    readonly "jobRefusal.queueFull": string;
    readonly "jobRefusal.activeJob": string;
    readonly "jobRefusal.hourlyLimit": (gaps: { readonly jobType: string; readonly limit: string }) => string;
    readonly "cowriterRefusal.browserLogin": string;
    readonly "cowriterRefusal.turnRunning": string;
    readonly "cowriterRefusal.takeNotInSong": string;
    readonly "takeRefusal.notPlayable": string;
    readonly "settingsRefusal.modelUnavailable": (gaps: { readonly mode: string }) => string;
    readonly "settingsRefusal.invalidDefaultConfig": string;
    readonly "settingsRefusal.tailBudgetRange": (gaps: { readonly maximum: string; readonly minimum: string }) => string;
    readonly "settingsRefusal.unknownKeys": (gaps: { readonly keys: string }) => string;
    readonly "settingsRefusal.negativeValue": (gaps: { readonly key: string }) => string;
    readonly "presetRefusal.nameTaken": string;
    readonly "adminRefusal.unknownModelMode": (gaps: { readonly mode: string }) => string;
    readonly "adminRefusal.noOnlineWorkers": string;
    readonly "adminRefusal.alreadyDownloaded": (gaps: { readonly mode: string }) => string;
    readonly "adminRefusal.alreadyDownloading": (gaps: { readonly jobId: string; readonly mode: string }) => string;
    readonly "workerRefusal.unreachable": (gaps: { readonly reason: string }) => string;
    readonly "workerRefusal.relayed": (gaps: { readonly cause: string }) => string;
    readonly "workerRefusal.notResponding": (gaps: { readonly workerId: string }) => string;
    readonly "workerRefusal.returnedStatus": (gaps: { readonly status: string }) => string;
    readonly "coverRefusal.tooLarge": string;
    readonly "coverRefusal.unreadable": string;
    readonly "coverRefusal.unsupportedType": string;
    readonly "coverRefusal.tooManyPixels": string;
    readonly "coverRefusal.variantUnknown": string;
    readonly "coverRefusal.invalidAlbumId": string;
    readonly "coverRefusal.invalidSongId": string;
    readonly "coverRefusal.invalidPlaylistId": string;
    readonly "coverSuggestionRefusal.alreadyRunning": string;
    readonly "referenceRefusal.quotaReached": string;
    readonly "referenceRefusal.storage": string;
    readonly "albumRefusal.restoreWindowPassed": (gaps: { readonly days: string; readonly id: string; readonly window: string }) => string;
    readonly "songRefusal.restoreWindowPassed": (gaps: { readonly days: string; readonly id: string; readonly window: string }) => string;
    readonly "takesList.loading": string;
    readonly "takesList.error": string;
    readonly "takesList.retry": string;
    readonly "takesList.aboutTakes": string;
    readonly "takesList.mobileHint": string;
    readonly "takesList.empty": (gaps: { readonly generate: string }) => string;
    readonly "takesList.draftUnsaved": (gaps: { readonly next: string }) => string;
    readonly "takesList.draftDiffers": (gaps: { readonly latest: string; readonly next: string }) => string;
    readonly "takesList.openVersion": (gaps: { readonly number: string }) => string;
    readonly "takesList.currentHead": (count: number, gaps: { readonly number: string }) => string;
    readonly "takesList.foldedVersion": (count: number, gaps: { readonly number: string }) => string;
    readonly "takesList.foldedImported": (count: number) => string;
    readonly "takesList.foldedVersionArchived": (count: number, gaps: { readonly archived: string; readonly number: string }) => string;
    readonly "takesList.foldedImportedArchived": (count: number, gaps: { readonly archived: string }) => string;
    readonly "takesList.allArchived": string;
    readonly "takesList.earlier": string;
    readonly "takesList.takeLabel": (gaps: { readonly number: string }) => string;
    readonly "takesList.selectAllUnkept": string;
    readonly "takesList.selectedCount": (count: number) => string;
    readonly "takesList.bulkDeleteLabel": (count: number) => string;
    readonly "takesList.bulkDeleteTitle": (count: number) => string;
    readonly "takesList.cancel": string;
    readonly "takesList.deleteTitle": (gaps: { readonly number: string }) => string;
    readonly "takesList.deleteMessage": string;
    readonly "takesList.deleteConfirm": string;
    readonly "takesList.deleted": (count: number) => string;
    readonly "takesList.bulkDeleteFailed": string;
    readonly "takesList.addedToPlaylist": string;
    readonly "takesList.addFailed": string;
    readonly "takeRow.takeLabel": (gaps: { readonly number: string }) => string;
    readonly "takeRow.takeVersioned": (gaps: { readonly take: string; readonly version: string }) => string;
    readonly "takeRow.takeUnversioned": (gaps: { readonly take: string }) => string;
    readonly "takeRow.archivedTitle": string;
    readonly "takeRow.selectTake": (gaps: { readonly take: string }) => string;
    readonly "takeRow.playTake": (gaps: { readonly action: string; readonly take: string }) => string;
    readonly "takeRow.pickTake": (gaps: { readonly take: string }) => string;
    readonly "takeRow.unpickTake": (gaps: { readonly take: string }) => string;
    readonly "takeRow.keepTake": (gaps: { readonly take: string }) => string;
    readonly "takeRow.unkeepTake": (gaps: { readonly take: string }) => string;
    readonly "takeRow.provenanceRepaint": (gaps: { readonly take: string }) => string;
    readonly "takeRow.provenanceCover": (gaps: { readonly take: string }) => string;
    readonly "takeRow.batchBadge": (gaps: { readonly delivered: string; readonly requested: string }) => string;
    readonly "takeRow.batchTitle": (gaps: { readonly delivered: string; readonly requested: string }) => string;
    readonly "takeRow.flagNoVocals": string;
    readonly "takeRow.flagNoVocalsTitle": string;
    readonly "takeRow.flagLongSilence": string;
    readonly "takeRow.flagLongSilenceTitle": (gaps: { readonly count: number }) => string;
    readonly "takeRow.rescoring": string;
    readonly "takeRow.archived": string;
    readonly "takeRow.archivedBadgeTitle": string;
    readonly "takeRow.expiryBadge": (gaps: { readonly count: number }) => string;
    readonly "takeRow.expiresIn": (count: number) => string;
    readonly "takeRow.voice": (gaps: { readonly name: string }) => string;
    readonly "takeRow.voiceDeleted": (gaps: { readonly name: string }) => string;
    readonly "takeRow.scoreTitle": (gaps: { readonly metric: string; readonly value: string }) => string;
    readonly "takeRow.scoreRating": string;
    readonly "takeRow.scoreLyricsSung": string;
    readonly "takeRow.scoreDynamics": string;
    readonly "takeRow.scoreQuality": string;
    readonly "takeRow.scoreEnjoyment": string;
    readonly "takeRow.scoreCoherence": string;
    readonly "takeTask.repaint": string;
    readonly "takeTask.cover": string;
    readonly "takeTask.close": string;
    readonly "takeTask.closeTitle": string;
    readonly "takeTask.fromTake": (gaps: { readonly number: string }) => string;
    readonly "takeTask.detailVersioned": (gaps: { readonly duration: string; readonly version: string }) => string;
    readonly "takeTask.detail": (gaps: { readonly duration: string }) => string;
    readonly "takeTask.range": string;
    readonly "takeTask.rangeCaption": string;
    readonly "takeTask.repaintAmount": string;
    readonly "takeTask.modeConservative": string;
    readonly "takeTask.modeBalanced": string;
    readonly "takeTask.modeAggressive": string;
    readonly "takeTask.repaintStrength": string;
    readonly "takeTask.strengthValue": (gaps: { readonly count: number }) => string;
    readonly "takeTask.coverCloseness": (gaps: { readonly number: string }) => string;
    readonly "takeTask.coverFree": string;
    readonly "takeTask.coverStrict": string;
    readonly "takeTask.coverStrength": string;
    readonly "takeTask.noise": string;
    readonly "takeTask.noiseCaption": string;
    readonly "takeTask.noiseBound": (gaps: { readonly count: number }) => string;
    readonly "takeTask.promptHint": string;
    readonly "takeTask.seedLine": (gaps: { readonly number: string }) => string;
    readonly "takeTask.landing": (gaps: { readonly number: string }) => string;
    readonly "takeTask.headerNote": string;
    readonly "takeTask.repaintPress": (gaps: { readonly end: string; readonly start: string }) => string;
    readonly "seedChip.label": (gaps: { readonly number: string }) => string;
    readonly "seedChip.clear": string;
    readonly "takeActions.pickFailed": string;
    readonly "takeActions.keepFailed": string;
    readonly "takeActions.restoreFailed": string;
    readonly "takeActions.ratingSaved": string;
    readonly "takeActions.ratingFailed": string;
    readonly "takeActions.rescoreQueued": string;
    readonly "takeActions.rescoreFailed": string;
    readonly "takeActions.useSeed": (gaps: { readonly number: string }) => string;
    readonly "nowPlayingTake.label": (gaps: { readonly number: string }) => string;
    readonly "nowPlayingTake.importedHeading": string;
    readonly "nowPlayingTake.heading": (gaps: { readonly take: string; readonly version: string }) => string;
    readonly "nowPlayingTake.headingDuration": (gaps: { readonly duration: string; readonly take: string; readonly version: string }) => string;
    readonly "nowPlayingTake.headingMode": (gaps: { readonly mode: string; readonly take: string; readonly version: string }) => string;
    readonly "nowPlayingTake.headingDurationMode": (gaps: { readonly duration: string; readonly mode: string; readonly take: string; readonly version: string }) => string;
    readonly "nowPlayingTake.openVersion": (gaps: { readonly number: string }) => string;
    readonly "nowPlayingTake.pick": string;
    readonly "nowPlayingTake.unpick": string;
    readonly "nowPlayingTake.keep": string;
    readonly "nowPlayingTake.unkeep": string;
    readonly "nowPlayingTake.scores": string;
    readonly "nowPlayingTake.scoresEmpty": string;
    readonly "nowPlayingTake.scoreRating": string;
    readonly "nowPlayingTake.scoreLyricsSung": string;
    readonly "nowPlayingTake.scoreDynamics": string;
    readonly "nowPlayingTake.scoreQuality": string;
    readonly "nowPlayingTake.scoreEnjoyment": string;
    readonly "nowPlayingTake.scoreCoherence": string;
    readonly "nowPlayingTake.scoreBpm": string;
    readonly "nowPlayingTake.deviations": string;
    readonly "nowPlayingTake.deviationsEmpty": string;
    readonly "nowPlayingTake.deviationsUnavailable": string;
    readonly "nowPlayingTake.lyricsRow": (gaps: { readonly lyrics: string }) => string;
    readonly "nowPlayingTake.deviationAddedTitle": string;
    readonly "nowPlayingTake.deviationAdded": (gaps: { readonly value: string }) => string;
    readonly "nowPlayingTake.rescoreAction": string;
    readonly "nowPlayingTake.rescoring": string;
    readonly "nowPlayingTake.rescore": string;
    readonly "nowPlayingTake.recipe": string;
    readonly "nowPlayingTake.rating": string;
    readonly "nowPlayingTake.ratingNotes": string;
    readonly "nowPlayingTake.ratingSave": string;
    readonly "nowPlayingTake.ratingSaving": string;
    readonly "nowPlayingTake.useSeed": string;
    readonly "nowPlayingTake.repaint": string;
    readonly "nowPlayingTake.cover": string;
    readonly "takeRecipe.groupModel": string;
    readonly "takeRecipe.groupReproducibility": string;
    readonly "takeRecipe.groupVersion": string;
    readonly "takeRecipe.groupOther": string;
    readonly "takeRecipe.model": string;
    readonly "takeRecipe.deliveredBatchSize": string;
    readonly "takeRecipe.seed": string;
    readonly "takeRecipe.requestedSeed": string;
    readonly "takeRecipe.bpm": string;
    readonly "takeRecipe.duration": string;
    readonly "takeRecipe.key": string;
    readonly "takeRecipe.language": string;
    readonly "takeRecipe.on": string;
    readonly "takeRecipe.off": string;
    readonly "albumRefusal.notFound": string;
    readonly "albumRefusal.titleRequired": string;
    readonly "albumRefusal.idConflict": (gaps: { readonly title: string }) => string;
    readonly "songRefusal.notFound": string;
    readonly "songRefusal.titleRequired": string;
    readonly "songRefusal.titleTooLong": string;
    readonly "songRefusal.moveTargetMissing": string;
    readonly "songRefusal.restoreAlbumDeleted": (gaps: { readonly id: string }) => string;
    readonly "songRefusal.notPlayable": string;
    readonly "songRefusal.playlistLacksSong": string;
    readonly "songRefusal.referenceMissing": string;
    readonly "versionRefusal.notFound": string;
    readonly "versionRefusal.inUse": string;
    readonly "playlistRefusal.notFound": string;
    readonly "playlistRefusal.entryNotFound": string;
    readonly "playlistRefusal.songNotPlayable": string;
    readonly "coverSuggestionRefusal.notFound": string;
    readonly "coverSuggestionRefusal.nothingNamed": string;
    readonly "coverSuggestionRefusal.browserLogin": string;
    readonly "shareRefusal.personsAgent": string;
    readonly "libraryRefusal.queryRequired": string;
    readonly "cowriter.title": string;
    readonly "cowriter.thinking": string;
    readonly "cowriter.conversationMenu": string;
    readonly "cowriter.conversationMenuWaiting": string;
    readonly "cowriter.composerPlaceholder": string;
    readonly "cowriter.send": string;
    readonly "cowriter.newConversation": string;
    readonly "cowriter.memory": string;
    readonly "cowriter.memoryWaiting": string;
    readonly "cowriter.deleteConversationTitle": string;
    readonly "cowriter.deleteConversationWarning": string;
    readonly "cowriter.deleteConversation": string;
    readonly "cowriter.newConversationLine": string;
    readonly "cowriter.lineSince": (gaps: { readonly day: string }) => string;
    readonly "cowriter.lineArchived": (gaps: { readonly day: string }) => string;
    readonly "cowriter.conversationSince": (gaps: { readonly day: string; readonly time: string }) => string;
    readonly "cowriter.archivedRow": (gaps: { readonly day: string; readonly time: string }) => string;
    readonly "cowriter.confirmRow": (gaps: { readonly messages: string; readonly name: string }) => string;
    readonly "cowriter.messageCount": (count: number) => string;
    readonly "cowriter.today": string;
    readonly "cowriter.toolRan": (gaps: { readonly name: string }) => string;
    readonly "cowriter.toolTarget": (gaps: { readonly title: string }) => string;
    readonly "cowriter.toolForeignTarget": string;
    readonly "cowriter.historyUnavailable": string;
    readonly "cowriter.loadingChat": string;
    readonly "cowriter.startFailed": string;
    readonly "cowriter.deleteFailed": string;
    readonly "cowriter.archivedToast": string;
    readonly "cowriter.archivedBanner": readonly (string | { readonly marker: "link"; readonly text: string })[];
    readonly "cowriter.albumFallback": string;
    readonly "cowriter.noMatches": string;
    readonly "cowriter.memoryUnavailable": string;
    readonly "cowriter.memorySaveFailed": string;
    readonly "cowriter.proposalStale": string;
    readonly "memory.close": string;
    readonly "memory.loading": string;
    readonly "memory.you": string;
    readonly "memory.thisSong": string;
    readonly "memory.albumNotes": string;
    readonly "memory.hintUser": string;
    readonly "memory.hintSong": string;
    readonly "memory.hintAlbum": string;
    readonly "memory.proposedUser": string;
    readonly "memory.proposedSong": string;
    readonly "memory.proposedAlbum": string;
    readonly "memory.accept": string;
    readonly "memory.reject": string;
    readonly "memory.userField": string;
    readonly "memory.songField": string;
    readonly "memory.albumField": string;
    readonly "memory.save": string;
    readonly "memory.saving": string;
    readonly "cowriter.emptyHint": string;
    readonly "shareStatus.loadingAlbum": string;
    readonly "shareStatus.loadingPlaylist": string;
    readonly "shareStatus.loadingSong": string;
    readonly "shareStatus.loadingTake": string;
    readonly "shareStatus.notFoundAlbum": string;
    readonly "shareStatus.notFoundPlaylist": string;
    readonly "shareStatus.notFoundSong": string;
    readonly "shareStatus.notFoundTake": string;
    readonly "shareStatus.errorAlbum": string;
    readonly "shareStatus.errorPlaylist": string;
    readonly "shareStatus.errorSong": string;
    readonly "shareStatus.errorTake": string;
    readonly "shareStatus.errorBodyAlbum": string;
    readonly "shareStatus.errorBodyPlaylist": string;
    readonly "shareStatus.errorBodySong": string;
    readonly "shareStatus.errorBodyTake": string;
    readonly "shareStatus.invalidLink": string;
    readonly "shareStatus.openApp": (gaps: { readonly app: string }) => string;
    readonly "shareStatus.retry": string;
    readonly "shareAlbumPage.documentTitle": (gaps: { readonly app: string; readonly artist: string; readonly title: string }) => string;
    readonly "shareAlbumPage.fallbackTitle": (gaps: { readonly app: string }) => string;
    readonly "sharePlaylistPage.documentTitle": (gaps: { readonly app: string; readonly title: string }) => string;
    readonly "sharePlaylistPage.fallbackTitle": (gaps: { readonly app: string }) => string;
    readonly "shareSongPage.documentTitle": (gaps: { readonly app: string; readonly artist: string; readonly title: string }) => string;
    readonly "shareSongPage.fallbackTitle": (gaps: { readonly app: string }) => string;
    readonly "shareTakePage.documentTitle": (gaps: { readonly app: string; readonly number: string; readonly title: string }) => string;
    readonly "shareTakePage.fallbackTitle": (gaps: { readonly app: string }) => string;
    readonly "share.nowPlaying": (gaps: { readonly position: string; readonly title: string; readonly total: string }) => string;
    readonly "share.albumSubtitle": (gaps: { readonly artist: string }) => string;
    readonly "share.albumSubtitleNoArtist": string;
    readonly "share.playlistSubtitle": (count: number) => string;
    readonly "share.noLyrics": string;
    readonly "share.noAudio": string;
    readonly "share.backToPlayer": string;
    readonly "share.songs": string;
    readonly "shareButton.copyFailedToast": string;
    readonly "shareButton.copiedToast": string;
    readonly "shareButton.unsharedToast": string;
    readonly "shareButton.failedToast": string;
    readonly "shareButton.fallbackTitle": string;
    readonly "shareButton.songLabel": string;
    readonly "shareToggle.sharedTooltip": (gaps: { readonly path: string }) => string;
    readonly "shareLink.copiedToast": string;
    readonly "shareLink.copyFailedToast": string;
    readonly "shareDialog.title": string;
    readonly "shareDialog.intro": string;
    readonly "shareDialog.close": string;
    readonly "libraryShares.copyLink": string;
    readonly "legal.imprint": string;
    readonly "legal.privacy": string;
    readonly "legal.terms": string;
    readonly "account.menu": (gaps: { readonly username: string }) => string;
    readonly "account.menuClose": string;
    readonly "account.signOutFailed": string;
    readonly "auth.loading": string;
    readonly "auth.retry": string;
    readonly "auth.checkRateLimited": string;
    readonly "auth.checkServerError": string;
    readonly "auth.checkNetworkError": string;
    readonly "referenceRefusal.notFound": string;
    readonly "referenceRefusal.noFilename": string;
    readonly "referenceRefusal.filenameInvalid": string;
    readonly "referenceRefusal.filenameTooLong": (gaps: { readonly max: string }) => string;
    readonly "referenceRefusal.formatUnsupported": (gaps: { readonly accepted: string; readonly extension: string }) => string;
    readonly "referenceRefusal.fileTooLarge": (gaps: { readonly max: string }) => string;
    readonly "referenceRefusal.fileTooSmall": string;
    readonly "referenceRefusal.inUse": string;
    readonly "referenceRefusal.countdownStale": string;
    readonly "jobRefusal.notFound": string;
    readonly "jobRefusal.notCancellable": string;
    readonly "libraryQueueRefusal.startUnplayable": string;
    readonly "libraryQueueRefusal.emptyPool": (gaps: { readonly pool: string }) => string;
    readonly "libraryQueueRefusal.emptyWindow": string;
    readonly "libraryQueueRefusal.tooManyRequests": string;
    readonly "libraryQueueRefusal.limiterUnavailable": string;
    readonly "libraryRefusal.cursorInvalid": string;
    readonly "libraryRefusal.cursorMismatch": string;
    readonly "connectivity.offlineStrip": string;
    readonly "resourceSync.error": string;
    readonly "http.rateLimited": string;
    readonly "http.genericError": string;
    readonly "navigation.songLinkNotFound": string;
    readonly "dialog.cancel": string;
    readonly "dialog.confirm": string;
    readonly "toast.dismiss": string;
    readonly "loading.plain": string;
    readonly "adminPage.heading": string;
    readonly "adminPage.accessRequired": string;
    readonly "adminPage.sections": string;
    readonly "adminPage.tabVoices": string;
    readonly "adminPage.tabRateLimits": string;
    readonly "adminPage.tabGeneration": string;
    readonly "adminPage.tabModels": string;
    readonly "adminPage.tabAcestep": string;
    readonly "adminPage.tabCleanup": string;
    readonly "adminPage.saving": string;
    readonly "adminPage.saveDefaults": string;
    readonly "adminPage.saveFailed": string;
    readonly "adminVoices.heading": string;
    readonly "adminVoices.loading": string;
    readonly "adminVoices.empty": string;
    readonly "adminVoices.loadFailed": string;
    readonly "adminVoices.columnVoice": string;
    readonly "adminVoices.columnOwner": string;
    readonly "adminVoices.columnStatus": string;
    readonly "rateLimits.heading": string;
    readonly "rateLimits.hint": string;
    readonly "rateLimits.generations": string;
    readonly "rateLimits.scorings": string;
    readonly "rateLimits.maxQueueDepth": string;
    readonly "rateLimits.maxActiveJobs": string;
    readonly "rateLimits.loadFailed": string;
    readonly "generationDefaults.heading": string;
    readonly "generationDefaults.hint": string;
    readonly "generationDefaults.reset": string;
    readonly "generationDefaults.loadFailed": string;
    readonly "generationDefaults.saveFailed": string;
    readonly "availableModels.heading": string;
    readonly "availableModels.hint": string;
    readonly "availableModels.on": string;
    readonly "availableModels.off": string;
    readonly "availableModels.toggleFailed": string;
    readonly "modelsTable.heading": string;
    readonly "modelsTable.columnTask": string;
    readonly "modelsTable.columnProvider": string;
    readonly "modelsTable.columnRoute": string;
    readonly "modelsTable.columnModel": string;
    readonly "modelsTable.columnStatus": string;
    readonly "modelsTable.taskCowriter": string;
    readonly "modelsTable.taskCover": string;
    readonly "modelsTable.setByAgentFile": string;
    readonly "modelsTable.routeGateway": string;
    readonly "modelsTable.advanced": string;
    readonly "modelsTable.historyTail": string;
    readonly "modelsTable.saved": string;
    readonly "modelsTable.retry": string;
    readonly "modelsTable.saveFailed": string;
    readonly "modelsTable.loading": string;
    readonly "modelsTable.unavailable": string;
    readonly "modelsTable.loadFailed": string;
    readonly "recipe.modelsLoadFailed": string;
    readonly "workerPool.heading": string;
    readonly "workerPool.loadFailed": string;
    readonly "workerPool.refreshFailed": string;
    readonly "workerPool.noWorkers": (gaps: { readonly container: string }) => readonly (string | { readonly marker: "code"; readonly text: string })[];
    readonly "workerPool.cardHeader": (gaps: { readonly gpu: string; readonly vram: string }) => string;
    readonly "workerPool.vramTotal": (gaps: { readonly total: string }) => string;
    readonly "workerPool.statusLabel": string;
    readonly "workerPool.logLabel": string;
    readonly "workerPool.queueLabel": string;
    readonly "workerPool.lastSeenLabel": string;
    readonly "workerPool.queueJobs": (count: number) => string;
    readonly "workerPool.loadingSpinner": string;
    readonly "workerPool.statusLoading": (gaps: { readonly mode: string }) => string;
    readonly "workerPool.statusLoadingElapsed": (gaps: { readonly elapsed: string; readonly mode: string }) => string;
    readonly "workerPool.statusTraining": (gaps: { readonly seconds: string }) => string;
    readonly "workerPool.statusNoModel": string;
    readonly "workerPool.statusBusy": (gaps: { readonly count: number }) => string;
    readonly "workerPool.statusIdle": string;
    readonly "workerPool.offlineSince": (gaps: { readonly lastSeen: string }) => string;
    readonly "workerPool.gpuUnavailableDetail": (gaps: { readonly detail: string }) => string;
    readonly "workerPool.gpuUnavailable": string;
    readonly "workerPool.gpuHealthNotReported": string;
    readonly "workerPool.restartNoProcess": (gaps: { readonly worker: string }) => string;
    readonly "workerPool.restartBrokenGpu": (gaps: { readonly worker: string }) => string;
    readonly "workerPool.restartNoGpuHealth": (gaps: { readonly worker: string }) => string;
    readonly "workerPool.seenNever": string;
    readonly "workerPool.seenJustNow": string;
    readonly "workerPool.secondsAgo": (gaps: { readonly count: number }) => string;
    readonly "workerPool.minutesAgo": (gaps: { readonly count: number }) => string;
    readonly "workerPool.hoursAgo": (gaps: { readonly count: number }) => string;
    readonly "workerPool.daysAgo": (gaps: { readonly count: number }) => string;
    readonly "workerPool.elapsedSeconds": (gaps: { readonly seconds: string }) => string;
    readonly "workerPool.elapsedMinutes": (gaps: { readonly minutes: string; readonly seconds: string }) => string;
    readonly "workerPool.elapsedHours": (gaps: { readonly hours: string; readonly minutes: string }) => string;
    readonly "workerPool.loadModel": string;
    readonly "workerPool.load": string;
    readonly "workerPool.loadingAction": string;
    readonly "workerPool.selectModel": string;
    readonly "workerPool.enqueueFailed": string;
    readonly "workerPool.unloadFailed": string;
    readonly "workerPool.restartFailed": string;
    readonly "workerPool.keepLoadedFailed": string;
    readonly "workerPool.loadingToast": (gaps: { readonly mode: string; readonly worker: string }) => string;
    readonly "workerPool.unloadedToast": (gaps: { readonly mode: string; readonly worker: string }) => string;
    readonly "workerPool.restartRequested": (gaps: { readonly worker: string }) => string;
    readonly "workerPool.keepLoadedOff": (gaps: { readonly mode: string; readonly worker: string }) => string;
    readonly "workerPool.keepLoadedOn": (gaps: { readonly mode: string; readonly worker: string }) => string;
    readonly "workerPool.lastError": string;
    readonly "workerPool.fullLogs": (gaps: { readonly command: string }) => readonly (string | { readonly marker: "code"; readonly text: string })[];
    readonly "workerPool.restart": string;
    readonly "workerPool.restarting": string;
    readonly "workerPool.restartTitle": (gaps: { readonly worker: string }) => string;
    readonly "workerPool.restartWarning": string;
    readonly "workerPool.restartConfirm": string;
    readonly "workerPool.models": string;
    readonly "workerPool.modelsLoading": (gaps: { readonly mode: string }) => string;
    readonly "workerPool.modelsOffline": string;
    readonly "workerPool.keepLoaded": string;
    readonly "workerPool.keepLoadedHint": string;
    readonly "workerPool.keepLoadedModel": (gaps: { readonly mode: string }) => string;
    readonly "workerPool.unload": string;
    readonly "workerPool.unloadModel": (gaps: { readonly mode: string }) => string;
    readonly "workerPool.modelSize": (gaps: { readonly size: string }) => string;
    readonly "workerPool.vram": string;
    readonly "workerPool.vramLabel": string;
    readonly "workerPool.vramUsed": (gaps: { readonly total: string; readonly used: string }) => string;
    readonly "workerPool.vramUsedEstimated": (gaps: { readonly total: string; readonly used: string }) => string;
    readonly "workerPool.vramFree": (gaps: { readonly free: string }) => string;
    readonly "workerPool.vramEstimateReason": string;
    readonly "workerPool.vramUnknown": string;
    readonly "workerPool.vramOffline": string;
    readonly "workerPool.vramNoHeartbeat": string;
    readonly "workerPool.vramNoTotal": string;
    readonly "workerPool.vramNoFields": string;
    readonly "modelRegistry.heading": string;
    readonly "modelRegistry.loading": string;
    readonly "modelRegistry.loadFailed": string;
    readonly "modelRegistry.columnMode": string;
    readonly "modelRegistry.columnStatus": string;
    readonly "modelRegistry.columnLoaded": string;
    readonly "modelRegistry.columnLoading": string;
    readonly "modelRegistry.columnActions": string;
    readonly "modelRegistry.downloaded": string;
    readonly "modelRegistry.stateUnknown": string;
    readonly "modelRegistry.notDownloaded": string;
    readonly "modelRegistry.downloadingProgress": (gaps: { readonly percent: string }) => string;
    readonly "modelRegistry.noWorkerOnline": string;
    readonly "modelRegistry.starting": string;
    readonly "modelRegistry.download": string;
    readonly "modelRegistry.connectionLost": string;
    readonly "modelRegistry.downloadingToast": (gaps: { readonly mode: string }) => string;
    readonly "modelRegistry.downloadFailed": string;
    readonly "takeRetention.heading": string;
    readonly "takeRetention.explanation": string;
    readonly "takeRetention.whatThisDoes": string;
    readonly "takeRetention.schedule": (gaps: { readonly hour: string }) => string;
    readonly "takeRetention.loading": string;
    readonly "takeRetention.days": (count: number) => string;
    readonly "takeRetention.archiveAfter": string;
    readonly "takeRetention.hardDeleteAfter": string;
    readonly "takeRetention.toArchive": string;
    readonly "takeRetention.toHardDelete": string;
    readonly "takeRetention.nothingDue": string;
    readonly "takeRetention.refresh": string;
    readonly "takeRetention.runNow": string;
    readonly "takeRetention.confirm": (count: number, gaps: { readonly deleted: string }) => readonly (string | { readonly marker: "strong"; readonly text: string })[];
    readonly "takeRetention.cancel": string;
    readonly "takeRetention.running": string;
    readonly "takeRetention.delete": (gaps: { readonly count: number }) => string;
    readonly "takeRetention.previewFailed": string;
    readonly "takeRetention.runFailed": string;
    readonly "takeRetention.outcome": (gaps: { readonly archived: string; readonly deleted: string }) => string;
    readonly "generationRefusal.notFound": string;
    readonly "generationRefusal.someNotFound": string;
    readonly "generationRefusal.audioMissing": string;
    readonly "voiceRefusal.notFound": string;
    readonly "voiceRefusal.sampleNotFound": string;
    readonly "conversationRefusal.notFound": string;
    readonly "presetRefusal.notFound": string;
    readonly "modelRefusal.notFound": string;
    readonly "workerRefusal.notFound": (gaps: { readonly workerId: string }) => string;
    readonly "voicesPage.documentTitle": (gaps: { readonly app: string }) => string;
    readonly "voicesPage.heading": string;
    readonly "voicesPage.showDeleted": string;
    readonly "voicesPage.newVoice": string;
    readonly "voicesPage.cancel": string;
    readonly "voicesPage.namePlaceholder": string;
    readonly "voicesPage.creating": string;
    readonly "voicesPage.create": string;
    readonly "voicesPage.loading": string;
    readonly "voicesPage.loadFailed": string;
    readonly "voicesPage.empty": string;
    readonly "voicesPage.sampleCount": (count: number) => string;
    readonly "voicesPage.delete": string;
    readonly "voicesPage.deletedTag": string;
    readonly "voicesPage.statusDraft": string;
    readonly "voicesPage.statusQueued": string;
    readonly "voicesPage.statusPreprocessing": string;
    readonly "voicesPage.statusTraining": string;
    readonly "voicesPage.statusExporting": string;
    readonly "voicesPage.statusReady": string;
    readonly "voicesPage.statusFailed": string;
    readonly "voicesPage.created": string;
    readonly "voicesPage.createFailed": string;
    readonly "voicesPage.deletedToast": (gaps: { readonly name: string }) => string;
    readonly "voicesPage.deleteFailed": string;
    readonly "voicesPage.deleteTitle": string;
    readonly "voicesPage.deleteWarning": (gaps: { readonly name: string }) => string;
    readonly "voiceDetail.deletedBanner": string;
    readonly "voiceDetail.trainingCancelled": string;
    readonly "voiceDetail.lockedQueued": string;
    readonly "voiceDetail.lockedPreprocessing": string;
    readonly "voiceDetail.lockedTraining": string;
    readonly "voiceDetail.lockedExporting": string;
    readonly "voiceDetail.trainingFailed": string;
    readonly "voiceDetail.samples": string;
    readonly "voiceDetail.sampleCapacity": (gaps: { readonly max: string; readonly used: string }) => string;
    readonly "voiceDetail.noSamples": (gaps: { readonly count: number }) => string;
    readonly "voiceDetail.samplePosition": (gaps: { readonly position: string }) => string;
    readonly "voiceDetail.removeLabel": string;
    readonly "voiceDetail.remove": string;
    readonly "voiceDetail.removeConfirm": (gaps: { readonly position: string }) => string;
    readonly "voiceDetail.captionLabel": string;
    readonly "voiceDetail.lyricsLabel": string;
    readonly "voiceDetail.addSample": string;
    readonly "voiceDetail.dropHint": readonly (string | { readonly marker: "browse"; readonly text: string })[];
    readonly "voiceDetail.sources": string;
    readonly "voiceDetail.captionPlaceholder": string;
    readonly "voiceDetail.lyricsPlaceholder": string;
    readonly "voiceDetail.uploading": string;
    readonly "voiceDetail.sampleLimit": string;
    readonly "voiceDetail.ownTakesOpen": string;
    readonly "voiceDetail.ownTakesClose": string;
    readonly "voiceDetail.ownTakes": string;
    readonly "voiceDetail.ownTakesLoading": string;
    readonly "voiceDetail.ownTakesEmpty": string;
    readonly "voiceDetail.takeNumber": (gaps: { readonly number: string }) => string;
    readonly "voiceDetail.adding": string;
    readonly "voiceDetail.useTake": string;
    readonly "voiceDetail.waiting": string;
    readonly "voiceDetail.training": string;
    readonly "voiceDetail.cancel": string;
    readonly "voiceDetail.waitingDefault": string;
    readonly "voiceDetail.queuePosition": (gaps: { readonly position: string }) => string;
    readonly "voiceDetail.progressLabel": string;
    readonly "voiceDetail.epoch": (gaps: { readonly current: string; readonly total: string }) => string;
    readonly "voiceDetail.remainingCalculating": string;
    readonly "voiceDetail.remainingMinutes": (gaps: { readonly minutes: string }) => string;
    readonly "voiceDetail.remainingHours": (gaps: { readonly hours: string; readonly minutes: string }) => string;
    readonly "voiceDetail.trainVoice": string;
    readonly "voiceDetail.trainAgain": string;
    readonly "voiceDetail.starting": string;
    readonly "voiceDetail.trainButtonQueued": string;
    readonly "voiceDetail.trainButtonPreprocessing": string;
    readonly "voiceDetail.trainButtonTraining": string;
    readonly "voiceDetail.trainButtonExporting": string;
    readonly "voiceDetail.needSamples": (count: number, gaps: { readonly have: string }) => string;
    readonly "voiceDetail.sampleTextsMissing": string;
    readonly "voiceDetail.progressLoadFailed": string;
    readonly "voiceDetail.unsupportedFormat": (gaps: { readonly formats: string }) => string;
    readonly "voiceDetail.pickFileFirst": string;
    readonly "voiceDetail.captionLyricsRequired": string;
    readonly "voiceDetail.sampleAdded": string;
    readonly "voiceDetail.uploadFailed": string;
    readonly "voiceDetail.ownTakesLoadFailed": string;
    readonly "voiceDetail.copyFailed": string;
    readonly "voiceDetail.saveFailed": string;
    readonly "voiceDetail.deleteFailed": string;
    readonly "voiceDetail.queuedToast": string;
    readonly "voiceDetail.startFailed": string;
    readonly "voiceDetail.cancelFailed": string;
    readonly "referencesPage.documentTitle": (gaps: { readonly app: string }) => string;
    readonly "referencesPage.loading": string;
    readonly "referencesPage.loadFailed": string;
    readonly "referencesPage.retry": string;
    readonly "referencesPage.empty": string;
    readonly "referencesPage.upload": string;
    readonly "referencesPage.uploadingName": (gaps: { readonly name: string }) => string;
    readonly "referencesPage.uploadFailed": string;
    readonly "referencesPage.filesFigure": (count: number, gaps: { readonly files: string }) => string;
    readonly "referencesPage.sizeFigure": (gaps: { readonly limit: string; readonly used: string }) => string;
    readonly "referencesPage.storageFullFiles": (count: number, gaps: { readonly files: string }) => string;
    readonly "referencesPage.storageFullSize": (gaps: { readonly limit: string; readonly used: string }) => string;
    readonly "referencesPage.doesNotFit": (gaps: { readonly limit: string; readonly used: string }) => string;
    readonly "referencesPage.playFault": string;
    readonly "referencesPage.inUseFault": string;
    readonly "referencesPage.deleteFailed": string;
    readonly "referencesPage.keepFailed": string;
    readonly "referencesPage.unkeepFailed": string;
    readonly "referencesPage.deleteTitle": string;
    readonly "referencesPage.deleteItem": (gaps: { readonly filename: string }) => string;
    readonly "referenceRow.play": (gaps: { readonly filename: string }) => string;
    readonly "referenceRow.pause": (gaps: { readonly filename: string }) => string;
    readonly "referenceRow.keep": (gaps: { readonly filename: string }) => string;
    readonly "referenceRow.unkeep": (gaps: { readonly filename: string }) => string;
    readonly "referenceRow.usedIn": (gaps: { readonly uses: string }) => string;
    readonly "referenceRow.takes": (count: number) => string;
    readonly "referenceRow.versions": (count: number) => string;
    readonly "referenceUses.loading": string;
    readonly "referenceUses.loadFailed": string;
    readonly "referenceUses.staysNote": string;
    readonly "referenceUses.deletedTag": string;
    readonly "referenceUses.archivedTag": string;
    readonly "referenceUses.take": (gaps: { readonly number: string }) => string;
    readonly "referenceUses.takeVersion": (gaps: { readonly number: string; readonly version: string }) => string;
    readonly "referenceUses.takeLength": (gaps: { readonly length: string; readonly number: string }) => string;
    readonly "referenceUses.takeVersionLength": (gaps: { readonly length: string; readonly number: string; readonly version: string }) => string;
    readonly "referenceUses.version": (gaps: { readonly version: string }) => string;
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
    "playlistPage.coverAlt": (gaps: { readonly title: string }) => "Playlist cover for " + gaps.title,
    "playlistPage.coverAltEmpty": "Playlist cover",
    "playlistPage.loading": "Loading playlist…",
    "playlistPage.empty": "No songs in this playlist yet.",
    "playlistPage.retry": "Retry",
    "playlistPage.loadError": "Failed to load playlists",
    "playlistPage.entryMore": (gaps: { readonly title: string }) => "More for " + gaps.title,
    "playlistPage.moveUp": "Move up",
    "playlistPage.moveDown": "Move down",
    "playlistPage.remove": "Remove from playlist",
    "playlistPage.deleted": "Playlist deleted",
    "playlistPage.deleteFailed": "Delete failed",
    "playlistPage.renameFailed": "Rename failed",
    "playlistPage.coverSaved": "Cover saved",
    "playlistPage.coverSaveFailed": "Cover upload failed",
    "playlistPage.coverRemoved": "Cover removed",
    "playlistPage.coverRemoveFailed": "Cover remove failed",
    "playlistPage.removeFailed": "Remove failed",
    "playlistPage.reorderFailed": "Reorder failed",
    "playlistPage.deleteTitle": (gaps: { readonly title: string }) => "Delete \"" + gaps.title + "\"?",
    "playlistPage.songCount": (count: number) => ({
        zero: numberFormat.format(count) + " songs",
        one: numberFormat.format(count) + " song",
        two: numberFormat.format(count) + " songs",
        few: numberFormat.format(count) + " songs",
        many: numberFormat.format(count) + " songs",
        other: numberFormat.format(count) + " songs",
    })[pluralRules.select(count)],
    "playlistPage.deleteConfirm": "Delete Playlist",
    "playlistPicker.label": "Add to Playlist",
    "playlistPicker.heading": "Add to Playlist",
    "playlistPicker.loading": "Loading playlists…",
    "playlistPicker.error": "Failed to load playlists",
    "playlistPicker.retry": "Retry",
    "playlistPicker.newPlaceholder": "New playlist...",
    "playlistPicker.add": "Add playlist",
    "playlistPicker.createFailed": "Failed to create playlist",
    "songRow.openInEditor": (gaps: { readonly title: string }) => "Open " + gaps.title + " in the song editor",
    "homeWrite.openInEditor": (gaps: { readonly title: string }) => "Open " + gaps.title + " in the song editor",
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
    "recipe.panel": "Recipe",
    "recipe.panelChanged": "Recipe, changed",
    "recipe.tabsLabel": "Recipe sections",
    "recipe.close": "Close the recipe",
    "recipe.tabSong": "Song",
    "recipe.tabGenerate": "Generate",
    "recipe.tabEngine": "Engine",
    "recipe.savedWithVersion": "Saved with the version",
    "recipe.resetAll": "Reset all",
    "recipe.resetAuto": "Back to Auto",
    "recipe.resetEmpty": "Back to empty",
    "recipe.resetNone": "Back to None",
    "recipe.resetReference": "Remove the reference",
    "recipe.resetModel": "Back to the first model",
    "recipe.resetTakes": "Back to ×1",
    "recipe.resetPreset": "Back to Default",
    "recipe.bpm": "BPM",
    "recipe.duration": "Duration (s)",
    "recipe.key": "Key",
    "recipe.auto": "Auto",
    "recipe.empty": "—",
    "recipe.none": "None",
    "recipe.model": "Model",
    "recipe.modelLoading": "Loading…",
    "recipe.modelLoaded": "Loaded",
    "recipe.takes": "Takes per Generate",
    "recipe.retry": "Retry",
    "recipe.defaultsError": "Failed to load generation defaults",
    "recipe.engineEmptyHint": "Empty field = the model's default",
    "recipe.preset": "Preset",
    "recipe.presetDefault": "Default",
    "recipe.presetCustom": "Custom",
    "recipe.presetShared": (gaps: { readonly name: string }) => gaps.name + " (shared)",
    "recipe.presetNamePlaceholder": "Preset name",
    "recipe.presetSave": "Save",
    "recipe.presetCancel": "Cancel",
    "recipe.presetSaveError": "Failed to save preset",
    "recipe.saveAsPreset": "Save as preset",
    "recipe.managePresets": "Manage in Settings → Generation",
    "referencePicker.label": "Reference track",
    "referencePicker.chosen": (gaps: { readonly name: string }) => "Reference track: " + gaps.name,
    "referencePicker.none": "None",
    "referencePicker.play": (gaps: { readonly name: string }) => "Play " + gaps.name,
    "referencePicker.pause": (gaps: { readonly name: string }) => "Pause " + gaps.name,
    "referencePicker.loading": "Loading references…",
    "referencePicker.loadError": "Failed to load references",
    "referencePicker.playError": "Can't play this recording",
    "referencePicker.retry": "Retry",
    "referencePicker.upload": "Upload audio",
    "referencePicker.uploading": "Uploading…",
    "referencePicker.uploadError": "Upload failed",
    "referencePicker.all": "All references",
    "voicePicker.label": "Your Voice",
    "voicePicker.mobileLabel": (gaps: { readonly mode: string }) => "Your Voice · " + gaps.mode + " model",
    "voicePicker.none": "None",
    "voicePicker.create": "Create a voice",
    "voicePicker.stateNotForModel": "not available for this model",
    "voicePicker.stateDeleted": "voice deleted",
    "voicePicker.stateDraft": "draft",
    "voicePicker.stateTraining": "training",
    "voicePicker.stateFailed": "failed",
    "voicePicker.chosenUnavailable": (gaps: { readonly name: string; readonly state: string }) => gaps.name + " — " + gaps.state,
    "voicePicker.optionUnavailable": (gaps: { readonly state: string }) => "— " + gaps.state,
    "referenceExpiry.deletesOn": (gaps: { readonly date: string }) => "Deleted on " + gaps.date + " — keep to preserve",
    "referenceExpiry.daysLeft": (count: number) => ({
        zero: numberFormat.format(count) + "d",
        one: numberFormat.format(count) + "d",
        two: numberFormat.format(count) + "d",
        few: numberFormat.format(count) + "d",
        many: numberFormat.format(count) + "d",
        other: numberFormat.format(count) + "d",
    })[pluralRules.select(count)],
    "paramField.inferenceSteps": "Inference Steps",
    "paramField.guidanceScale": "Guidance Scale",
    "paramField.shift": "Shift",
    "paramField.cfgIntervalStart": "CFG Interval Start",
    "paramField.cfgIntervalEnd": "CFG Interval End",
    "paramField.velocityNorm": "Velocity Norm",
    "paramField.velocityEma": "Velocity EMA",
    "paramField.latentShift": "Latent Shift",
    "paramField.latentRescale": "Latent Rescale",
    "paramField.lmCodeStrength": "LM Code Strength",
    "paramField.inferMethod": "Infer Method",
    "paramField.sampler": "Sampler",
    "paramField.adaptiveDualGuidance": "Adaptive Dual Guidance",
    "paramField.temperature": "Temperature",
    "paramField.topK": "Top-K",
    "paramField.topP": "Top-P",
    "paramField.cfgScale": "CFG Scale",
    "paramField.repetitionPenalty": "Rep. Penalty",
    "paramField.batchSize": "Batch Size",
    "paramField.thinking": "Thinking",
    "paramField.cotCaption": "CoT Caption",
    "paramField.cotLanguage": "CoT Language",
    "paramField.negativePrompt": "Negative Prompt",
    "paramField.negativePromptPlaceholder": "e.g. bad quality, noise",
    "paramField.sectionDit": "DiT (Sound)",
    "paramField.sectionLm": "LM (Lyrics)",
    "paramField.defaultOption": "default",
    "paramField.defaultOptionValue": (gaps: { readonly value: string }) => "default (" + gaps.value + ")",
    "paramField.defaultMissing": (gaps: { readonly key: string }) => "Default missing for " + gaps.key,
    "paramField.resetTitle": "Back to the model's default",
    "paramField.resetLabel": (gaps: { readonly field: string }) => gaps.field + ": Back to the model's default",
    "voiceRefusal.deleted": "LoRA is deleted",
    "voiceRefusal.modifyDuringTraining": (gaps: { readonly status: string }) => "LoRA is " + gaps.status + " — cannot modify during training",
    "voiceRefusal.deleteDuringTraining": (gaps: { readonly status: string }) => "LoRA is " + gaps.status + " — cannot delete during training",
    "voiceRefusal.alreadyTraining": (gaps: { readonly status: string }) => "LoRA is " + gaps.status + " — already training",
    "voiceRefusal.notReady": (gaps: { readonly status: string }) => "LoRA is not ready (status=" + gaps.status + ")",
    "voiceRefusal.nameRequired": "Name is required",
    "voiceRefusal.limit": (gaps: { readonly limit: string }) => "Could not create voice\nYou have reached the limit of " + gaps.limit + " voices. Delete a voice before creating another.",
    "voiceRefusal.slugConflict": (gaps: { readonly name: string }) => "LoRA slug conflict for '" + gaps.name + "'",
    "voiceRefusal.sampleLimit": (gaps: { readonly maximum: string }) => "LoRA already has the maximum of " + gaps.maximum + " samples",
    "voiceRefusal.captionRequired": "Caption is required",
    "voiceRefusal.lyricsRequired": "Lyrics are required",
    "voiceRefusal.captionEmpty": "Caption cannot be empty",
    "voiceRefusal.lyricsEmpty": "Lyrics cannot be empty",
    "voiceRefusal.unsupportedFormat": (gaps: { readonly accepted: string; readonly extension: string }) => "Unsupported audio format '" + gaps.extension + "'. Accepted: " + gaps.accepted,
    "voiceRefusal.fileTooLarge": (gaps: { readonly maxMb: string }) => "Audio file too large (max " + gaps.maxMb + "MB)",
    "voiceRefusal.fileEmpty": "Audio file is empty",
    "voiceRefusal.tooFewSamples": (gaps: { readonly have: string; readonly minimum: string }) => "At least " + gaps.minimum + " samples required for training (have " + gaps.have + ")",
    "voiceRefusal.samplesIncomplete": "All samples must have non-empty caption and lyrics before training",
    "voiceRefusal.trainingQueueFull": (gaps: { readonly waiting: string }) => "Training queue is full\n" + gaps.waiting + " trainings are already waiting. Try again when one training starts or finishes.",
    "generationRefusal.sourceNoAudio": "Source generation has no audio file",
    "generationRefusal.ffmpegMissing": "ffmpeg is not available",
    "generationRefusal.wavConversionFailed": "Failed to convert MP3 to WAV",
    "generationRefusal.noLinkedVersion": "Generation has no linked version",
    "generationRefusal.needsLyricsAndPrompt": "Song needs lyrics and a style prompt before generating",
    "generationRefusal.repaintRange": "repainting_start must be less than repainting_end",
    "generationRefusal.workerNotRunning": "Worker not running",
    "jobRefusal.queueUnavailable": "Job queue unavailable",
    "jobRefusal.queueFull": "Queue is full. Try again later.",
    "jobRefusal.activeJob": "You already have an active job. Wait for it to finish.",
    "jobRefusal.hourlyLimit": (gaps: { readonly jobType: string; readonly limit: string }) => "Rate limit reached (" + gaps.limit + "/" + gaps.jobType + "s per hour).",
    "cowriterRefusal.browserLogin": "The co-writer needs a browser login.",
    "cowriterRefusal.turnRunning": "A co-writer reply is still being written",
    "cowriterRefusal.takeNotInSong": "Generation does not belong to the current song",
    "takeRefusal.notPlayable": "Generation is not playable",
    "settingsRefusal.modelUnavailable": (gaps: { readonly mode: string }) => "Model '" + gaps.mode + "' is not available",
    "settingsRefusal.invalidDefaultConfig": "Invalid config: must be null, 'sft', 'turbo', or a preset ID",
    "settingsRefusal.tailBudgetRange": (gaps: { readonly maximum: string; readonly minimum: string }) => "tail_token_budget must be between " + gaps.minimum + " and " + gaps.maximum,
    "settingsRefusal.unknownKeys": (gaps: { readonly keys: string }) => "Unknown setting keys: " + gaps.keys,
    "settingsRefusal.negativeValue": (gaps: { readonly key: string }) => "Value for " + gaps.key + " must be non-negative",
    "presetRefusal.nameTaken": "A preset with that name already exists",
    "adminRefusal.unknownModelMode": (gaps: { readonly mode: string }) => "Unknown model mode '" + gaps.mode + "'",
    "adminRefusal.noOnlineWorkers": "No online workers available to download",
    "adminRefusal.alreadyDownloaded": (gaps: { readonly mode: string }) => "Model '" + gaps.mode + "' is already downloaded",
    "adminRefusal.alreadyDownloading": (gaps: { readonly jobId: string; readonly mode: string }) => "Model '" + gaps.mode + "' is already being downloaded (job " + gaps.jobId + ")",
    "workerRefusal.unreachable": (gaps: { readonly reason: string }) => "Worker unreachable: " + gaps.reason,
    "workerRefusal.relayed": (gaps: { readonly cause: string }) => gaps.cause,
    "workerRefusal.notResponding": (gaps: { readonly workerId: string }) => "Worker '" + gaps.workerId + "' isn't responding, so it can't be asked to restart itself. Its container is likely stopped or crashed — restart the container directly.",
    "workerRefusal.returnedStatus": (gaps: { readonly status: string }) => "Worker returned " + gaps.status,
    "coverRefusal.tooLarge": "Cover file is too large",
    "coverRefusal.unreadable": "Cover image could not be read",
    "coverRefusal.unsupportedType": "Cover must be a JPEG or PNG image",
    "coverRefusal.tooManyPixels": "Cover image is too large",
    "coverRefusal.variantUnknown": "Unknown cover variant",
    "coverRefusal.invalidAlbumId": "Invalid album id for cover storage",
    "coverRefusal.invalidSongId": "Invalid song id for cover storage",
    "coverRefusal.invalidPlaylistId": "Invalid playlist id for cover storage",
    "coverSuggestionRefusal.alreadyRunning": "Cover suggestions are already being generated",
    "referenceRefusal.quotaReached": "Reference audio storage limit reached.",
    "referenceRefusal.storage": "Reference audio storage could not be checked.",
    "albumRefusal.restoreWindowPassed": (gaps: { readonly days: string; readonly id: string; readonly window: string }) => "Album " + gaps.id + " was deleted " + gaps.days + " days ago, past the " + gaps.window + "-day restore window",
    "songRefusal.restoreWindowPassed": (gaps: { readonly days: string; readonly id: string; readonly window: string }) => "Song " + gaps.id + " was deleted " + gaps.days + " days ago, past the " + gaps.window + "-day restore window",
    "takesList.loading": "Loading takes…",
    "takesList.error": "Failed to load takes",
    "takesList.retry": "Try again",
    "takesList.aboutTakes": "About takes",
    "takesList.mobileHint": "Tap play → details in Now Playing",
    "takesList.empty": (gaps: { readonly generate: string }) => "No takes yet · " + gaps.generate + " makes the first",
    "takesList.draftUnsaved": (gaps: { readonly next: string }) => "Draft — unsaved changes. Generate creates v" + gaps.next + ".",
    "takesList.draftDiffers": (gaps: { readonly latest: string; readonly next: string }) => "Draft — differs from v" + gaps.latest + ". Generate creates v" + gaps.next + ".",
    "takesList.openVersion": (gaps: { readonly number: string }) => "Open v" + gaps.number,
    "takesList.currentHead": (count: number, gaps: { readonly number: string }) => ({
        zero: "v" + gaps.number + " current · " + numberFormat.format(count) + " takes",
        one: "v" + gaps.number + " current · " + numberFormat.format(count) + " take",
        two: "v" + gaps.number + " current · " + numberFormat.format(count) + " takes",
        few: "v" + gaps.number + " current · " + numberFormat.format(count) + " takes",
        many: "v" + gaps.number + " current · " + numberFormat.format(count) + " takes",
        other: "v" + gaps.number + " current · " + numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "takesList.foldedVersion": (count: number, gaps: { readonly number: string }) => ({
        zero: "v" + gaps.number + " · " + numberFormat.format(count) + " takes",
        one: "v" + gaps.number + " · " + numberFormat.format(count) + " take",
        two: "v" + gaps.number + " · " + numberFormat.format(count) + " takes",
        few: "v" + gaps.number + " · " + numberFormat.format(count) + " takes",
        many: "v" + gaps.number + " · " + numberFormat.format(count) + " takes",
        other: "v" + gaps.number + " · " + numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "takesList.foldedImported": (count: number) => ({
        zero: "Imported · " + numberFormat.format(count) + " takes",
        one: "Imported · " + numberFormat.format(count) + " take",
        two: "Imported · " + numberFormat.format(count) + " takes",
        few: "Imported · " + numberFormat.format(count) + " takes",
        many: "Imported · " + numberFormat.format(count) + " takes",
        other: "Imported · " + numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "takesList.foldedVersionArchived": (count: number, gaps: { readonly archived: string; readonly number: string }) => ({
        zero: "v" + gaps.number + " · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        one: "v" + gaps.number + " · " + numberFormat.format(count) + " take · " + gaps.archived + " archived",
        two: "v" + gaps.number + " · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        few: "v" + gaps.number + " · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        many: "v" + gaps.number + " · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        other: "v" + gaps.number + " · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
    })[pluralRules.select(count)],
    "takesList.foldedImportedArchived": (count: number, gaps: { readonly archived: string }) => ({
        zero: "Imported · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        one: "Imported · " + numberFormat.format(count) + " take · " + gaps.archived + " archived",
        two: "Imported · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        few: "Imported · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        many: "Imported · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
        other: "Imported · " + numberFormat.format(count) + " takes · " + gaps.archived + " archived",
    })[pluralRules.select(count)],
    "takesList.allArchived": "all",
    "takesList.earlier": "Earlier versions",
    "takesList.takeLabel": (gaps: { readonly number: string }) => "Take " + gaps.number,
    "takesList.selectAllUnkept": "Select all unkept",
    "takesList.selectedCount": (count: number) => ({
        zero: numberFormat.format(count) + " selected",
        one: numberFormat.format(count) + " selected",
        two: numberFormat.format(count) + " selected",
        few: numberFormat.format(count) + " selected",
        many: numberFormat.format(count) + " selected",
        other: numberFormat.format(count) + " selected",
    })[pluralRules.select(count)],
    "takesList.bulkDeleteLabel": (count: number) => ({
        zero: "Delete " + numberFormat.format(count),
        one: "Delete " + numberFormat.format(count),
        two: "Delete " + numberFormat.format(count),
        few: "Delete " + numberFormat.format(count),
        many: "Delete " + numberFormat.format(count),
        other: "Delete " + numberFormat.format(count),
    })[pluralRules.select(count)],
    "takesList.bulkDeleteTitle": (count: number) => ({
        zero: "Delete " + numberFormat.format(count) + " takes?",
        one: "Delete " + numberFormat.format(count) + " take?",
        two: "Delete " + numberFormat.format(count) + " takes?",
        few: "Delete " + numberFormat.format(count) + " takes?",
        many: "Delete " + numberFormat.format(count) + " takes?",
        other: "Delete " + numberFormat.format(count) + " takes?",
    })[pluralRules.select(count)],
    "takesList.cancel": "Cancel",
    "takesList.deleteTitle": (gaps: { readonly number: string }) => "Delete take " + gaps.number + "?",
    "takesList.deleteMessage": "Audio files will be permanently deleted",
    "takesList.deleteConfirm": "Delete",
    "takesList.deleted": (count: number) => ({
        zero: "Deleted " + numberFormat.format(count) + " takes",
        one: "Deleted " + numberFormat.format(count) + " take",
        two: "Deleted " + numberFormat.format(count) + " takes",
        few: "Deleted " + numberFormat.format(count) + " takes",
        many: "Deleted " + numberFormat.format(count) + " takes",
        other: "Deleted " + numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "takesList.bulkDeleteFailed": "Bulk delete failed",
    "takesList.addedToPlaylist": "Added to playlist",
    "takesList.addFailed": "Failed to add",
    "takeRow.takeLabel": (gaps: { readonly number: string }) => "Take " + gaps.number,
    "takeRow.takeVersioned": (gaps: { readonly take: string; readonly version: string }) => "v" + gaps.version + " · take " + gaps.take,
    "takeRow.takeUnversioned": (gaps: { readonly take: string }) => "take " + gaps.take,
    "takeRow.archivedTitle": "Archived take",
    "takeRow.selectTake": (gaps: { readonly take: string }) => "Select " + gaps.take,
    "takeRow.playTake": (gaps: { readonly action: string; readonly take: string }) => gaps.action + " " + gaps.take,
    "takeRow.pickTake": (gaps: { readonly take: string }) => "Pick " + gaps.take,
    "takeRow.unpickTake": (gaps: { readonly take: string }) => "Unpick " + gaps.take,
    "takeRow.keepTake": (gaps: { readonly take: string }) => "Keep " + gaps.take,
    "takeRow.unkeepTake": (gaps: { readonly take: string }) => "Unkeep " + gaps.take,
    "takeRow.provenanceRepaint": (gaps: { readonly take: string }) => "Repaint from " + gaps.take,
    "takeRow.provenanceCover": (gaps: { readonly take: string }) => "Cover from " + gaps.take,
    "takeRow.batchBadge": (gaps: { readonly delivered: string; readonly requested: string }) => gaps.delivered + " of " + gaps.requested,
    "takeRow.batchTitle": (gaps: { readonly delivered: string; readonly requested: string }) => "Batch size reduced by ACE-Step due to available VRAM: delivered " + gaps.delivered + " of " + gaps.requested,
    "takeRow.flagNoVocals": "No vocals",
    "takeRow.flagNoVocalsTitle": "No vocals detected in this take",
    "takeRow.flagLongSilence": "Long silence",
    "takeRow.flagLongSilenceTitle": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "s of silence detected",
    "takeRow.rescoring": "Re-scoring…",
    "takeRow.archived": "archived",
    "takeRow.archivedBadgeTitle": "Archived — will be hard-deleted",
    "takeRow.expiryBadge": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "d",
    "takeRow.expiresIn": (count: number) => ({
        zero: "Expires in " + numberFormat.format(count) + " days — pick or keep to preserve",
        one: "Expires in " + numberFormat.format(count) + " day — pick or keep to preserve",
        two: "Expires in " + numberFormat.format(count) + " days — pick or keep to preserve",
        few: "Expires in " + numberFormat.format(count) + " days — pick or keep to preserve",
        many: "Expires in " + numberFormat.format(count) + " days — pick or keep to preserve",
        other: "Expires in " + numberFormat.format(count) + " days — pick or keep to preserve",
    })[pluralRules.select(count)],
    "takeRow.voice": (gaps: { readonly name: string }) => "Voice: " + gaps.name,
    "takeRow.voiceDeleted": (gaps: { readonly name: string }) => "Voice: " + gaps.name + " — voice deleted",
    "takeRow.scoreTitle": (gaps: { readonly metric: string; readonly value: string }) => gaps.metric + " " + gaps.value,
    "takeRow.scoreRating": "Rating",
    "takeRow.scoreLyricsSung": "Lyrics sung",
    "takeRow.scoreDynamics": "Dynamics",
    "takeRow.scoreQuality": "Quality",
    "takeRow.scoreEnjoyment": "Enjoyment",
    "takeRow.scoreCoherence": "Coherence",
    "takeTask.repaint": "Repaint",
    "takeTask.cover": "Cover",
    "takeTask.close": "Close",
    "takeTask.closeTitle": "Close — nothing changes",
    "takeTask.fromTake": (gaps: { readonly number: string }) => "take " + gaps.number,
    "takeTask.detailVersioned": (gaps: { readonly duration: string; readonly version: string }) => "· v" + gaps.version + " · " + gaps.duration,
    "takeTask.detail": (gaps: { readonly duration: string }) => "· " + gaps.duration,
    "takeTask.range": "Range",
    "takeTask.rangeCaption": "drag the handles",
    "takeTask.repaintAmount": "How much changes",
    "takeTask.modeConservative": "Conservative",
    "takeTask.modeBalanced": "Balanced",
    "takeTask.modeAggressive": "Aggressive",
    "takeTask.repaintStrength": "Repaint strength",
    "takeTask.strengthValue": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "%",
    "takeTask.coverCloseness": (gaps: { readonly number: string }) => "How close to take " + gaps.number,
    "takeTask.coverFree": "Free",
    "takeTask.coverStrict": "Strict",
    "takeTask.coverStrength": "Cover strength",
    "takeTask.noise": "Noise",
    "takeTask.noiseCaption": "more noise, more surprise",
    "takeTask.noiseBound": (gaps: { readonly count: number }) => numberFormat.format(gaps.count),
    "takeTask.promptHint": "Paints using the lyrics and style currently in the editor — not the source take's own.",
    "takeTask.seedLine": (gaps: { readonly number: string }) => "seed: from take " + gaps.number,
    "takeTask.landing": (gaps: { readonly number: string }) => "New take in v" + gaps.number,
    "takeTask.headerNote": "· the header Generate stays what it is",
    "takeTask.repaintPress": (gaps: { readonly end: string; readonly start: string }) => "Repaint " + gaps.start + " – " + gaps.end,
    "seedChip.label": (gaps: { readonly number: string }) => "Seed · take " + gaps.number,
    "seedChip.clear": "Clear seed",
    "takeActions.pickFailed": "Pick failed",
    "takeActions.keepFailed": "Keep failed",
    "takeActions.restoreFailed": "Restore failed",
    "takeActions.ratingSaved": "Rating saved",
    "takeActions.ratingFailed": "Rating failed",
    "takeActions.rescoreQueued": "Re-scoring this take…",
    "takeActions.rescoreFailed": "Re-score failed",
    "takeActions.useSeed": (gaps: { readonly number: string }) => "Seed from take " + gaps.number,
    "nowPlayingTake.label": (gaps: { readonly number: string }) => "Take " + gaps.number,
    "nowPlayingTake.importedHeading": "Imported take",
    "nowPlayingTake.heading": (gaps: { readonly take: string; readonly version: string }) => "v" + gaps.version + " · take " + gaps.take,
    "nowPlayingTake.headingDuration": (gaps: { readonly duration: string; readonly take: string; readonly version: string }) => "v" + gaps.version + " · take " + gaps.take + " · " + gaps.duration,
    "nowPlayingTake.headingMode": (gaps: { readonly mode: string; readonly take: string; readonly version: string }) => "v" + gaps.version + " · take " + gaps.take + " · " + gaps.mode,
    "nowPlayingTake.headingDurationMode": (gaps: { readonly duration: string; readonly mode: string; readonly take: string; readonly version: string }) => "v" + gaps.version + " · take " + gaps.take + " · " + gaps.duration + " · " + gaps.mode,
    "nowPlayingTake.openVersion": (gaps: { readonly number: string }) => "Open v" + gaps.number,
    "nowPlayingTake.pick": "Pick",
    "nowPlayingTake.unpick": "Unpick",
    "nowPlayingTake.keep": "Keep",
    "nowPlayingTake.unkeep": "Unkeep",
    "nowPlayingTake.scores": "Scores",
    "nowPlayingTake.scoresEmpty": "No scores yet",
    "nowPlayingTake.scoreRating": "Rating",
    "nowPlayingTake.scoreLyricsSung": "Lyrics sung",
    "nowPlayingTake.scoreDynamics": "Dynamics",
    "nowPlayingTake.scoreQuality": "Quality",
    "nowPlayingTake.scoreEnjoyment": "Enjoyment",
    "nowPlayingTake.scoreCoherence": "Coherence",
    "nowPlayingTake.scoreBpm": "BPM",
    "nowPlayingTake.deviations": "Sung vs. lyrics",
    "nowPlayingTake.deviationsEmpty": "Sung text matches the lyrics",
    "nowPlayingTake.deviationsUnavailable": "No transcript to compare against yet",
    "nowPlayingTake.lyricsRow": (gaps: { readonly lyrics: string }) => "Lyrics: " + gaps.lyrics,
    "nowPlayingTake.deviationAddedTitle": "Not in lyrics",
    "nowPlayingTake.deviationAdded": (gaps: { readonly value: string }) => gaps.value + " (Not in lyrics)",
    "nowPlayingTake.rescoreAction": "Re-score this take to follow the lyrics.",
    "nowPlayingTake.rescoring": "Re-scoring…",
    "nowPlayingTake.rescore": "Re-score",
    "nowPlayingTake.recipe": "Recipe",
    "nowPlayingTake.rating": "Your rating",
    "nowPlayingTake.ratingNotes": "Notes (optional)",
    "nowPlayingTake.ratingSave": "Save rating",
    "nowPlayingTake.ratingSaving": "Saving…",
    "nowPlayingTake.useSeed": "Use seed",
    "nowPlayingTake.repaint": "Repaint",
    "nowPlayingTake.cover": "Cover",
    "takeRecipe.groupModel": "Model & Sampling",
    "takeRecipe.groupReproducibility": "Reproducibility",
    "takeRecipe.groupVersion": "Version",
    "takeRecipe.groupOther": "Other",
    "takeRecipe.model": "Model",
    "takeRecipe.deliveredBatchSize": "Delivered Batch Size",
    "takeRecipe.seed": "Seed",
    "takeRecipe.requestedSeed": "Requested Seed",
    "takeRecipe.bpm": "BPM",
    "takeRecipe.duration": "Duration",
    "takeRecipe.key": "Key",
    "takeRecipe.language": "Language",
    "takeRecipe.on": "On",
    "takeRecipe.off": "Off",
    "albumRefusal.notFound": "Album not found",
    "albumRefusal.titleRequired": "Title is required",
    "albumRefusal.idConflict": (gaps: { readonly title: string }) => "Album ID conflict for '" + gaps.title + "'. Try a different title.",
    "songRefusal.notFound": "Song not found",
    "songRefusal.titleRequired": "Title is required",
    "songRefusal.titleTooLong": "Title is too long",
    "songRefusal.moveTargetMissing": "Song or album not found",
    "songRefusal.restoreAlbumDeleted": (gaps: { readonly id: string }) => "Cannot restore song " + gaps.id + ": parent album is deleted",
    "songRefusal.notPlayable": "Song is not playable",
    "songRefusal.playlistLacksSong": "Playlist does not hold this song",
    "songRefusal.referenceMissing": "Not Found",
    "versionRefusal.notFound": "Version not found",
    "versionRefusal.inUse": "This version has a take rendering; wait for it to finish or cancel it.",
    "playlistRefusal.notFound": "Playlist not found",
    "playlistRefusal.entryNotFound": "Playlist entry not found",
    "playlistRefusal.songNotPlayable": "Song has no playable take",
    "coverSuggestionRefusal.notFound": "Album not found",
    "coverSuggestionRefusal.nothingNamed": "Name the suggestions or runs to discard",
    "coverSuggestionRefusal.browserLogin": "Cover suggestions need a browser login.",
    "shareRefusal.personsAgent": "A person's own agent cannot share; the person shares in the app.",
    "libraryRefusal.queryRequired": "Search query is required",
    "cowriter.title": "Co-writer",
    "cowriter.thinking": "Co-writer is thinking…",
    "cowriter.conversationMenu": "Conversation menu",
    "cowriter.conversationMenuWaiting": "Conversation menu, memory proposal waiting",
    "cowriter.composerPlaceholder": "Ask for a rewrite…",
    "cowriter.send": "Send",
    "cowriter.newConversation": "New conversation",
    "cowriter.memory": "Memory",
    "cowriter.memoryWaiting": "Memory, memory proposal waiting",
    "cowriter.deleteConversationTitle": "Delete conversation?",
    "cowriter.deleteConversationWarning": "This can't be undone.",
    "cowriter.deleteConversation": "Delete conversation",
    "cowriter.newConversationLine": "new conversation",
    "cowriter.lineSince": (gaps: { readonly day: string }) => "conversation since " + gaps.day,
    "cowriter.lineArchived": (gaps: { readonly day: string }) => "archived conversation from " + gaps.day,
    "cowriter.conversationSince": (gaps: { readonly day: string; readonly time: string }) => "Conversation since " + gaps.day + " " + gaps.time,
    "cowriter.archivedRow": (gaps: { readonly day: string; readonly time: string }) => "Archived · " + gaps.day + " " + gaps.time,
    "cowriter.confirmRow": (gaps: { readonly messages: string; readonly name: string }) => gaps.name + " · " + gaps.messages,
    "cowriter.messageCount": (count: number) => ({
        zero: numberFormat.format(count) + " msgs",
        one: numberFormat.format(count) + " msg",
        two: numberFormat.format(count) + " msgs",
        few: numberFormat.format(count) + " msgs",
        many: numberFormat.format(count) + " msgs",
        other: numberFormat.format(count) + " msgs",
    })[pluralRules.select(count)],
    "cowriter.today": "today",
    "cowriter.toolRan": (gaps: { readonly name: string }) => "ran tool: " + gaps.name,
    "cowriter.toolTarget": (gaps: { readonly title: string }) => "for: " + gaps.title,
    "cowriter.toolForeignTarget": "This proposal applies to a different song than the one you have open",
    "cowriter.historyUnavailable": "Conversation history unavailable",
    "cowriter.loadingChat": "Loading chat…",
    "cowriter.startFailed": "Failed to start new conversation",
    "cowriter.deleteFailed": "Failed to delete conversation",
    "cowriter.archivedToast": "Viewing an archived conversation — start a new one to reply",
    "cowriter.archivedBanner": ["Archived — ", { marker: "link", text: "start a new conversation" }, " to reply."] as readonly (string | { readonly marker: "link"; readonly text: string })[],
    "cowriter.albumFallback": "Album",
    "cowriter.noMatches": "No matches",
    "cowriter.memoryUnavailable": "Memory unavailable",
    "cowriter.memorySaveFailed": "Failed to save memory",
    "cowriter.proposalStale": "Memory proposal is stale or belongs elsewhere",
    "memory.close": "Close memory",
    "memory.loading": "Loading memory…",
    "memory.you": "You",
    "memory.thisSong": "This song",
    "memory.albumNotes": "Album notes",
    "memory.hintUser": "Taste, language, standing rules",
    "memory.hintSong": "Concept, locked vs open decisions, names, open questions",
    "memory.hintAlbum": "Album-level notes — not lyrics",
    "memory.proposedUser": "Proposed You",
    "memory.proposedSong": "Proposed This song",
    "memory.proposedAlbum": "Proposed Album notes",
    "memory.accept": "Accept",
    "memory.reject": "Reject",
    "memory.userField": "User memory",
    "memory.songField": "Song memory",
    "memory.albumField": "Album notes",
    "memory.save": "Save",
    "memory.saving": "Saving...",
    "cowriter.emptyHint": "I can see the song you have open. Tell me what you want to work on, or ask me to browse your other songs — I'll pull them up as needed.",
    "shareStatus.loadingAlbum": "Loading album",
    "shareStatus.loadingPlaylist": "Loading playlist",
    "shareStatus.loadingSong": "Loading song",
    "shareStatus.loadingTake": "Loading take",
    "shareStatus.notFoundAlbum": "Album not found",
    "shareStatus.notFoundPlaylist": "Playlist not found",
    "shareStatus.notFoundSong": "Song not found",
    "shareStatus.notFoundTake": "Take not found",
    "shareStatus.errorAlbum": "Could not load this album",
    "shareStatus.errorPlaylist": "Could not load this playlist",
    "shareStatus.errorSong": "Could not load this song",
    "shareStatus.errorTake": "Could not load this take",
    "shareStatus.errorBodyAlbum": "Something went wrong while loading this album.",
    "shareStatus.errorBodyPlaylist": "Something went wrong while loading this playlist.",
    "shareStatus.errorBodySong": "Something went wrong while loading this song.",
    "shareStatus.errorBodyTake": "Something went wrong while loading this take.",
    "shareStatus.invalidLink": "This share link is invalid or was removed.",
    "shareStatus.openApp": (gaps: { readonly app: string }) => "Open " + gaps.app,
    "shareStatus.retry": "Try again",
    "shareAlbumPage.documentTitle": (gaps: { readonly app: string; readonly artist: string; readonly title: string }) => gaps.title + " — " + gaps.artist + " | " + gaps.app,
    "shareAlbumPage.fallbackTitle": (gaps: { readonly app: string }) => "Shared album | " + gaps.app,
    "sharePlaylistPage.documentTitle": (gaps: { readonly app: string; readonly title: string }) => gaps.title + " | " + gaps.app,
    "sharePlaylistPage.fallbackTitle": (gaps: { readonly app: string }) => "Shared playlist | " + gaps.app,
    "shareSongPage.documentTitle": (gaps: { readonly app: string; readonly artist: string; readonly title: string }) => gaps.title + " — " + gaps.artist + " | " + gaps.app,
    "shareSongPage.fallbackTitle": (gaps: { readonly app: string }) => "Shared song | " + gaps.app,
    "shareTakePage.documentTitle": (gaps: { readonly app: string; readonly number: string; readonly title: string }) => "Take " + gaps.number + " — " + gaps.title + " | " + gaps.app,
    "shareTakePage.fallbackTitle": (gaps: { readonly app: string }) => "Shared take | " + gaps.app,
    "share.nowPlaying": (gaps: { readonly position: string; readonly title: string; readonly total: string }) => "Now playing · " + gaps.title + " · " + gaps.position + " of " + gaps.total,
    "share.albumSubtitle": (gaps: { readonly artist: string }) => gaps.artist + " · Album",
    "share.albumSubtitleNoArtist": "Album",
    "share.playlistSubtitle": (count: number) => ({
        zero: "Playlist · " + numberFormat.format(count) + " songs",
        one: "Playlist · " + numberFormat.format(count) + " song",
        two: "Playlist · " + numberFormat.format(count) + " songs",
        few: "Playlist · " + numberFormat.format(count) + " songs",
        many: "Playlist · " + numberFormat.format(count) + " songs",
        other: "Playlist · " + numberFormat.format(count) + " songs",
    })[pluralRules.select(count)],
    "share.noLyrics": "No lyrics",
    "share.noAudio": "No audio available yet.",
    "share.backToPlayer": "Back to the player",
    "share.songs": "Songs",
    "shareButton.copyFailedToast": "Shared — copy the link manually, clipboard write failed",
    "shareButton.copiedToast": "Link copied to clipboard",
    "shareButton.unsharedToast": "Sharing disabled",
    "shareButton.failedToast": "Share failed",
    "shareButton.fallbackTitle": "Share",
    "shareButton.songLabel": "Share song",
    "shareToggle.sharedTooltip": (gaps: { readonly path: string }) => "Shared: " + gaps.path,
    "shareLink.copiedToast": "Link copied",
    "shareLink.copyFailedToast": "Copy failed",
    "shareDialog.title": "Missing from the share page",
    "shareDialog.intro": "These songs have no playable take and won't appear when shared:",
    "shareDialog.close": "Got it",
    "libraryShares.copyLink": "Copy link",
    "legal.imprint": "Legal notice",
    "legal.privacy": "Privacy",
    "legal.terms": "Terms of use",
    "account.menu": (gaps: { readonly username: string }) => "Account · " + gaps.username,
    "account.menuClose": "Close account menu",
    "account.signOutFailed": "Couldn't log out. Check your connection and try again.",
    "auth.loading": "Loading...",
    "auth.retry": "Retry",
    "auth.checkRateLimited": "Too many requests. Retry in a moment to check your session.",
    "auth.checkServerError": "Could not verify your session. Retry to try again.",
    "auth.checkNetworkError": "Network error. Retry to check your session.",
    "referenceRefusal.notFound": "Not Found",
    "referenceRefusal.noFilename": "No filename provided",
    "referenceRefusal.filenameInvalid": "Invalid filename.",
    "referenceRefusal.filenameTooLong": (gaps: { readonly max: string }) => "Filename too long (max " + gaps.max + " characters)",
    "referenceRefusal.formatUnsupported": (gaps: { readonly accepted: string; readonly extension: string }) => "Unsupported format '" + gaps.extension + "'. Accepted: " + gaps.accepted,
    "referenceRefusal.fileTooLarge": (gaps: { readonly max: string }) => "File too large (max " + gaps.max + "MB)",
    "referenceRefusal.fileTooSmall": "File is empty or too small",
    "referenceRefusal.inUse": "Reference audio is in use.",
    "referenceRefusal.countdownStale": "The countdown epoch is no longer current.",
    "jobRefusal.notFound": "Job not found",
    "jobRefusal.notCancellable": "Only queued or running jobs can be cancelled",
    "libraryQueueRefusal.startUnplayable": "Requested take is not playable",
    "libraryQueueRefusal.emptyPool": (gaps: { readonly pool: string }) => "No playable takes in pool '" + gaps.pool + "'",
    "libraryQueueRefusal.emptyWindow": "No playable takes in scanned library window",
    "libraryQueueRefusal.tooManyRequests": "Too many queue stream requests",
    "libraryQueueRefusal.limiterUnavailable": "Queue stream rate limiter unavailable",
    "libraryRefusal.cursorInvalid": "Invalid library cursor",
    "libraryRefusal.cursorMismatch": "Library cursor does not match query and sort",
    "connectivity.offlineStrip": "You're offline — retrying",
    "resourceSync.error": "Couldn't reach your library",
    "http.rateLimited": "Too many requests — hang on, it will continue in a moment.",
    "http.genericError": "Something went wrong. Try again.",
    "navigation.songLinkNotFound": "Song not found — it may have been deleted",
    "dialog.cancel": "Cancel",
    "dialog.confirm": "Confirm",
    "toast.dismiss": "Dismiss",
    "loading.plain": "Loading...",
    "adminPage.heading": "Admin",
    "adminPage.accessRequired": "Admin access required.",
    "adminPage.sections": "Admin sections",
    "adminPage.tabVoices": "Voices",
    "adminPage.tabRateLimits": "Rate Limits",
    "adminPage.tabGeneration": "Generation",
    "adminPage.tabModels": "Models",
    "adminPage.tabAcestep": "ACE-Step",
    "adminPage.tabCleanup": "Cleanup",
    "adminPage.saving": "Saving...",
    "adminPage.saveDefaults": "Save Defaults",
    "adminPage.saveFailed": "Failed to save",
    "adminVoices.heading": "Voice operations",
    "adminVoices.loading": "Loading voices...",
    "adminVoices.empty": "No voices have been created.",
    "adminVoices.loadFailed": "Failed to load voices",
    "adminVoices.columnVoice": "Voice",
    "adminVoices.columnOwner": "Owner",
    "adminVoices.columnStatus": "Status",
    "rateLimits.heading": "Global Defaults",
    "rateLimits.hint": "These apply to all users.",
    "rateLimits.generations": "Generations / hour",
    "rateLimits.scorings": "Scorings / hour",
    "rateLimits.maxQueueDepth": "Max queue depth",
    "rateLimits.maxActiveJobs": "Max active jobs",
    "rateLimits.loadFailed": "Failed to load rate limits",
    "generationDefaults.heading": "Generation Defaults",
    "generationDefaults.hint": "Default generation parameters for all users. Per-song overrides take precedence.",
    "generationDefaults.reset": "Reset",
    "generationDefaults.loadFailed": "Failed to load generation defaults",
    "generationDefaults.saveFailed": "Failed to save generation defaults",
    "availableModels.heading": "Available Models",
    "availableModels.hint": "Toggle which models users can create presets for.",
    "availableModels.on": "ON",
    "availableModels.off": "OFF",
    "availableModels.toggleFailed": "Failed to toggle model",
    "modelsTable.heading": "Models",
    "modelsTable.columnTask": "Task",
    "modelsTable.columnProvider": "Provider",
    "modelsTable.columnRoute": "Route",
    "modelsTable.columnModel": "Model",
    "modelsTable.columnStatus": "Status",
    "modelsTable.taskCowriter": "Co-Writer",
    "modelsTable.taskCover": "Cover",
    "modelsTable.setByAgentFile": "Set by the agent file",
    "modelsTable.routeGateway": "Gateway",
    "modelsTable.advanced": "Advanced",
    "modelsTable.historyTail": "History tail (tokens)",
    "modelsTable.saved": "Saved.",
    "modelsTable.retry": "Retry",
    "modelsTable.saveFailed": "The server rejected the change.",
    "modelsTable.loading": "Loading…",
    "modelsTable.unavailable": "Unavailable",
    "modelsTable.loadFailed": "Failed to load co-writer settings",
    "recipe.modelsLoadFailed": "Failed to load models",
    "workerPool.heading": "Worker Pool",
    "workerPool.loadFailed": "Cannot reach the worker pool API.",
    "workerPool.refreshFailed": "Worker pool not updating — retrying…",
    "workerPool.noWorkers": (gaps: { readonly container: string }): readonly (string | { readonly marker: "code"; readonly text: string })[] => ["No workers registered. Start the ", { marker: "code", text: gaps.container }, " container and wait a few seconds."],
    "workerPool.cardHeader": (gaps: { readonly gpu: string; readonly vram: string }) => "GPU " + gaps.gpu + " • " + gaps.vram,
    "workerPool.vramTotal": (gaps: { readonly total: string }) => gaps.total + " GB",
    "workerPool.statusLabel": "Status:",
    "workerPool.logLabel": "Log:",
    "workerPool.queueLabel": "Queue:",
    "workerPool.lastSeenLabel": "Last seen:",
    "workerPool.queueJobs": (count: number) => ({
        zero: numberFormat.format(count) + " jobs",
        one: numberFormat.format(count) + " job",
        two: numberFormat.format(count) + " jobs",
        few: numberFormat.format(count) + " jobs",
        many: numberFormat.format(count) + " jobs",
        other: numberFormat.format(count) + " jobs",
    })[pluralRules.select(count)],
    "workerPool.loadingSpinner": "loading",
    "workerPool.statusLoading": (gaps: { readonly mode: string }) => "Loading " + gaps.mode + "…",
    "workerPool.statusLoadingElapsed": (gaps: { readonly elapsed: string; readonly mode: string }) => "Loading " + gaps.mode + "… (" + gaps.elapsed + " elapsed)",
    "workerPool.statusTraining": (gaps: { readonly seconds: string }) => "Training (" + gaps.seconds + "s remaining)",
    "workerPool.statusNoModel": "No model loaded",
    "workerPool.statusBusy": (gaps: { readonly count: number }) => "Busy (" + numberFormat.format(gaps.count) + " in queue)",
    "workerPool.statusIdle": "Idle",
    "workerPool.offlineSince": (gaps: { readonly lastSeen: string }) => "Offline — last registered " + gaps.lastSeen,
    "workerPool.gpuUnavailableDetail": (gaps: { readonly detail: string }) => "GPU unavailable — " + gaps.detail,
    "workerPool.gpuUnavailable": "GPU unavailable",
    "workerPool.gpuHealthNotReported": "GPU health not reported — worker build predates GPU health checks",
    "workerPool.restartNoProcess": (gaps: { readonly worker: string }) => "Can't restart — no worker process is running to ask. Restart the container running worker \"" + gaps.worker + "\" directly.",
    "workerPool.restartBrokenGpu": (gaps: { readonly worker: string }) => "Can't restart — its GPU is the problem, not the process. Restart the container running worker \"" + gaps.worker + "\" directly, or check the host's NVIDIA driver.",
    "workerPool.restartNoGpuHealth": (gaps: { readonly worker: string }) => "Can't restart — this worker build doesn't report GPU health, so it can't be trusted as healthy. Restarting the same process won't add that; update the container running worker \"" + gaps.worker + "\" to the current image.",
    "workerPool.seenNever": "never",
    "workerPool.seenJustNow": "just now",
    "workerPool.secondsAgo": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "s ago",
    "workerPool.minutesAgo": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "m ago",
    "workerPool.hoursAgo": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "h ago",
    "workerPool.daysAgo": (gaps: { readonly count: number }) => numberFormat.format(gaps.count) + "d ago",
    "workerPool.elapsedSeconds": (gaps: { readonly seconds: string }) => gaps.seconds + "s",
    "workerPool.elapsedMinutes": (gaps: { readonly minutes: string; readonly seconds: string }) => gaps.minutes + "m " + gaps.seconds + "s",
    "workerPool.elapsedHours": (gaps: { readonly hours: string; readonly minutes: string }) => gaps.hours + "h " + gaps.minutes + "m",
    "workerPool.loadModel": "Load model…",
    "workerPool.load": "Load",
    "workerPool.loadingAction": "Loading…",
    "workerPool.selectModel": "Select a model to load",
    "workerPool.enqueueFailed": "Failed to enqueue load",
    "workerPool.unloadFailed": "Failed to unload model",
    "workerPool.restartFailed": "Restart failed",
    "workerPool.keepLoadedFailed": "Failed to change Keep loaded",
    "workerPool.loadingToast": (gaps: { readonly mode: string; readonly worker: string }) => "Loading " + gaps.mode + " on " + gaps.worker + "…",
    "workerPool.unloadedToast": (gaps: { readonly mode: string; readonly worker: string }) => "Unloaded " + gaps.mode + " from " + gaps.worker,
    "workerPool.restartRequested": (gaps: { readonly worker: string }) => "Restart requested for " + gaps.worker,
    "workerPool.keepLoadedOff": (gaps: { readonly mode: string; readonly worker: string }) => "Keep loaded disabled for " + gaps.mode + " on " + gaps.worker,
    "workerPool.keepLoadedOn": (gaps: { readonly mode: string; readonly worker: string }) => "Keep loaded enabled for " + gaps.mode + " on " + gaps.worker,
    "workerPool.lastError": "Last error",
    "workerPool.fullLogs": (gaps: { readonly command: string }): readonly (string | { readonly marker: "code"; readonly text: string })[] => ["Full logs: ", { marker: "code", text: gaps.command }],
    "workerPool.restart": "Restart worker…",
    "workerPool.restarting": "Restarting…",
    "workerPool.restartTitle": (gaps: { readonly worker: string }) => "Restart " + gaps.worker + "?",
    "workerPool.restartWarning": "Running takes will stop.",
    "workerPool.restartConfirm": "Restart",
    "workerPool.models": "Models on this GPU",
    "workerPool.modelsLoading": (gaps: { readonly mode: string }) => "None yet — " + gaps.mode + " is loading.",
    "workerPool.modelsOffline": "Unknown while the worker is offline.",
    "workerPool.keepLoaded": "Keep loaded",
    "workerPool.keepLoadedHint": "Keep loaded — never unloaded to make room",
    "workerPool.keepLoadedModel": (gaps: { readonly mode: string }) => "Keep loaded " + gaps.mode,
    "workerPool.unload": "Unload",
    "workerPool.unloadModel": (gaps: { readonly mode: string }) => "Unload " + gaps.mode,
    "workerPool.modelSize": (gaps: { readonly size: string }) => "~" + gaps.size + " GB",
    "workerPool.vram": "VRAM",
    "workerPool.vramLabel": "VRAM:",
    "workerPool.vramUsed": (gaps: { readonly total: string; readonly used: string }) => gaps.used + " / " + gaps.total + " GB",
    "workerPool.vramUsedEstimated": (gaps: { readonly total: string; readonly used: string }) => "~" + gaps.used + " / " + gaps.total + " GB est.",
    "workerPool.vramFree": (gaps: { readonly free: string }) => gaps.free + " GB free",
    "workerPool.vramEstimateReason": "No GPU reading — the sizes of the loaded models, not a measurement",
    "workerPool.vramUnknown": "unknown",
    "workerPool.vramOffline": "VRAM unavailable while the worker is offline.",
    "workerPool.vramNoHeartbeat": "No heartbeat — nothing to read",
    "workerPool.vramNoTotal": "Worker does not report total VRAM",
    "workerPool.vramNoFields": "Worker build does not report VRAM fields",
    "modelRegistry.heading": "Model Registry",
    "modelRegistry.loading": "Loading registry…",
    "modelRegistry.loadFailed": "Cannot reach the registry API.",
    "modelRegistry.columnMode": "Mode",
    "modelRegistry.columnStatus": "Status",
    "modelRegistry.columnLoaded": "Loaded",
    "modelRegistry.columnLoading": "Loading",
    "modelRegistry.columnActions": "Actions",
    "modelRegistry.downloaded": "downloaded",
    "modelRegistry.stateUnknown": "no worker running — download state unknown",
    "modelRegistry.notDownloaded": "not downloaded",
    "modelRegistry.downloadingProgress": (gaps: { readonly percent: string }) => "Downloading… " + gaps.percent,
    "modelRegistry.noWorkerOnline": "No worker online to download it",
    "modelRegistry.starting": "Starting…",
    "modelRegistry.download": "Download",
    "modelRegistry.connectionLost": "Connection lost — retrying…",
    "modelRegistry.downloadingToast": (gaps: { readonly mode: string }) => "Downloading " + gaps.mode + "…",
    "modelRegistry.downloadFailed": "Failed to start download",
    "takeRetention.heading": "Take Retention",
    "takeRetention.explanation": "Takes that are neither picked nor kept are archived after the retention window, then permanently deleted after the hard-delete window.",
    "takeRetention.whatThisDoes": "What this does",
    "takeRetention.schedule": (gaps: { readonly hour: string }) => "Auto · daily " + gaps.hour + ":00 UTC",
    "takeRetention.loading": "Loading preview…",
    "takeRetention.days": (count: number) => ({
        zero: numberFormat.format(count) + " days",
        one: numberFormat.format(count) + " day",
        two: numberFormat.format(count) + " days",
        few: numberFormat.format(count) + " days",
        many: numberFormat.format(count) + " days",
        other: numberFormat.format(count) + " days",
    })[pluralRules.select(count)],
    "takeRetention.archiveAfter": "Archive after",
    "takeRetention.hardDeleteAfter": "Hard-delete after archive",
    "takeRetention.toArchive": "to archive now",
    "takeRetention.toHardDelete": "to hard-delete now",
    "takeRetention.nothingDue": "Nothing to clean up right now",
    "takeRetention.refresh": "Refresh",
    "takeRetention.runNow": "Run now",
    "takeRetention.confirm": (count: number, gaps: { readonly deleted: string }): readonly (string | { readonly marker: "strong"; readonly text: string })[] => ({
        zero: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " takes" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
        one: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " take" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
        two: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " takes" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
        few: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " takes" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
        many: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " takes" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
        other: ["Archive ", { marker: "strong", text: numberFormat.format(count) + " takes" }, " and permanently delete ", { marker: "strong", text: gaps.deleted }, ". Deleting cannot be undone."],
    } as const)[pluralRules.select(count)],
    "takeRetention.cancel": "Cancel",
    "takeRetention.running": "Running…",
    "takeRetention.delete": (gaps: { readonly count: number }) => "Delete " + numberFormat.format(gaps.count),
    "takeRetention.previewFailed": "Preview failed",
    "takeRetention.runFailed": "Cleanup failed",
    "takeRetention.outcome": (gaps: { readonly archived: string; readonly deleted: string }) => "Archived " + gaps.archived + ", deleted " + gaps.deleted,
    "generationRefusal.notFound": "Generation not found",
    "generationRefusal.someNotFound": "One or more generations not found",
    "generationRefusal.audioMissing": "Audio file not found",
    "voiceRefusal.notFound": "LoRA not found",
    "voiceRefusal.sampleNotFound": "LoRA sample not found",
    "conversationRefusal.notFound": "Conversation not found",
    "presetRefusal.notFound": "Preset not found",
    "modelRefusal.notFound": "Model not found",
    "workerRefusal.notFound": (gaps: { readonly workerId: string }) => "Worker '" + gaps.workerId + "' not found",
    "voicesPage.documentTitle": (gaps: { readonly app: string }) => "My Voices — " + gaps.app,
    "voicesPage.heading": "My Voices",
    "voicesPage.showDeleted": "Show deleted",
    "voicesPage.newVoice": "New Voice",
    "voicesPage.cancel": "Cancel",
    "voicesPage.namePlaceholder": "Voice name (e.g. My Tenor)",
    "voicesPage.creating": "Creating...",
    "voicesPage.create": "Create",
    "voicesPage.loading": "Loading voices...",
    "voicesPage.loadFailed": "Failed to load voices",
    "voicesPage.empty": "No voices yet. Create one to upload samples and train your own vocal style.",
    "voicesPage.sampleCount": (count: number) => ({
        zero: numberFormat.format(count) + " samples",
        one: numberFormat.format(count) + " sample",
        two: numberFormat.format(count) + " samples",
        few: numberFormat.format(count) + " samples",
        many: numberFormat.format(count) + " samples",
        other: numberFormat.format(count) + " samples",
    })[pluralRules.select(count)],
    "voicesPage.delete": "Delete",
    "voicesPage.deletedTag": "deleted",
    "voicesPage.statusDraft": "draft",
    "voicesPage.statusQueued": "queued",
    "voicesPage.statusPreprocessing": "preprocessing",
    "voicesPage.statusTraining": "training",
    "voicesPage.statusExporting": "exporting",
    "voicesPage.statusReady": "ready",
    "voicesPage.statusFailed": "failed",
    "voicesPage.created": "Voice created",
    "voicesPage.createFailed": "Could not create voice",
    "voicesPage.deletedToast": (gaps: { readonly name: string }) => "Deleted " + gaps.name,
    "voicesPage.deleteFailed": "Delete failed",
    "voicesPage.deleteTitle": "Delete voice?",
    "voicesPage.deleteWarning": (gaps: { readonly name: string }) => gaps.name + " will be hidden from new generations. Existing takes keep their audio and remain playable; they will show “voice deleted”.",
    "voiceDetail.deletedBanner": "This voice has been deleted. Editing is disabled.",
    "voiceDetail.trainingCancelled": "Training cancelled",
    "voiceDetail.lockedQueued": "Voice is queued — editing is locked until training finishes.",
    "voiceDetail.lockedPreprocessing": "Voice is preprocessing — editing is locked until training finishes.",
    "voiceDetail.lockedTraining": "Voice is training — editing is locked until training finishes.",
    "voiceDetail.lockedExporting": "Voice is exporting — editing is locked until training finishes.",
    "voiceDetail.trainingFailed": "Training failed",
    "voiceDetail.samples": "Samples",
    "voiceDetail.sampleCapacity": (gaps: { readonly max: string; readonly used: string }) => gaps.used + " / " + gaps.max,
    "voiceDetail.noSamples": (gaps: { readonly count: number }) => "No samples yet. Add at least " + numberFormat.format(gaps.count) + " to train.",
    "voiceDetail.samplePosition": (gaps: { readonly position: string }) => "#" + gaps.position,
    "voiceDetail.removeLabel": "Remove sample",
    "voiceDetail.remove": "Remove",
    "voiceDetail.removeConfirm": (gaps: { readonly position: string }) => "Remove sample at position " + gaps.position + "?",
    "voiceDetail.captionLabel": "Caption (style prompt)",
    "voiceDetail.lyricsLabel": "Lyrics",
    "voiceDetail.addSample": "Add sample",
    "voiceDetail.dropHint": ["Drag audio here, or ", { marker: "browse", text: "browse" }] as readonly (string | { readonly marker: "browse"; readonly text: string })[],
    "voiceDetail.sources": "Your takes and uploads only.",
    "voiceDetail.captionPlaceholder": "e.g. warm male vocal, folk guitar",
    "voiceDetail.lyricsPlaceholder": "Lyrics present in this audio clip",
    "voiceDetail.uploading": "Uploading...",
    "voiceDetail.sampleLimit": "Sample limit reached.",
    "voiceDetail.ownTakesOpen": "Use a take",
    "voiceDetail.ownTakesClose": "Close takes",
    "voiceDetail.ownTakes": "Your takes",
    "voiceDetail.ownTakesLoading": "Loading your takes...",
    "voiceDetail.ownTakesEmpty": "No playable takes yet.",
    "voiceDetail.takeNumber": (gaps: { readonly number: string }) => "Take " + gaps.number,
    "voiceDetail.adding": "Adding...",
    "voiceDetail.useTake": "Use as sample",
    "voiceDetail.waiting": "Waiting",
    "voiceDetail.training": "Training",
    "voiceDetail.cancel": "Cancel",
    "voiceDetail.waitingDefault": "Waiting for the worker.",
    "voiceDetail.queuePosition": (gaps: { readonly position: string }) => "Position " + gaps.position + " in the queue",
    "voiceDetail.progressLabel": "Training progress",
    "voiceDetail.epoch": (gaps: { readonly current: string; readonly total: string }) => "Epoch " + gaps.current + " of " + gaps.total,
    "voiceDetail.remainingCalculating": "Calculating remaining time...",
    "voiceDetail.remainingMinutes": (gaps: { readonly minutes: string }) => "~ " + gaps.minutes + "m remaining",
    "voiceDetail.remainingHours": (gaps: { readonly hours: string; readonly minutes: string }) => "~ " + gaps.hours + "h " + gaps.minutes + "m remaining",
    "voiceDetail.trainVoice": "Train voice",
    "voiceDetail.trainAgain": "Train again",
    "voiceDetail.starting": "Starting...",
    "voiceDetail.trainButtonQueued": "Training (queued)",
    "voiceDetail.trainButtonPreprocessing": "Training (preprocessing)",
    "voiceDetail.trainButtonTraining": "Training (training)",
    "voiceDetail.trainButtonExporting": "Training (exporting)",
    "voiceDetail.needSamples": (count: number, gaps: { readonly have: string }) => ({
        zero: "Need at least " + numberFormat.format(count) + " samples (have " + gaps.have + ")",
        one: "Need at least " + numberFormat.format(count) + " sample (have " + gaps.have + ")",
        two: "Need at least " + numberFormat.format(count) + " samples (have " + gaps.have + ")",
        few: "Need at least " + numberFormat.format(count) + " samples (have " + gaps.have + ")",
        many: "Need at least " + numberFormat.format(count) + " samples (have " + gaps.have + ")",
        other: "Need at least " + numberFormat.format(count) + " samples (have " + gaps.have + ")",
    })[pluralRules.select(count)],
    "voiceDetail.sampleTextsMissing": "Every sample needs a non-empty caption and lyrics",
    "voiceDetail.progressLoadFailed": "Could not load training progress",
    "voiceDetail.unsupportedFormat": (gaps: { readonly formats: string }) => "Unsupported format. Accepted: " + gaps.formats,
    "voiceDetail.pickFileFirst": "Pick an audio file first",
    "voiceDetail.captionLyricsRequired": "Caption and lyrics are required",
    "voiceDetail.sampleAdded": "Sample added",
    "voiceDetail.uploadFailed": "Upload failed",
    "voiceDetail.ownTakesLoadFailed": "Could not load takes",
    "voiceDetail.copyFailed": "Could not add take",
    "voiceDetail.saveFailed": "Save failed",
    "voiceDetail.deleteFailed": "Delete failed",
    "voiceDetail.queuedToast": "Training queued",
    "voiceDetail.startFailed": "Training failed to start",
    "voiceDetail.cancelFailed": "Could not cancel training",
    "referencesPage.documentTitle": (gaps: { readonly app: string }) => "References — " + gaps.app,
    "referencesPage.loading": "Loading references…",
    "referencesPage.loadFailed": "Failed to load references",
    "referencesPage.retry": "Try again",
    "referencesPage.empty": "No references yet — upload a recording to guide a song's sound.",
    "referencesPage.upload": "Upload",
    "referencesPage.uploadingName": (gaps: { readonly name: string }) => "Uploading " + gaps.name,
    "referencesPage.uploadFailed": "Couldn't upload this file",
    "referencesPage.filesFigure": (count: number, gaps: { readonly files: string }) => ({
        zero: gaps.files + " of " + numberFormat.format(count) + " files",
        one: gaps.files + " of " + numberFormat.format(count) + " file",
        two: gaps.files + " of " + numberFormat.format(count) + " files",
        few: gaps.files + " of " + numberFormat.format(count) + " files",
        many: gaps.files + " of " + numberFormat.format(count) + " files",
        other: gaps.files + " of " + numberFormat.format(count) + " files",
    })[pluralRules.select(count)],
    "referencesPage.sizeFigure": (gaps: { readonly limit: string; readonly used: string }) => gaps.used + " of " + gaps.limit + " MB",
    "referencesPage.storageFullFiles": (count: number, gaps: { readonly files: string }) => ({
        zero: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " files) — delete one first.",
        one: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " file) — delete one first.",
        two: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " files) — delete one first.",
        few: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " files) — delete one first.",
        many: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " files) — delete one first.",
        other: "Reference storage is full (" + gaps.files + " of " + numberFormat.format(count) + " files) — delete one first.",
    })[pluralRules.select(count)],
    "referencesPage.storageFullSize": (gaps: { readonly limit: string; readonly used: string }) => "Reference storage is full (" + gaps.used + " of " + gaps.limit + " MB) — delete one first.",
    "referencesPage.doesNotFit": (gaps: { readonly limit: string; readonly used: string }) => "That file doesn't fit (" + gaps.used + " of " + gaps.limit + " MB used) — delete one first.",
    "referencesPage.playFault": "Can't play this recording",
    "referencesPage.inUseFault": "In use — not deleted.",
    "referencesPage.deleteFailed": "Couldn't delete this recording",
    "referencesPage.keepFailed": "Couldn't keep this recording",
    "referencesPage.unkeepFailed": "Couldn't unkeep this recording",
    "referencesPage.deleteTitle": "Delete reference?",
    "referencesPage.deleteItem": (gaps: { readonly filename: string }) => gaps.filename + " — its audio file",
    "referenceRow.play": (gaps: { readonly filename: string }) => "Play " + gaps.filename,
    "referenceRow.pause": (gaps: { readonly filename: string }) => "Pause " + gaps.filename,
    "referenceRow.keep": (gaps: { readonly filename: string }) => "Keep " + gaps.filename,
    "referenceRow.unkeep": (gaps: { readonly filename: string }) => "Unkeep " + gaps.filename,
    "referenceRow.usedIn": (gaps: { readonly uses: string }) => "Used in " + gaps.uses,
    "referenceRow.takes": (count: number) => ({
        zero: numberFormat.format(count) + " takes",
        one: numberFormat.format(count) + " take",
        two: numberFormat.format(count) + " takes",
        few: numberFormat.format(count) + " takes",
        many: numberFormat.format(count) + " takes",
        other: numberFormat.format(count) + " takes",
    })[pluralRules.select(count)],
    "referenceRow.versions": (count: number) => ({
        zero: numberFormat.format(count) + " versions",
        one: numberFormat.format(count) + " version",
        two: numberFormat.format(count) + " versions",
        few: numberFormat.format(count) + " versions",
        many: numberFormat.format(count) + " versions",
        other: numberFormat.format(count) + " versions",
    })[pluralRules.select(count)],
    "referenceUses.loading": "Loading…",
    "referenceUses.loadFailed": "Couldn't load where it is used",
    "referenceUses.staysNote": "It stays while a take or version uses it.",
    "referenceUses.deletedTag": "Deleted",
    "referenceUses.archivedTag": "Archived",
    "referenceUses.take": (gaps: { readonly number: string }) => "Take " + gaps.number,
    "referenceUses.takeVersion": (gaps: { readonly number: string; readonly version: string }) => "Take " + gaps.number + " · v" + gaps.version,
    "referenceUses.takeLength": (gaps: { readonly length: string; readonly number: string }) => "Take " + gaps.number + " · " + gaps.length,
    "referenceUses.takeVersionLength": (gaps: { readonly length: string; readonly number: string; readonly version: string }) => "Take " + gaps.number + " · v" + gaps.version + " · " + gaps.length,
    "referenceUses.version": (gaps: { readonly version: string }) => "Version v" + gaps.version,
};
export type Key = keyof Words;
