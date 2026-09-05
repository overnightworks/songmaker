// The take strip's kinetic scrolling (issue #358): jsdom cannot compute
// layout, so the unit suite can only pin what's honestly checkable there —
// the axis-selection contract and the momentum/friction math against faked
// timers. Whether a drag actually moves the strip, whether momentum coasts
// past the release point, whether a click that catches a still-rolling strip
// stays silent, and which axis a real container query puts the strip on can
// only be shown here, against a real render.
//
// The strip renders in Write on the compact shell too. Its phone proof below
// verifies the same action survives at 375px and that a second take list is
// not reintroduced there.

import { expect, test, type Page } from '@playwright/test';
import { EDITOR_VIEW_COWRITER_LABEL, TRANSPORT_PAUSE_LABEL } from '../src/lib/constants';
import { nowPlayingTakeLabel } from '../src/lib/constants/now-playing';
import { DESKTOP_VIEWPORT, FlowGuard, MOBILE_VIEWPORT } from './helpers';
import { readSeededLibrary, seedTakeStripSong } from './seed';

/** Its dedicated album keeps this flow from mutating the shared base library. */
const KINETIC_STRIP_SONG_TITLE = 'Kinetic Strip Takes';

/**
 * Takes seeded for that song — enough for the strip to genuinely overflow its
 * container in both the row and the column layout. Measured directly against
 * the real render, not assumed: the column layout's own container only turns
 * out to be height-bounded once its content exceeds it (~503px at
 * DESKTOP_VIEWPORT, ~35.5px per chip — under about 14 chips it simply grows
 * to fit everything, since the fix below is what makes it stop doing that),
 * and the row layout's own container is ~591px wide at ROW_LAYOUT_VIEWPORT
 * against ~72.7px per chip. 25 total takes overflows both with headroom.
 */
const TAKE_COUNT = 25;

/**
 * A container width below the `@container editor (min-width: 680px)` switch
 * in WriteColumn.svelte, but still well above the app's own 768px compact
 * breakpoint — measured directly against the real container query (not
 * assumed): 900px keeps the shell on its desktop layout while the editor
 * region it hosts renders under 680px, so the strip renders as a row. Kept
 * as its own narrower context rather than the desktop project's own 1440px
 * viewport, which renders the column layout instead (also measured).
 */
const ROW_LAYOUT_VIEWPORT = { width: 900, height: 900 };

/**
 * What this spec costs the API per test, measured over several green runs
 * against a clean stack (the song's own takes are seeded directly against
 * the database — see seedTakeStripSong — so none of that setup counts here):
 * a cold song open, the co-writer toggle, and playing two takes costs 24-28
 * requests for the column and row tests; the mobile-absence check costs 15
 * and never comes close. One shared ceiling with headroom — a flow that
 * suddenly needs more round trips is a regression, find the extra requests
 * instead of raising the number.
 */
const KINETIC_STRIP_FLOW_API_REQUEST_BUDGET = 35;

function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.beforeAll(async ({}, testInfo) => {
	// beforeAll runs once per Playwright project, not once per file — every
	// test below skips on mobile (each opens its own desktop-shaped context
	// regardless of project), so seeding the song there would cost a second
	// one for nothing.
	if (testInfo.project.name === 'mobile') return;
	const library = readSeededLibrary();
	await seedTakeStripSong(library.kineticStripAlbumId, KINETIC_STRIP_SONG_TITLE, TAKE_COUNT);
});

/** Chip labels in the strip's real DOM order: newest take first (TakeStrip.svelte's sort). */
function takeLabelsNewestFirst(): string[] {
	return Array.from({ length: TAKE_COUNT }, (_, i) => nowPlayingTakeLabel(null, TAKE_COUNT - i));
}

