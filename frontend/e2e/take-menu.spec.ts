// The take ⋯ stands on the same popover as the album's and the song's (#1507,
// #915 slice 3b): fully on screen whichever take it belongs to, in the album
// form, and in the same place on every open. The operator's drive of
// 16.10.2026 found the old absolute panel clipped or invisible on every
// second tap -- a layout promise only a real browser measures. Phone cells run
// in the mobile project (the Takes tab carries the rows there), laptop cells
// in the desktop one (the takes column beside the lyrics).

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	DIALOG_CANCEL_LABEL,
	HITBOX_FREQUENT_PX,
	TAKE_COVER_LABEL,
	TAKE_DELETE_LABEL,
	TAKE_OVERFLOW_LABEL,
	TAKE_PLAYLIST_LABEL,
	TAKE_REPAINT_LABEL,
	TAKE_SHARE_LABEL
} from '../src/lib/constants';
import { TAKE_USE_SEED_LABEL } from '../src/lib/constants/take-task';
import {
	boundingBoxes,
	csrfHeaders,
	FlowGuard,
	nameStartingWith,
	ONLY_IN_SHELL,
	type RenderedBox,
	type Shell
} from './helpers';
import { bottomOf, expectMenuInsideViewport, rightOf, VIEWPORT_MARGIN_PX } from './menu-viewport';
import { archiveOwnedAlbum, seedSongPhoneSong, seedTakeStripSong } from './seed';

const VIEWPORT_HEIGHT_PX = 844;
const ALBUM_FORM_MENU_WIDTH_PX = 238;
const SONG_TITLE = 'Take menu cells';
const TAKE_COUNT = 16;
const MIDDLE_TAKE_INDEX = TAKE_COUNT / 2;
const FIRST_TAKE_SEED = 4127730;
const FOOT_OF_LIST_REACH_PX = HITBOX_FREQUENT_PX;
const SAME_PLACE_TOLERANCE_PX = 0.5;
const ROW_LABELS_IN_ORDER = [
	TAKE_REPAINT_LABEL,
	TAKE_COVER_LABEL,
	TAKE_PLAYLIST_LABEL,
	TAKE_SHARE_LABEL,
	TAKE_DELETE_LABEL
];

/**
 * Own album and song per flow, seeded straight into the database with
 * `TAKE_COUNT` takes, so a flow costs the API what a cold song open costs.
 * Measured locally: 20 requests for every flow, 22 with the first take
 * played or shared.
 */
const TAKE_MENU_FLOW_API_REQUEST_BUDGET = 30;

interface Cell {
	shell: Shell;
	width: number;
}

const CELLS: Cell[] = [
	{ shell: 'mobile', width: 390 },
	{ shell: 'desktop', width: 1024 },
	{ shell: 'desktop', width: 1280 }
];

interface TakePosition {
	name: string;
	index: number;
	listScrolledToFoot: boolean;
}

const TAKE_POSITIONS: TakePosition[] = [
	{ name: 'first take', index: 0, listScrolledToFoot: false },
	{ name: 'middle take', index: MIDDLE_TAKE_INDEX, listScrolledToFoot: false },
	{ name: 'last take', index: TAKE_COUNT - 1, listScrolledToFoot: false },
	{ name: 'lowest reachable row', index: TAKE_COUNT - 1, listScrolledToFoot: true }
];

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Take-menu flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(TAKE_MENU_FLOW_API_REQUEST_BUDGET);
});

