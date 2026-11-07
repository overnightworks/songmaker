// Move › in the song ⋯ lists the person's own albums and moves the song while
// the person stays on it. Each cell runs at the desktop width, where the crumb
// names the new album, and at the phone width, where a toast does.

import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	DIALOG_CANCEL_LABEL,
	SONG_MENU_LABEL,
	SONG_MENU_MOVE_LABEL,
	SONG_MOVE_HEADING,
	SONG_MOVE_NO_OTHER_ALBUM,
	SONG_MOVE_SHARED_TITLE,
	songMovedToastLabel,
	songMoveSharedMessage
} from '../src/lib/constants';
import { FlowGuard, HOME_PATH, nameStartingWith, ONLY_IN_SHELL, type Shell } from './helpers';
import {
	archiveOwnedAlbum,
	BASE_URL,
	runMarker,
	seedAccount,
	signedInApi,
	type AccountRole,
	type SeededAccount
} from './seed';

const WIDTH_PX: Record<Shell, number> = { desktop: 1440, mobile: 375 };
const VIEWPORT_HEIGHT_PX = 844;
const SONG_TITLE = 'E2E Move song';
const SAVED_LYRICS = 'saved lyrics';
const DRAFT_LYRICS = 'E2E move draft that is not saved yet';

interface Created {
	id: string;
	slug: string;
}

interface Person {
	api: APIRequestContext;
	albumIds: string[];
}

let guard: FlowGuard;
let people: Person[] = [];

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
	people = [];
});

test.afterEach(async () => {
	try {
		guard.assertClean();
	} finally {
		for (const person of people) {
			for (const albumId of person.albumIds) await archiveOwnedAlbum(person.api, albumId);
			await person.api.dispose();
		}
	}
});

/** A flow's own account with its session; the flow archives the albums it made. */
async function newPerson(
	name: string,
	role: AccountRole = 'user'
): Promise<{ person: Person; cookies: SeededAccount['cookies'] }> {
	const account = await seedAccount(`e2e-move-${name}-${runMarker()}`, role);
	const person: Person = { api: await signedInApi(account), albumIds: [] };
	people.push(person);
	return { person, cookies: account.cookies };
}

async function ownAlbum(person: Person, title: string): Promise<string> {
	const response = await person.api.post('/api/albums', {
		headers: { origin: BASE_URL },
		data: { title: `E2E Move ${runMarker()} ${title}`, artist: '' }
	});
	expect(response.ok()).toBe(true);
	const { id } = (await response.json()) as Created;
	person.albumIds.push(id);
	return id;
}

async function shareAlbum(person: Person, albumId: string): Promise<void> {
	const response = await person.api.post(`/api/albums/${albumId}/share`, {
		headers: { origin: BASE_URL },
		data: {}
	});
	expect(response.ok()).toBe(true);
}

async function albumIdOf(person: Person, songId: string): Promise<string> {
	const response = await person.api.get(`/api/songs/${songId}`);
	return ((await response.json()) as { album_id: string }).album_id;
}

async function titleOf(person: Person, albumId: string): Promise<string> {
	const response = await person.api.get(`/api/albums/${albumId}`);
	return ((await response.json()) as { title: string }).title;
}

async function ownSong(person: Person, albumId: string): Promise<Created> {
	const response = await person.api.post('/api/songs', {
		headers: { origin: BASE_URL },
		data: { title: SONG_TITLE, album_id: albumId, lyrics: SAVED_LYRICS, prompt: 'calm test tone' }
	});
	expect(response.ok()).toBe(true);
	return (await response.json()) as Created;
}

async function openSongAs(
	page: Page,
	shell: Shell,
	cookies: SeededAccount['cookies'],
	albumId: string,
	song: Created
): Promise<void> {
	await page.setViewportSize({ width: WIDTH_PX[shell], height: VIEWPORT_HEIGHT_PX });
	await page.context().clearCookies();
	await page.context().addCookies(cookies);
	await page.goto(HOME_PATH);
	await page.goto(`/album/${albumId}/${song.slug}`);
	await expect(page.getByRole('heading', { name: SONG_TITLE, exact: true })).toBeVisible();
	const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
	await expect(lyrics).toBeEnabled();
	await expect(lyrics).toHaveValue(SAVED_LYRICS);
}

