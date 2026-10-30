export type TabStorage = Pick<Storage, 'getItem' | 'setItem'>;

// The names a browser refuses storage under: a full quota, a private mode that
// offers storage but will not keep anything in it, or site data blocked so that
// even reaching session storage is denied.
const STORAGE_REFUSALS: ReadonlySet<string> = new Set(['QuotaExceededError', 'SecurityError']);

function isStorageRefusal(error: unknown): boolean {
	return error instanceof DOMException && STORAGE_REFUSALS.has(error.name);
}

// The tab's counts live in session storage so that a reload keeps them. Once
// the browser refuses storage -- reaching it, reading it or writing it -- they
// live in this document's memory instead, seeded by whatever storage still
// gives and raised by every entry the document meets, rather than the page
// failing to render. Storage is never reached unguarded: not on use, and not
// while the module loads onto an entry and counts it.
export function tabStorage(reachStorage: () => TabStorage): TabStorage {
	let memoryAfterRefusal: Map<string, string> | null = null;

	function memoryAfter(error: unknown): Map<string, string> {
		if (!isStorageRefusal(error)) throw error;
		memoryAfterRefusal ??= new Map();
		return memoryAfterRefusal;
	}

	return {
		getItem: (key) => {
			const remembered = memoryAfterRefusal?.get(key);
			if (remembered !== undefined) return remembered;
			try {
				return reachStorage().getItem(key);
			} catch (error) {
				memoryAfter(error);
				return null;
			}
		},
		setItem: (key, value) => {
			if (memoryAfterRefusal !== null) {
				memoryAfterRefusal.set(key, value);
				return;
			}
			try {
				reachStorage().setItem(key, value);
			} catch (error) {
				memoryAfter(error).set(key, value);
			}
		}
	};
}
