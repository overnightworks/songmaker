import { readFileSync } from 'node:fs';
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';
import type { SongItem } from '../src/lib/api/types';
import {
	ACCOUNT_MENU_LOGOUT_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import {
	accountCircle,
	accountMenu,
	FlowGuard,
	nameStartingWith,
	observePlayingAudio,
	openRailNav,
	openLibraryWall,
	playingAudioState,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import {
	BASE_URL,
	STORAGE_STATE_FILE,
	TAKE_FIXTURE,
	createAccount,
	runMarker,
	seedUnpickedLibrary
} from './seed';

// The gate runs both configured shells: 390×844 and 1440×900. No synthetic
// playing/ended events: the same short fixture as queue-continuity really ends.
test.use({ serviceWorkers: 'block' });
// Account seeding and the two naturally advancing tabs share this allowance.
test.setTimeout(90_000);
const PASSWORD = 'E2eRetirement!2026';
const END_TIMEOUT_MS = 15_000;
const SLOW_PLAYBACK_RATE = 0.1;

interface RecoveryRecord {
	generationId: string;
	position: number;
}
interface StorageNotice {
	key: string | null;
	oldValue: string | null;
	newValue: string | null;
}
interface ProofLibrary {
	userId: string;
	username: string;
	albumId: string;
	song: SongItem;
	api: APIRequestContext;
}

async function apiHeaders(api: APIRequestContext): Promise<Record<string, string>> {
	const csrf = (await api.storageState()).cookies.find((cookie) => cookie.name === 'csrf_token');
	if (!csrf) throw new Error('Proof account has no CSRF cookie');
	return { 'x-csrf-token': csrf.value, origin: BASE_URL };
}

async function withProofLibrary(flow: (library: ProofLibrary) => Promise<void>): Promise<void> {
	const admin = await request.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE_FILE });
	const api = await request.newContext({ baseURL: BASE_URL });
	let albumId: string | undefined;
	try {
		const username = `e2e-retirement-${runMarker()}`;
		const userId = await createAccount(admin, username, PASSWORD);
		const library = await seedUnpickedLibrary(api, { username, password: PASSWORD });
		albumId = library.albumId;
		const response = await api.get(`/api/songs?album_id=${albumId}`);
		expect(response.ok()).toBe(true);
		const { items } = (await response.json()) as { items: SongItem[] };
		const song = items.find((item) => item.title === library.tracks[0].songTitle);
		if (!song) throw new Error('Seeded opening song is missing');
		const imported = await api.post(`/api/songs/${song.id}/reimport`, {
			headers: await apiHeaders(api),
			multipart: {
				mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
			}
		});
		expect(imported.ok()).toBe(true);
		await flow({ userId, username, albumId, song, api });
	} finally {
		// Retain the recognizable E2E album and its evidence, archived rather
		// than deleting the account and cascading away its music.
		try {
			if (albumId) {
				const archived = await api.post(`/api/albums/${albumId}/archive`, {
					headers: await apiHeaders(api)
				});
				expect(archived.ok()).toBe(true);
			}
		} finally {
			await api.dispose();
			await admin.dispose();
		}
	}
}

async function signIn(page: Page, library: ProofLibrary): Promise<void> {
	await page.goto('/login');
	await page.getByLabel('Username').fill(library.username);
	await page.getByLabel('Password').fill(PASSWORD);
	await page.getByRole('button', { name: 'Enter', exact: true }).click();
	await expect(workspace(page)).toBeVisible();
}

async function signOut(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') {
		await openLibraryWall(page, shell);
		await accountCircle(page).click();
		await accountMenu(page).getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL }).click();
	} else {
		const rail = await openRailNav(page, shell);
		await rail.getByRole('button', { name: 'Logout', exact: true }).click();
	}
	await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function observeStorage(page: Page): Promise<StorageNotice[]> {
	const notices: StorageNotice[] = [];
	await page.exposeFunction('reportRecoveryStorage', (notice: StorageNotice) =>
		notices.push(notice)
	);
	await page.addInitScript(() => {
		window.addEventListener('storage', (event) => {
			if (event.storageArea === localStorage) {
				Reflect.get(
					window,
					'reportRecoveryStorage'
				)({
					key: event.key,
					oldValue: event.oldValue,
					newValue: event.newValue
				});
			}
		});
	});
	return notices;
}

async function preparePage(page: Page, library: ProofLibrary): Promise<void> {
	await observePlayingAudio(page);
	// Album queues normally cycle. A one-song HTTP result gives the player a
	// finite queue with no successor; both takes remain selectable in its UI.
	await page.route('**/api/songs?*', async (route) => {
		if (new URL(route.request().url()).searchParams.get('album_id') !== library.albumId) {
			await route.continue();
			return;
		}
		const response = await route.fetch();
		const body = (await response.json()) as { items: SongItem[]; total: number };
		const items = body.items.filter((song) => song.id === library.song.id);
		await route.fulfill({ response, json: { ...body, items, total: items.length } });
	});
}

