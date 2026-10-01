// What was typed in a create card's title field, kept for the session (issue
// #1184) and keyed by card kind; clearAuth() resets it so a session that ends
// without a page reload hands nothing typed to the next musician on this tab.
const titleDrafts = new Map<string, string>();

export function titleDraft(key: string): string | undefined {
	return titleDrafts.get(key);
}

export function keepTitleDraft(key: string, title: string): void {
	if (title.trim() === '') titleDrafts.delete(key);
	else titleDrafts.set(key, title);
}

export function dropTitleDraft(key: string): void {
	titleDrafts.delete(key);
}

export function resetTitleDrafts(): void {
	titleDrafts.clear();
}