async function openKineticStripSongCoWriter(page: Page): Promise<void> {
	const library = readSeededLibrary();
	const songAddress = `/album/${library.kineticStripAlbumId}/${expectedSongSlug(KINETIC_STRIP_SONG_TITLE)}`;
	await page.goto(songAddress);
	await expect(page.getByRole('heading', { name: KINETIC_STRIP_SONG_TITLE })).toBeVisible();
	await page.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL }).click();
	const strip = page.locator('.take-strip');
	await strip.waitFor();
	// At the row layout's narrower width the strip sits below a lot of other
	// content in the single stacked column, well past the fold — a real user
	// scrolls the page to reach it, and a raw page.mouse coordinate this test
	// computes from its bounding box needs it to already be on screen.
	await strip.scrollIntoViewIfNeeded();
}

/** The strip's own scroll position — a structural selector, like `.settings-sidebar`
 *  elsewhere in this suite (README): `.take-strip` carries no accessible role of its
 *  own to select by. */
function stripScroll(page: Page): Promise<{ left: number; top: number; flexDirection: string }> {
	return page.locator('.take-strip').evaluate((el: HTMLElement) => ({
		left: el.scrollLeft,
		top: el.scrollTop,
		flexDirection: getComputedStyle(el).flexDirection
	}));
}

/**
 * Home/End and the arrow keys each reveal their target with a native smooth
 * `scrollIntoView` — a real key press or two, not a burst, so waits for that
 * animation to actually finish (two unchanged reads in a row) before the next
 * key, rather than a fixed sleep racing an animation of unknown duration.
 */
async function waitForStripScrollSettled(page: Page): Promise<void> {
	await page.waitForFunction(
		() => {
			const el = document.querySelector('.take-strip') as
				(HTMLElement & { __lastScrollCheck?: string }) | null;
			if (!el) return false;
			const value = `${el.scrollLeft},${el.scrollTop}`;
			const settled = el.__lastScrollCheck === value;
			el.__lastScrollCheck = value;
			return settled;
		},
		{ timeout: 2000, polling: 60 }
	);
}

/** Waits for the strip's scroll position on `axis` to differ from `from` —
 *  the first observable sign that something is still moving it after a
 *  release, rather than an assumed elapsed time. */
async function waitForScrollChangeFrom(
	page: Page,
	axis: 'left' | 'top',
	from: number
): Promise<void> {
	await page.waitForFunction(
		({ axis, from }) => {
			const el = document.querySelector('.take-strip') as HTMLElement | null;
			if (!el) return false;
			const value = axis === 'left' ? el.scrollLeft : el.scrollTop;
			return value !== from;
		},
		{ axis, from },
		{ timeout: 2000, polling: 30 }
	);
}

/** The strip's average per-chip span on `axis`, measured from its own
 *  rendered content rather than a guessed pixel constant. */
async function measureChipSpan(page: Page, axis: 'left' | 'top'): Promise<number> {
	const size = await page
		.locator('.take-strip')
		.evaluate((el, axis) => (axis === 'left' ? el.scrollWidth : el.scrollHeight), axis);
	return size / TAKE_COUNT;
}

/**
 * Waits until the strip has moved more than `thresholdPx` past
 * `atReleaseValue` — the direct proof of momentum, not an inference drawn
 * afterwards. `stopMomentum(true)` always ends a drag or a catch by
 * snapping to the *nearest* item's centre (kineticScroll.ts), whether real
 * momentum ran or the flick was too gentle to coast at all, so a bare "it
 * moved after release" cannot tell the two apart — a snap-only settle
 * moves it too. A snap targets the nearest item, so it can move at most
 * half the span between two items; passing a full chip span (`thresholdPx`
 * here) cannot be explained by snapping alone, only by momentum having
 * carried it there. Waiting for the crossing itself (rather than waiting
 * for any movement, then separately measuring the eventual settle) also
 * keeps this from being satisfied by the stop click's own catch-and-snap
 * that follows it — the threshold is crossed before that click ever fires.
 */