async function openTakes(page: Page, library: ProofLibrary, shell: Shell): Promise<void> {
	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(library.song.title) })
		.click();
	if (shell === 'mobile') await workspace(page).getByRole('tab', { name: /Takes/ }).click();
	await expect(workspace(page).locator('.take-row')).toHaveCount(2);
}

function transport(page: Page, label: string) {
	return page.getByRole('contentinfo').getByRole('button', { name: label, exact: true });
}

async function playTake(page: Page, index = 0, slow = true): Promise<void> {
	await workspace(page)
		.locator('.take-row')
		.nth(index)
		.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) })
		.click();
	await expect(transport(page, TRANSPORT_PAUSE_LABEL)).toHaveAttribute('aria-busy', 'false');
	if (slow) {
		await page.evaluate((rate) => {
			const element = Reflect.get(window, 'playingAudio') as HTMLMediaElement;
			element.playbackRate = rate;
		}, SLOW_PLAYBACK_RATE);
	}
}

async function recovery(page: Page, userId: string): Promise<RecoveryRecord | null> {
	return page.evaluate((id) => {
		const saved = JSON.parse(localStorage.getItem(`playbackResume:${id}`) ?? 'null');
		return saved === null ? null : { generationId: saved.generationId, position: saved.position };
	}, userId);
}

async function marker(page: Page, userId: string): Promise<string | null> {
	return page.evaluate((id) => localStorage.getItem(`playbackLogout:${id}`), userId);
}

async function advanceAndPause(page: Page): Promise<void> {
	const before = (await playingAudioState(page)).time;
	await expect
		.poll(
			async () => {
				const state = await playingAudioState(page);
				return state.paused ? 0 : state.time - before;
			},
			{ timeout: END_TIMEOUT_MS }
		)
		.toBeGreaterThan(0.3);
	await transport(page, TRANSPORT_PAUSE_LABEL).click();
	await expect.poll(async () => (await playingAudioState(page)).paused).toBe(true);
}

for (const tabs of [1, 2]) {
	test(`1354_52_C1: exhaustion retires recovery and ${tabs} tab(s) can save again`, async ({
		page,
		context
	}, info) => {
		await context.clearCookies();
		await withProofLibrary(async (library) => {
			const shell = shellOf(info);
			const guard = new FlowGuard(page);
			await preparePage(page, library);
			await signIn(page, library);
			await openTakes(page, library, shell);
			const receiver = tabs === 2 ? await context.newPage() : null;
			try {
				const notices = receiver ? await observeStorage(receiver) : [];
				const receiverGuard = receiver ? new FlowGuard(receiver) : null;
				if (receiver) {
					await preparePage(receiver, library);
					await openTakes(receiver, library, shell);
					await playTake(receiver);
				}
				await playTake(page, 0, false);
				await expect.poll(() => recovery(page, library.userId)).not.toBeNull();
				const firstTake = (await recovery(page, library.userId))?.generationId;
				await expect
					.poll(() => recovery(page, library.userId), { timeout: END_TIMEOUT_MS })
					.toBeNull();
				expect(await marker(page, library.userId)).toBeNull();
				if (receiver) {
					await expect
						.poll(() =>
							notices.some(
								(event) =>
									event.key === `playbackResume:${library.userId}` && event.newValue === null
							)
						)
						.toBe(true);
					await advanceAndPause(receiver);
					const saved = await recovery(receiver, library.userId);
					expect(saved?.position).toBeGreaterThan(0);
					await receiver.reload();
					await expect(transport(receiver, TRANSPORT_PLAY_LABEL)).toBeVisible();
					await expect(receiver.getByRole('contentinfo')).toContainText(library.song.title);
					expect(await recovery(receiver, library.userId)).toEqual(saved);
				}
				// This stays in the originating document: a reload would hide
				// accidental suppression by resetting the recovery module.
				await playTake(page, 1);
				await advanceAndPause(page);
				expect((await recovery(page, library.userId))?.generationId).not.toBe(firstTake);
				expect((await recovery(page, library.userId))?.position).toBeGreaterThan(0);
				guard.assertClean();
				receiverGuard?.assertClean();
			} finally {
				await receiver?.close();
			}
		});
	});
}

