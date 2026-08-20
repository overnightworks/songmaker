export type CreatedSort = 'newest' | 'oldest' | 'title';

export const CREATED_SORTS: readonly CreatedSort[] = ['newest', 'oldest', 'title'];

export const CREATED_SORT_LABELS: Record<CreatedSort, string> = {
	newest: 'Newest',
	oldest: 'Oldest',
	title: 'Title'
};

const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export function parseCreatedAt(iso: string | null | undefined): Date | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return null;
	return date;
}

export function formatRelativeAge(iso: string | null | undefined, now: Date = new Date()): string {
	const date = parseCreatedAt(iso);
	if (!date) return 'unknown';
	const delta = now.getTime() - date.getTime();
	if (delta < 0) return 'soon';
	if (delta < MINUTE_MS) return `${Math.floor(delta / SECOND_MS)}s`;
	if (delta < HOUR_MS) return `${Math.floor(delta / MINUTE_MS)}m`;
	if (delta < DAY_MS) return `${Math.floor(delta / HOUR_MS)}h`;
	return `${Math.floor(delta / DAY_MS)}d`;
}

export function formatExactLocalTime(iso: string | null | undefined): string {
	const date = parseCreatedAt(iso);
	if (!date) return 'unknown time';
	return date.toLocaleString();
}

export function compareByCreatedAt<T extends { id: string; created_at?: string | null; title?: string }>(
	a: T,
	b: T,
	mode: CreatedSort
): number {
	if (mode === 'title') {
		const titles = (a.title ?? '').localeCompare(b.title ?? '');
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
