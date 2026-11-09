export const VERSION_CURRENT_TAG = 'current';
export const VERSION_PICKED_LABEL = 'picked';
export const VERSION_REPLACE_DRAFT_TITLE = 'Replace your unsaved draft?';
export const VERSION_REPLACE_DRAFT_CONFIRM_LABEL = 'Replace';
export const VERSION_DELETE_CONFIRM_LABEL = 'Delete version';
export const VERSION_DELETE_DRAFT_GOES = 'Your unsaved draft goes too.';
export const VERSION_DELETE_EMPTIES_EDITOR = 'Its lyrics leave the editor, which will be empty.';
export const VERSION_DELETE_LOAD_UNDO_GOES = 'Undo for your earlier draft goes too.';
export const VERSION_NO_LYRICS = 'No lyrics';
export const VERSIONS_SHEET_LABEL = 'Versions';
export const VERSIONS_SHEET_CLOSE_LABEL = 'Close versions';
export const TOAST_UNDO_LABEL = 'Undo';

const VERSION_CHIP_DRAFT_LABEL = 'draft';

export function versionLabel(versionNumber: number): string {
	return `v${versionNumber}`;
}

export function versionChipLabel(versionNumber: number, dirty: boolean): string {
	const version = versionLabel(versionNumber);
	return dirty ? `${version} · ${VERSION_CHIP_DRAFT_LABEL}` : version;
}

export function versionsChipAccessibleLabel(chipLabel: string): string {
	return `${VERSIONS_SHEET_LABEL}: ${chipLabel}`;
}

export function versionTakesLabel(count: number): string {
	if (count === 0) return 'no takes';
	return `${count} take${count === 1 ? '' : 's'}`;
}

export function versionDeleteLabel(versionNumber: number): string {
	return `Delete ${versionLabel(versionNumber)}`;
}

export function versionDeleteTitle(versionNumber: number, takeCount: number): string {
	const version = versionLabel(versionNumber);
	if (takeCount === 0) return `Delete ${version}?`;
	return `Delete ${version} and its ${versionTakesLabel(takeCount)}?`;
}

export function versionDeletePickWarning(takeCount: number): string {
	return takeCount === 1 ? 'It is the album pick.' : 'The album pick is one of them.';
}

export function versionDeleteReplacedBy(versionNumber: number): string {
	return `Its lyrics leave the editor; ${versionLabel(versionNumber)} replaces them.`;
}

export function versionDeleteLoadedDraftGoes(loadedFrom: number): string {
	return `The draft loaded from ${versionLabel(loadedFrom)} goes too.`;
}

export function versionDeleteLoadedDraftReplacedBy(loadedFrom: number, replacedBy: number): string {
	return `The draft loaded from ${versionLabel(loadedFrom)} leaves the editor; ${versionLabel(replacedBy)} replaces it.`;
}

export function versionLoadedFromLabel(versionNumber: number): string {
	return `Loaded from ${versionLabel(versionNumber)}`;
}

export function versionAlreadyTheDraftLabel(versionNumber: number): string {
	return `${versionLabel(versionNumber)} is already the draft`;
}

export function versionLoadedToastLabel(versionNumber: number): string {
	return `${versionLabel(versionNumber)} loaded`;
}

export function versionReplaceDraftMessage(versionNumber: number): string {
	return `Your draft has changes that are not in any version. Loading ${versionLabel(versionNumber)} replaces them. You can undo right after.`;
}
