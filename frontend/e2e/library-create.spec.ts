// + NEW on the Library head makes an album or a playlist from the wall, even
// from an empty library (#1149, #1166, #915 F2a/F2b; pictures N1–N5 in
// docs/design/navigation.html).
// The empty library is this user's own library answered empty on the wire, so
// the first-album path runs against the seeded stack; creating the album and
// opening its page are real.

import { expect, test, type Page, type Route } from '@playwright/test';
import {
	LIBRARY_NEW_ALBUM_LABEL,
	LIBRARY_NEW_MENU_LABEL,
	LIBRARY_NEW_PLAYLIST_LABEL,
	LIBRARY_WALL_EMPTY,
	NEW_ALBUM_CARD_LABEL,
	NEW_ALBUM_CLOSE_LABEL,
	NEW_ALBUM_TITLE_LABEL,
	NEW_PLACE_CREATE_LABEL,
	NEW_PLAYLIST_CARD_LABEL,
	NEW_PLAYLIST_CLOSE_LABEL,
	NEW_PLAYLIST_NAME_LABEL
} from '../src/lib/constants';
import { boundingBoxes, FlowGuard, shellOf, workspace } from './helpers';

/**
 * Sized before the first CI measurement from the cold wall open (auth, the
 * album and playlist lists, Continue, the live stream) plus one album create
 * and the album page's own loads; the CI log line below is the measurement to
 * tighten it against.
 */
const LIBRARY_CREATE_FLOW_API_REQUEST_BUDGET = 35;

const EMPTY_LIST_ANSWERS: Record<string, unknown> = {
	'/api/albums': { items: [], total: 0, offset: 0, limit: 50, has_more: false },
	'/api/playlists': [],
	'/api/library/continue': { items: [] }
};

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Library-create flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(LIBRARY_CREATE_FLOW_API_REQUEST_BUDGET);
});

async function answerTheLibraryEmpty(page: Page): Promise<void> {
	await page.route(
		(url) => url.pathname in EMPTY_LIST_ANSWERS,
		(route: Route) => {
			const answer = EMPTY_LIST_ANSWERS[new URL(route.request().url()).pathname];
			if (route.request().method() !== 'GET') return route.fallback();
			return route.fulfill({ json: answer });
		}
	);
}

function newButton(page: Page) {
	return workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true });
}

function newMenu(page: Page) {
	return page.getByRole('dialog', { name: LIBRARY_NEW_MENU_LABEL });
}

test('an empty library makes its first album from + New on the Library head and opens it', async ({
	page
}, testInfo) => {
	const title = `Night Drive ${shellOf(testInfo)} ${Date.now()}`;
	await answerTheLibraryEmpty(page);
	await page.goto('/');

	const wall = workspace(page);
	const libraryTitle = wall.getByRole('heading', { name: 'Library', level: 1 });
	await expect(wall.getByText(LIBRARY_WALL_EMPTY)).toBeVisible();
	await expect(newButton(page)).toBeVisible();
	const [titleBox, newBox] = await boundingBoxes(libraryTitle, newButton(page));
	expect(newBox.y).toBeLessThan(titleBox.y + titleBox.height);
	expect(newBox.y + newBox.height).toBeGreaterThan(titleBox.y);
	expect(newBox.x + newBox.width).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);

	await newButton(page).click();
	await expect(newMenu(page)).toBeVisible();
	await expect(newButton(page)).toHaveAttribute('aria-expanded', 'true');
	await page.goBack();
	await expect(newMenu(page)).toBeHidden();
	await expect(newButton(page)).toBeFocused();
	await expect(libraryTitle).toBeVisible();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_ALBUM_LABEL }).click();
	const card = wall.getByRole('form', { name: NEW_ALBUM_CARD_LABEL });
	await expect(card).toBeVisible();
	await card.getByRole('button', { name: NEW_ALBUM_CLOSE_LABEL }).click();
	await expect(card).toBeHidden();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_ALBUM_LABEL }).click();
	await card.getByLabel(NEW_ALBUM_TITLE_LABEL).fill(title);
	await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

	await expect(page).toHaveURL(/\/album\//);
	await expect(workspace(page).getByRole('heading', { name: title })).toBeVisible();
});

test('+ New makes a named playlist from the Library head and opens it', async ({
	page
}, testInfo) => {
	const name = `Road Trip ${shellOf(testInfo)} ${Date.now()}`;
	await page.goto('/');
	const wall = workspace(page);

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	const card = wall.getByRole('form', { name: NEW_PLAYLIST_CARD_LABEL });
	await expect(card).toBeVisible();
	await card.getByRole('button', { name: NEW_PLAYLIST_CLOSE_LABEL }).click();
	await expect(card).toBeHidden();
	await expect(newButton(page)).toBeFocused();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	await expect(card).toBeVisible();
	await page.goBack();
	await expect(card).toBeHidden();
	await expect(newButton(page)).toBeFocused();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	await card.getByLabel(NEW_PLAYLIST_NAME_LABEL).fill(name);
	await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

	await expect(page).toHaveURL(/\/playlist\//);
	await expect(workspace(page).getByRole('heading', { name })).toBeVisible();
});