for (const record of ['present', 'absent'] as const) {
	for (const observedTab of ['originating', 'receiving'] as const) {
		test(`1354_52_C2: logout with record ${record}, observed in ${observedTab} tab`, async ({
			page,
			context
		}, info) => {
			await context.clearCookies();
			await withProofLibrary(async (library) => {
				const shell = shellOf(info);
				const guard = new FlowGuard(page);
				await preparePage(page, library);
				await signIn(page, library);
				await openTakes(page, library, shell);
				const receiver = await context.newPage();
				try {
					const receiverGuard = new FlowGuard(receiver);
					const notices = await observeStorage(receiver);
					await preparePage(receiver, library);
					await openTakes(receiver, library, shell);
					await playTake(receiver);
					await advanceAndPause(receiver);
					expect(await recovery(receiver, library.userId)).not.toBeNull();
					if (record === 'absent') {
						await page.evaluate(
							(id) => localStorage.removeItem(`playbackResume:${id}`),
							library.userId
						);
					}
					const previousMarker = await marker(page, library.userId);
					await signOut(page, shell);
					await expect
						.poll(
							() =>
								notices.filter(
									(event) =>
										event.key === `playbackLogout:${library.userId}` && event.newValue !== null
								).length
						)
						.toBe(1);
					const logoutMarker = await marker(receiver, library.userId);
					expect(logoutMarker).not.toBeNull();
					expect(logoutMarker).not.toBe(previousMarker);
					const observed = observedTab === 'originating' ? page : receiver;
					expect(await recovery(observed, library.userId)).toBeNull();
					// Keep the receiving document alive; its cached media plays
					// despite the shared cookie being gone. A navigation proves less.
					const receiverUrl = receiver.url();
					await transport(receiver, TRANSPORT_PLAY_LABEL).click();
					await advanceAndPause(receiver);
					expect(receiver.url()).toBe(receiverUrl);
					expect(await recovery(receiver, library.userId)).toBeNull();
					expect(await marker(receiver, library.userId)).toBe(logoutMarker);
					expect(
						notices.filter((event) => event.key === `playbackLogout:${library.userId}`)
					).toHaveLength(1);
					guard.assertClean();
					receiverGuard.assertClean();
				} finally {
					await receiver.close();
				}
			});
		});
	}
}

for (const lifecycle of ['foreign viewer', 'reauthentication', 'session expiry'] as const) {
	test(`1354_52_C3: ${lifecycle} preserves the recovery boundary`, async ({
		page,
		context
	}, info) => {
		await context.clearCookies();
		await withProofLibrary(async (library) => {
			const shell = shellOf(info);
			const guard = new FlowGuard(page, {
				refusalsExpectedOn:
					lifecycle === 'session expiry' ? [{ path: '/api/auth/me', statuses: [401] }] : []
			});
			await preparePage(page, library);
			await signIn(page, library);
			await openTakes(page, library, shell);
			await playTake(page);
			await advanceAndPause(page);
			const saved = await recovery(page, library.userId);
			expect(saved?.position).toBeGreaterThan(0);
			if (lifecycle === 'foreign viewer') {
				const other = await context.newPage();
				try {
					const notices = await observeStorage(page);
					// Install the observer in the existing document too, without
					// replacing it and resetting the suppression being tested.
					await page.evaluate(() =>
						window.addEventListener('storage', (event) => {
							Reflect.get(
								window,
								'reportRecoveryStorage'
							)({ key: event.key, oldValue: event.oldValue, newValue: event.newValue });
						})
					);
					await other.goto('/login');
					await other.evaluate(() =>
						localStorage.setItem('playbackLogout:foreign-viewer', crypto.randomUUID())
					);
					await expect
						.poll(() => notices.some((event) => event.key === 'playbackLogout:foreign-viewer'))
						.toBe(true);
					expect(await recovery(page, library.userId)).toEqual(saved);
					await transport(page, TRANSPORT_PLAY_LABEL).click();
					await advanceAndPause(page);
					expect((await recovery(page, library.userId))?.position).toBeGreaterThan(
						saved?.position ?? 0
					);
				} finally {
					await other.close();
				}
			} else if (lifecycle === 'reauthentication') {
				await signOut(page, shell);
				await signIn(page, library);
				await openTakes(page, library, shell);
				await playTake(page, 1);
				await advanceAndPause(page);
				expect((await recovery(page, library.userId))?.position).toBeGreaterThan(0);
			} else {
				// Existing auth.test.ts also pins both checkAuth's 401 and
				// handleSessionLost; this drives the HTTP refusal at the page.
				await page.route('**/api/auth/me', (route) =>
					route.fulfill({
						status: 401,
						json: { detail: 'Session expired' }
					})
				);
				await page.reload();
				await expect(page).toHaveURL(/\/login(?:\?|$)/);
				expect(await recovery(page, library.userId)).toEqual(saved);
				expect(await marker(page, library.userId)).toBeNull();
			}
			guard.assertClean();
		});
	});
}