async function onOwnTakes(
	page: Page,
	{ shell, width }: Cell,
	flow: () => Promise<void>,
	takeSeedBase?: number
): Promise<void> {
	await page.setViewportSize({ width, height: VIEWPORT_HEIGHT_PX });
	const headers = await csrfHeaders(page);
	const album = await page.request.post('/api/albums', {
		headers,
		data: { title: `E2E Take menu ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	const { id: albumId } = (await album.json()) as { id: string };
	try {
		const songId =
			takeSeedBase === undefined
				? await seedTakeStripSong(albumId, SONG_TITLE, TAKE_COUNT)
				: await seedSongPhoneSong(albumId, SONG_TITLE, 1, TAKE_COUNT, takeSeedBase);
		const song = await page.request.get(`/api/songs/${songId}`);
		expect(song.ok()).toBe(true);
		const { slug } = (await song.json()) as { slug: string };
		await page.goto(`/album/${albumId}/${slug}`);
		await expect(page.getByRole('heading', { name: SONG_TITLE, exact: true })).toBeVisible();
		if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
		await expect(takeMenuTriggers(page)).toHaveCount(TAKE_COUNT);
		await flow();
	} finally {
		// 1354_65_D3: every menu flow archives through the seed owner.
		await archiveOwnedAlbum(page.request, albumId);
	}
}

function takeMenuTriggers(page: Page): Locator {
	return page.locator('.take-row').getByRole('button', { name: TAKE_OVERFLOW_LABEL, exact: true });
}

function takeMenu(page: Page): Locator {
	return page.getByRole('dialog', { name: TAKE_OVERFLOW_LABEL, exact: true });
}

/**
 * The lowest a take's trigger can stand. No trigger sits within 44 px of the
 * viewport bottom: the scroll area holding the list ends above the transport
 * bar. The lowest a clickable trigger gets is its bottom on that scroll
 * area's bottom edge; returns the area's box to measure that against.
 */
async function scrollToFootOfList(trigger: Locator): Promise<RenderedBox> {
	return trigger.evaluate((node) => {
		node.scrollIntoView({ block: 'end' });
		let area = node.parentElement;
		while (
			area &&
			!(
				area.scrollHeight > area.clientHeight &&
				/auto|scroll/.test(getComputedStyle(area).overflowY)
			)
		)
			area = area.parentElement;
		if (!area) throw new Error('Expected the takes list to sit in a scrolling area');
		const { x, y, width, height } = area.getBoundingClientRect();
		return { x, y, width, height };
	});
}

function expectTriggerAtFootOf(triggerBox: RenderedBox, scrollArea: RenderedBox): void {
	expect(Math.abs(bottomOf(scrollArea) - bottomOf(triggerBox))).toBeLessThanOrEqual(
		FOOT_OF_LIST_REACH_PX
	);
}

async function dangerColor(page: Page): Promise<string> {
	return page.evaluate(() => {
		const probe = document.createElement('span');
		probe.style.color = 'var(--score-bad)';
		document.body.append(probe);
		const { color } = getComputedStyle(probe);
		probe.remove();
		return color;
	});
}

async function expectAlbumForm(page: Page, menu: Locator): Promise<void> {
	const rows = menu.getByRole('button');
	await expect(rows).toHaveCount(ROW_LABELS_IN_ORDER.length);
	for (const [index, label] of ROW_LABELS_IN_ORDER.entries()) {
		await expect(rows.nth(index)).toContainText(label);
		await expect(rows.nth(index).locator('svg')).toHaveCount(1);
	}
	for (const rowBox of await boundingBoxes(...(await rows.all())))
		expect(rowBox.height).toBeCloseTo(HITBOX_FREQUENT_PX, 0);

	const heading = menu.locator('.menu-heading');
	await expect(heading).toHaveText(/^Take · (v\d+ · )?\d+$/);
	await expect(heading).toHaveCSS('text-transform', 'uppercase');
	await expect(page.locator('.menu-backdrop')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');

	const [panel] = await boundingBoxes(menu);
	expect(panel.width).toBeCloseTo(ALBUM_FORM_MENU_WIDTH_PX, 0);

	const danger = await dangerColor(page);
	await expect(rows.last()).toHaveText(TAKE_DELETE_LABEL);
	await expect(rows.last()).toHaveCSS('color', danger);
	await expect(rows.first()).not.toHaveCSS('color', danger);
}

/** Opens the trigger's menu and holds it to the album form, fully on screen; returns where the panel stands. */
async function openCheckedMenu(page: Page, trigger: Locator, cell: Cell): Promise<RenderedBox> {
	await trigger.click();
	const menu = takeMenu(page);
	await expect(menu).toBeVisible();
	await expect(trigger).toHaveAttribute('aria-expanded', 'true');

	await expectMenuInsideViewport(page, menu);
	await expectAlbumForm(page, menu);
	const [panel] = await boundingBoxes(menu);
	if (cell.shell === 'mobile')
		expect(rightOf(panel)).toBeCloseTo(cell.width - VIEWPORT_MARGIN_PX, 0);
	return panel;
}

async function closeWithEscape(page: Page, trigger: Locator): Promise<void> {
	await page.keyboard.press('Escape');
	await expect(takeMenu(page)).toBeHidden();
	await expect(trigger).toHaveAttribute('aria-expanded', 'false');
}

function expectSamePlace(second: RenderedBox, first: RenderedBox): void {
	for (const edge of ['x', 'y', 'width', 'height'] as const)
		expect(Math.abs(second[edge] - first[edge])).toBeLessThanOrEqual(SAME_PLACE_TOLERANCE_PX);
}

interface GridCell {
	ids: string;
	position: TakePosition;
	cell: Cell;
}

/** T1-T24: every take position at every width, each opened twice (T1 is the first open, T2 the second). */
const GRID: GridCell[] = TAKE_POSITIONS.flatMap((position, positionIndex) =>
	CELLS.map((cell, cellIndex) => {
		const firstOpen = (positionIndex * CELLS.length + cellIndex) * 2 + 1;
		return { ids: `T${firstOpen}-T${firstOpen + 1}`, position, cell };
	})
);

for (const { ids, position, cell } of GRID) {
	test(
		`915_C3 ${ids}: the ${position.name}'s ⋯ opens fully on screen in the album form at ${cell.width} px, and again in the same place`,
		{ tag: ONLY_IN_SHELL[cell.shell] },
		async ({ page }, testInfo: TestInfo) => {
			await onOwnTakes(page, cell, async () => {
				const trigger = takeMenuTriggers(page).nth(position.index);
				const scrollArea = position.listScrolledToFoot
					? await scrollToFootOfList(trigger)
					: undefined;
				const [triggerBox] = await boundingBoxes(trigger);
				if (scrollArea) expectTriggerAtFootOf(triggerBox, scrollArea);

				const first = await openCheckedMenu(page, trigger, cell);
				if (scrollArea) expect(bottomOf(first)).toBeLessThanOrEqual(triggerBox.y);
				await closeWithEscape(page, trigger);
				const second = await openCheckedMenu(page, trigger, cell);

				expectSamePlace(second, first);
				await testInfo.attach(`take-menu-${position.name}-at-${cell.width}px`, {
					body: await page.screenshot(),
					contentType: 'image/png'
				});
			});
		}
	);
}

test.describe('Use seed row', () => {
	for (const cell of CELLS) {
		test(
			`1928 T29: a take with a seed lists Use seed third, with the seed as its hint, at ${cell.width} px`,
			{ tag: ONLY_IN_SHELL[cell.shell] },
			async ({ page }) => {
				await onOwnTakes(
					page,
					cell,
					async () => {
						for (const index of [0, MIDDLE_TAKE_INDEX, TAKE_COUNT - 1]) {
							const trigger = takeMenuTriggers(page).nth(index);
							await trigger.click();
							const rows = takeMenu(page).getByRole('button');
							await expect(rows).toHaveCount(ROW_LABELS_IN_ORDER.length + 1);
							await expect(rows.nth(2)).toContainText(TAKE_USE_SEED_LABEL);
							await expect(rows.nth(2).locator('.menu-item-hint')).toHaveText(
								String(FIRST_TAKE_SEED + TAKE_COUNT - 1 - index)
							);
							await expect(rows.nth(2).locator('svg')).toHaveCount(1);
							await closeWithEscape(page, trigger);
						}
					},
					FIRST_TAKE_SEED
				);
			}
		);
	}
});

test(
	'915_C3 T25: Delete asks first, and Cancel keeps the take',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		await onOwnTakes(page, CELLS[0], async () => {
			await takeMenuTriggers(page).first().click();
			await takeMenu(page).getByRole('button', { name: TAKE_DELETE_LABEL, exact: true }).click();

			const confirm = page.getByRole('dialog', { name: /^Delete take \d+\?$/ });
			await expect(confirm).toBeVisible();
			await expect(confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL })).toBeFocused();
			await confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();

			await expect(confirm).toBeHidden();
			await expect(takeMenuTriggers(page)).toHaveCount(TAKE_COUNT);
		});
	}
);

