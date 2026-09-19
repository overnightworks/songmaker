export type CreatedSort = 'newest' | 'oldest' | 'title';

export const CREATED_SORTS: readonly CreatedSort[] = ['newest', 'oldest', 'title'];

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
