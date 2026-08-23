// One login per run: the seed API context logs in, seeds the library and
// leaves its session cookies behind as the storage state every test reuses.

import { request } from '@playwright/test';
import { BASE_URL, STORAGE_STATE_FILE, seedLibrary, writeSeededLibrary } from './seed';

export default async function globalSetup(): Promise<void> {
	const api = await request.newContext({ baseURL: BASE_URL });
	try {
		writeSeededLibrary(await seedLibrary(api));
		await api.storageState({ path: STORAGE_STATE_FILE });
	} finally {
		await api.dispose();
	}
}