async function waitForCoastPastThreshold(
	page: Page,
	axis: 'left' | 'top',
	atReleaseValue: number,
	thresholdPx: number
): Promise<void> {
	await page.waitForFunction(
		({ axis, atReleaseValue, thresholdPx }) => {
			const el = document.querySelector('.take-strip') as HTMLElement | null;
			if (!el) return false;
			const value = axis === 'left' ? el.scrollLeft : el.scrollTop;
			return Math.abs(value - atReleaseValue) > thresholdPx;
		},
		{ axis, atReleaseValue, thresholdPx },
		{ timeout: 2000, polling: 20 }
	);
}

/**
 * Captures whether the *next* wheel event dispatched anywhere on the page
 * was default-prevented — direct proof of whether the action intercepted
 * it, rather than inferring that from whether the strip moved (native
 * scrolling and a JS handler emulating it would both move it). The
 * listener sits on `document` in the bubble phase, so it observes the
 * event after kineticScroll's own listener — registered directly on
 * `.take-strip`, deeper in the tree — has already had its chance to call
 * `preventDefault()`.
 */
async function captureNextWheelDefaultPrevented(page: Page): Promise<() => Promise<boolean>> {
	await page.evaluate(() => {
		delete document.documentElement.dataset.lastWheelDefaultPrevented;
		document.addEventListener(
			'wheel',
			(e) => {
				document.documentElement.dataset.lastWheelDefaultPrevented = String(e.defaultPrevented);
			},
			{ once: true }
		);
	});
	return async () => {
		const value = await page.evaluate(
			() => document.documentElement.dataset.lastWheelDefaultPrevented
		);
		if (value === undefined) throw new Error('No wheel event observed on the page');
		return value === 'true';
	};
}

async function expectNothingPlaying(page: Page): Promise<void> {
	await expect(
		page.getByRole('contentinfo').getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).not.toBeVisible();
}

