import { pageLanguage } from './page-language.ts';

export type CreatedSort = 'newest' | 'oldest' | 'title';

export const CREATED_SORTS: readonly CreatedSort[] = ['newest', 'oldest', 'title'];

const titleCollators = new Map<string, Intl.Collator>();

/** The comparator that orders titles, ignoring case and accents and numbers by value, in one language. */
export function titleComparatorFor(language: string): (a: string, b: string) => number {
	let collator = titleCollators.get(language);
	if (collator === undefined) {
		collator = new Intl.Collator(language, { sensitivity: 'base', numeric: true });
		titleCollators.set(language, collator);
	}
	return collator.compare;
}

export function compareTitles(a: string, b: string): number {
	return titleComparatorFor(pageLanguage())(a, b);
}

function parseCreatedAt(iso: string | null | undefined): Date | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return null;
	return date;
}

export function compareByCreatedAt<
	T extends { id: string; created_at?: string | null; title?: string }
>(a: T, b: T, mode: CreatedSort): number {
	if (mode === 'title') {
		const titles = compareTitles(a.title ?? '', b.title ?? '');
		if (titles !== 0) return titles;
		return a.id.localeCompare(b.id);
	}
	const aTime = parseCreatedAt(a.created_at)?.getTime() ?? null;
	const bTime = parseCreatedAt(b.created_at)?.getTime() ?? null;
	if (aTime === null && bTime === null) return a.id.localeCompare(b.id);
	if (aTime === null) return 1;
	if (bTime === null) return -1;
	const delta = mode === 'newest' ? bTime - aTime : aTime - bTime;
	if (delta !== 0) return delta;
	return a.id.localeCompare(b.id);
}
