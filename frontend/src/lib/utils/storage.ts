// Private browsing, a full quota or blocked site data: remembering is a
// comfort, so the app goes on and simply nothing is remembered (#1209).
export function readStorage(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

export function writeStorage(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		// Nothing is remembered; see readStorage.
	}
}

export function removeStorage(key: string): void {
	try {
		localStorage.removeItem(key);
	} catch {
		// Storage that cannot be reached holds no record to forget.
	}
}
