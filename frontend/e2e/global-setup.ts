// One seeded admin session per run: the seed API context carries it, seeds the
// library and leaves its session cookies behind as the storage state every
// test reuses. No password is posted.

import {
	STORAGE_STATE_FILE,
	seedAdminAccount,
	seedLibrary,
	signedInApi,
	writeSeededLibrary
} from './seed';

export default async function globalSetup(): Promise<void> {
	const api = await signedInApi(await seedAdminAccount());
	try {
		writeSeededLibrary(await seedLibrary(api));
		await api.storageState({ path: STORAGE_STATE_FILE });
	} finally {
		await api.dispose();
	}
}