async function openPicker(page: Page): Promise<Locator> {
	await page.getByRole('button', { name: SONG_MENU_LABEL, exact: true }).click();
	const menu = page.getByRole('dialog', { name: SONG_MENU_LABEL });
	// The row's › is drawn as content, so its accessible name reads "Move ›".
	await menu.getByRole('button', { name: nameStartingWith(SONG_MENU_MOVE_LABEL) }).click();
	await expect(menu.getByText(SONG_MOVE_HEADING, { exact: true })).toBeVisible();
	return menu;
}

function albumRow(menu: Locator, title: string): Locator {
	return menu.locator('.pk-row').filter({ hasText: title });
}

for (const shell of ['desktop', 'mobile'] as const) {
	test.describe(`Move at ${WIDTH_PX[shell]} px`, { tag: ONLY_IN_SHELL[shell] }, () => {
		test('the picker lists the persons own albums with the current one pinned', async ({
			page
		}) => {
			const { person, cookies } = await newPerson('list');
			const stranger = await newPerson('stranger');
			const currentId = await ownAlbum(person, 'Current');
			const otherId = await ownAlbum(person, 'Other');
			const foreignId = await ownAlbum(stranger.person, 'Foreign');
			const song = await ownSong(person, currentId);
			await openSongAs(page, shell, cookies, currentId, song);

			const menu = await openPicker(page);

			const current = menu.locator('.pk-row[aria-current="true"]');
			await expect(current).toContainText(await titleOf(person, currentId));
			await expect(current.locator('svg')).toBeVisible();
			await expect(albumRow(menu, await titleOf(person, otherId))).toBeVisible();
			await expect(albumRow(menu, await titleOf(stranger.person, foreignId))).toHaveCount(0);
		});

		test('a tap moves the song while the person stays on it with the same draft', async ({
			page
		}) => {
			const { person, cookies } = await newPerson('tap');
			const currentId = await ownAlbum(person, 'Current');
			const otherId = await ownAlbum(person, 'Other');
			const song = await ownSong(person, currentId);
			await openSongAs(page, shell, cookies, currentId, song);
			const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
			await lyrics.fill(DRAFT_LYRICS);
			const otherTitle = await titleOf(person, otherId);

			const menu = await openPicker(page);
			await albumRow(menu, otherTitle).click();

			await expect(menu).toBeHidden();
			await expect(page).toHaveURL(new RegExp(`/album/${otherId}/${song.slug}$`));
			await expect(page.getByRole('heading', { name: SONG_TITLE, exact: true })).toBeVisible();
			await expect(lyrics).toHaveValue(DRAFT_LYRICS);
			if (shell === 'desktop') {
				const crumb = page.getByRole('navigation', { name: 'Breadcrumb' });
				await expect(crumb.getByText(otherTitle, { exact: true })).toBeVisible();
			} else {
				await expect(
					page.getByRole('alert').filter({ hasText: songMovedToastLabel(otherTitle) })
				).toBeVisible();
			}
			const moved = await person.api.get(`/api/songs/${song.id}`);
			expect(((await moved.json()) as { album_id: string }).album_id).toBe(otherId);
		});

		test('history back does not return to the old address', async ({ page }) => {
			const { person, cookies } = await newPerson('back');
			const currentId = await ownAlbum(person, 'Current');
			const otherId = await ownAlbum(person, 'Other');
			const song = await ownSong(person, currentId);
			await openSongAs(page, shell, cookies, currentId, song);

			const menu = await openPicker(page);
			await albumRow(menu, await titleOf(person, otherId)).click();
			await expect(page).toHaveURL(new RegExp(`/album/${otherId}/${song.slug}$`));
			await page.goBack();

			await expect(page).not.toHaveURL(new RegExp(`/album/${currentId}/`));
			await expect(page).not.toHaveURL(new RegExp(`/album/${otherId}/${song.slug}$`));
		});

		test('with only one album the picker says there is no other album', async ({ page }) => {
			const { person, cookies } = await newPerson('solo');
			const onlyId = await ownAlbum(person, 'Only');
			const song = await ownSong(person, onlyId);
			await openSongAs(page, shell, cookies, onlyId, song);

			const menu = await openPicker(page);

			await expect(menu.getByText(SONG_MOVE_NO_OTHER_ALBUM, { exact: true })).toBeVisible();
			await expect(menu.locator('.pk-row')).toHaveCount(1);
		});

		test("an admin's picker does not list another person's album and the route refuses it", async ({
			page
		}) => {
			const { person: adminPerson, cookies } = await newPerson('admin', 'admin');
			const member = await newPerson('member');
			const adminAlbumId = await ownAlbum(adminPerson, 'Admin');
			const adminOtherId = await ownAlbum(adminPerson, 'Admin other');
			const memberAlbumId = await ownAlbum(member.person, 'Member');
			const song = await ownSong(adminPerson, adminAlbumId);
			await openSongAs(page, shell, cookies, adminAlbumId, song);

			const menu = await openPicker(page);

			await expect(albumRow(menu, await titleOf(adminPerson, adminOtherId))).toBeVisible();
			await expect(albumRow(menu, await titleOf(member.person, memberAlbumId))).toHaveCount(0);
			const refused = await adminPerson.api.put(`/api/songs/${song.id}/album`, {
				headers: { origin: BASE_URL },
				data: { album_id: memberAlbumId }
			});
			expect(refused.status()).toBe(404);
		});

		test('a shared album asks first: Cancel moves nothing and Move moves the song', async ({
			page
		}) => {
			const { person, cookies } = await newPerson('ask');
			const currentId = await ownAlbum(person, 'Current');
			const sharedId = await ownAlbum(person, 'Shared');
			await shareAlbum(person, sharedId);
			const song = await ownSong(person, currentId);
			await openSongAs(page, shell, cookies, currentId, song);
			const sharedTitle = await titleOf(person, sharedId);
			const asking = page.getByRole('dialog', { name: SONG_MOVE_SHARED_TITLE });

			const menu = await openPicker(page);
			await albumRow(menu, sharedTitle).click();

			await expect(asking).toBeVisible();
			await expect(asking).toContainText(songMoveSharedMessage(SONG_TITLE, sharedTitle));
			await asking.getByRole('button', { name: DIALOG_CANCEL_LABEL, exact: true }).click();
			await expect(asking).toBeHidden();
			expect(await albumIdOf(person, song.id)).toBe(currentId);

			const again = await openPicker(page);
			await albumRow(again, sharedTitle).click();
			await asking.getByRole('button', { name: SONG_MENU_MOVE_LABEL, exact: true }).click();

			await expect(page).toHaveURL(new RegExp(`/album/${sharedId}/${song.slug}$`));
			expect(await albumIdOf(person, song.id)).toBe(sharedId);
		});

		test('a private album moves the song at once without asking', async ({ page }) => {
			const { person, cookies } = await newPerson('private');
			const currentId = await ownAlbum(person, 'Current');
			const privateId = await ownAlbum(person, 'Private');
			const song = await ownSong(person, currentId);
			await openSongAs(page, shell, cookies, currentId, song);

			const menu = await openPicker(page);
			await albumRow(menu, await titleOf(person, privateId)).click();

			await expect(page).toHaveURL(new RegExp(`/album/${privateId}/${song.slug}$`));
			await expect(page.getByRole('dialog', { name: SONG_MOVE_SHARED_TITLE })).toHaveCount(0);
			expect(await albumIdOf(person, song.id)).toBe(privateId);
		});

		test('a move out of a shared album moves the song at once without asking', async ({ page }) => {
			const { person, cookies } = await newPerson('out');
			const sharedId = await ownAlbum(person, 'Shared');
			const privateId = await ownAlbum(person, 'Private');
			await shareAlbum(person, sharedId);
			const song = await ownSong(person, sharedId);
			await openSongAs(page, shell, cookies, sharedId, song);

			const menu = await openPicker(page);
			await albumRow(menu, await titleOf(person, privateId)).click();

			await expect(page).toHaveURL(new RegExp(`/album/${privateId}/${song.slug}$`));
			await expect(page.getByRole('dialog', { name: SONG_MOVE_SHARED_TITLE })).toHaveCount(0);
			expect(await albumIdOf(person, song.id)).toBe(privateId);
		});
	});
}