test(
	'915_C3 T26: Share toggles in place: one tap shares, the next unshares, and the menu stays open',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await onOwnTakes(page, CELLS[2], async () => {
			await takeMenuTriggers(page).nth(MIDDLE_TAKE_INDEX).click();
			const menu = takeMenu(page);
			const share = menu.getByRole('button', { name: TAKE_SHARE_LABEL, exact: true });
			const hint = share.locator('.menu-item-hint');
			await expect(share).toHaveAttribute('aria-pressed', 'false');
			await expect(hint).toHaveText('off');

			await share.click();
			await expect(share).toHaveAttribute('aria-pressed', 'true');
			await expect(hint).toHaveText('on');
			await expect(menu).toBeVisible();

			await share.click();
			await expect(share).toHaveAttribute('aria-pressed', 'false');
			await expect(hint).toHaveText('off');
			await expect(menu).toBeVisible();
		});
	}
);

test(
	"915_C3 T27: Escape closes the menu and hands the focus back to the row's More",
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await onOwnTakes(page, CELLS[1], async () => {
			const trigger = takeMenuTriggers(page).nth(MIDDLE_TAKE_INDEX);
			await trigger.click();
			await expect(takeMenu(page)).toBeVisible();
			await page.keyboard.press('Escape');

			await expect(takeMenu(page)).toBeHidden();
			await expect(trigger).toBeFocused();
		});
	}
);

test(
	'915_C3 T28: with Now Playing docked, the menu stands on screen and every row takes the tap',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await onOwnTakes(page, CELLS[2], async () => {
			await page
				.locator('.take-row')
				.first()
				.getByRole('button', { name: nameStartingWith('Take') })
				.click();
			await expect(page.getByRole('complementary', { name: SONG_TITLE })).toBeVisible();

			await takeMenuTriggers(page).nth(2).click();
			const menu = takeMenu(page);
			await expect(menu).toBeVisible();

			await expectMenuInsideViewport(page, menu);
			for (const row of await menu.getByRole('button').all()) await row.click({ trial: true });
		});
	}
);