test.describe('kinetic take strip', () => {
	let guard: FlowGuard;

	test.beforeEach(({ page }) => {
		guard = new FlowGuard(page);
	});

	// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
	test.afterEach(({}, testInfo) => {
		console.log(`Kinetic-strip flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(KINETIC_STRIP_FLOW_API_REQUEST_BUDGET);
	});

	test('drags, coasts and stops on click without opening the take it lands on, in the column layout the strip renders in at desktop width', async ({
		browser,
		isMobile
	}) => {
		test.skip(Boolean(isMobile), 'this test opens its own desktop-width context');
		// No storageState/baseURL passed here: the `browser` fixture Playwright
		// Test injects already carries the project's own `use` config (see
		// playwright.config.ts) as newContext()'s defaults, so the login
		// session and the relative page.goto() below both still resolve —
		// checked directly against this stack, not assumed, after an
		// independent review raised exactly this question.
		const context = await browser.newContext({ viewport: DESKTOP_VIEWPORT });
		const page = await context.newPage();
		guard = new FlowGuard(page);
		const labels = takeLabelsNewestFirst();

		await openKineticStripSongCoWriter(page);
		const before = await stripScroll(page);
		expect(before.flexDirection).toBe('column'); // the axis this test actually proves against

		const box = await page.locator('.take-strip').boundingBox();
		if (!box) throw new Error('take strip did not render a box');
		const cx = box.x + box.width / 2;
		// A moderate span (20% of the box, not edge-to-edge) rather than a
		// maximal drag — measured directly: an edge-to-edge drag here already
		// covers most of the container's own scrollable range on its own
		// (box height 502.5px against a max scroll of 377.5px at 25 takes),
		// leaving momentum almost no room to coast before hitting the
		// boundary and snapping immediately, which is indistinguishable from
		// no momentum at all.
		const startY = box.y + box.height * 0.65;
		const endY = box.y + box.height * 0.45;

		await expectNothingPlaying(page);
		await page.mouse.move(cx, startY);
		await page.mouse.down();
		const dragSteps = 6;
		for (let i = 1; i <= dragSteps; i++) {
			await page.mouse.move(cx, startY + ((endY - startY) * i) / dragSteps);
		}
		await page.mouse.up();

		const atRelease = await stripScroll(page);
		expect(atRelease.top).toBeGreaterThan(before.top); // the drag itself moved it

		// Momentum, proven before the stop click below ever fires — see
		// waitForCoastPastThreshold's own note on why a full chip span cannot
		// be explained by the eventual snap-to-nearest alone.
		const chipSpan = await measureChipSpan(page, 'top');
		await waitForCoastPastThreshold(page, 'top', atRelease.top, chipSpan);

		// The stop click: fired the instant real momentum is confirmed, not
		// after an assumed duration — a flick this strong takes the better
		// part of a second to decay (its capped release velocity and the
		// friction constant in kineticScroll.ts fix that), comfortably longer
		// than the reaction time between that confirmation and the click
		// below. It lands on whatever chip is currently under the pointer
		// while the strip is still rolling and must not open it.
		await page.mouse.click(cx, box.y + box.height / 2);
		await expectNothingPlaying(page);

		// A plain click elsewhere still opens a take normally — the strip isn't
		// just inert.
		await page.getByRole('button', { name: labels[labels.length - 1], exact: true }).click();
		await expect(page.getByRole('contentinfo').getByText(labels[labels.length - 1])).toBeVisible();
		await expect(
			page
				.getByRole('contentinfo')
				.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
		).toBeVisible();

		// The wheel: a plain vertical tick already scrolls a column natively.
		// Proven directly against the dispatched event, not inferred from
		// whether the strip moved — a JS handler emulating native scrolling
		// would move it too, so movement alone cannot show the browser handled
		// it unassisted (issue #358's own review). Movement is still checked
		// afterwards, as confirmation that the browser's own scroll actually
		// ran and nothing else on the page swallowed it — a negative delta
		// (scroll back toward the start) rather than a positive one, since the
		// take clicked just above scrolled the strip to its far end, where a
		// further forward tick would have nowhere left to move it.
		const beforeWheel = await stripScroll(page);
		const readWheelDefaultPrevented = await captureNextWheelDefaultPrevented(page);
		await page.mouse.move(cx, box.y + box.height / 2);
		await page.mouse.wheel(0, -150);
		expect(await readWheelDefaultPrevented()).toBe(false);
		await waitForScrollChangeFrom(page, 'top', beforeWheel.top);

		// Home/End and the vertical arrow keys.
		const firstChip = page.getByRole('button', { name: labels[0], exact: true });
		const lastChip = page.getByRole('button', { name: labels[labels.length - 1], exact: true });
		await firstChip.focus();
		await page.keyboard.press('End');
		await waitForStripScrollSettled(page);
		await expect(lastChip).toBeFocused();
		await page.keyboard.press('Home');
		await waitForStripScrollSettled(page);
		await expect(firstChip).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await waitForStripScrollSettled(page);
		await expect(page.getByRole('button', { name: labels[1], exact: true })).toBeFocused();
		await page.keyboard.press('ArrowUp');
		await waitForStripScrollSettled(page);
		await expect(firstChip).toBeFocused();

		await context.close();
	});

	test('drags, coasts and stops on click without opening the take it lands on, in the row layout the strip renders in when its container narrows below the desktop floor', async ({
		browser,
		isMobile
	}) => {
		test.skip(Boolean(isMobile), 'this test opens its own narrow desktop-width context'); // NOSONAR S1607: the test creates its own desktop context.
		const context = await browser.newContext({ viewport: ROW_LAYOUT_VIEWPORT });
		const page = await context.newPage();
		guard = new FlowGuard(page);
		const labels = takeLabelsNewestFirst();

		await openKineticStripSongCoWriter(page);
		const before = await stripScroll(page);
		expect(before.flexDirection).toBe('row'); // the axis this test actually proves against

		const box = await page.locator('.take-strip').boundingBox();
		if (!box) throw new Error('take strip did not render a box');
		const cy = box.y + box.height / 2;
		// A moderate span, not edge-to-edge — see the column test's own note
		// on why a maximal drag leaves momentum no room to coast.
		const startX = box.x + box.width * 0.65;
		const endX = box.x + box.width * 0.45;

		await expectNothingPlaying(page);
		await page.mouse.move(startX, cy);
		await page.mouse.down();
		const dragSteps = 6;
		for (let i = 1; i <= dragSteps; i++) {
			await page.mouse.move(startX + ((endX - startX) * i) / dragSteps, cy);
		}
		await page.mouse.up();

		const atRelease = await stripScroll(page);
		expect(atRelease.left).toBeGreaterThan(before.left); // the drag itself moved it

		// Momentum, proven before the stop click below ever fires (see the
		// column test's own note on waitForCoastPastThreshold).
		const chipSpan = await measureChipSpan(page, 'left');
		await waitForCoastPastThreshold(page, 'left', atRelease.left, chipSpan);

		// The stop click (see the column test's own note on timing): fired the
		// instant real momentum is confirmed, it lands on whatever chip is
		// currently under the pointer while the strip is still rolling and
		// must not open it.
		await page.mouse.click(box.x + box.width / 2, cy);
		await expectNothingPlaying(page);

		await page.getByRole('button', { name: labels[labels.length - 1], exact: true }).click();
		await expect(page.getByRole('contentinfo').getByText(labels[labels.length - 1])).toBeVisible();
		await expect(
			page
				.getByRole('contentinfo')
				.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
		).toBeVisible();

		// The wheel: a row's own axis is horizontal, so a plain vertical tick
		// (deltaX 0) has to be converted rather than left to a browser that
		// would otherwise do nothing useful with it on this axis. Proven
		// directly against the dispatched event (see the column test's own
		// note); movement is still checked afterwards, as confirmation that
		// the action's own conversion actually ran — a negative delta (see
		// the column test's own note on why: the take clicked just above
		// scrolled the strip to its far end).
		const beforeWheel = await stripScroll(page);
		const readWheelDefaultPrevented = await captureNextWheelDefaultPrevented(page);
		await page.mouse.move(box.x + box.width / 2, cy);
		await page.mouse.wheel(0, -150);
		expect(await readWheelDefaultPrevented()).toBe(true);
		await waitForScrollChangeFrom(page, 'left', beforeWheel.left);

		// Home/End and the horizontal arrow keys.
		const firstChip = page.getByRole('button', { name: labels[0], exact: true });
		const lastChip = page.getByRole('button', { name: labels[labels.length - 1], exact: true });
		await firstChip.focus();
		await page.keyboard.press('End');
		await waitForStripScrollSettled(page);
		await expect(lastChip).toBeFocused();
		await page.keyboard.press('Home');
		await waitForStripScrollSettled(page);
		await expect(firstChip).toBeFocused();
		await page.keyboard.press('ArrowRight');
		await waitForStripScrollSettled(page);
		await expect(page.getByRole('button', { name: labels[1], exact: true })).toBeFocused();
		await page.keyboard.press('ArrowLeft');
		await waitForStripScrollSettled(page);
		await expect(firstChip).toBeFocused();

		await context.close();
	});

	test('the strip renders in Write on the compact shell at phone width, without a second takes list', async ({
		browser,
		isMobile
	}) => {
		// prettier-ignore
		test.skip( // NOSONAR S1607: own mobile-emulated context.
			Boolean(isMobile),
			'this test opens its own mobile-emulated context regardless of project'
		);
		const context = await browser.newContext({
			viewport: MOBILE_VIEWPORT,
			isMobile: true,
			hasTouch: true
		});
		const page = await context.newPage();
		guard = new FlowGuard(page);
		const library = readSeededLibrary();

		await page.goto(`/album/${library.albumId}/${expectedSongSlug(library.pickedSongTitle)}`);
		await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();

		const strip = page.locator('.take-strip');
		await expect(strip).toBeVisible();
		await expect(page.locator('.takes-list')).toHaveCount(0);
		await expect(page.getByRole('tab', { name: /Takes/ })).toHaveCount(0);
		await strip.getByRole('button', { name: library.takeLabel, exact: true }).click();
		await expect(page.getByRole('contentinfo').getByText(library.takeLabel)).toBeVisible();

		await context.close();
	});
});
