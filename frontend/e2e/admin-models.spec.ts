// The admin Models tab, driven the way the admin drives it (issues #820, #846).
// It replaces `admin-routes.spec.ts`, which drove Fassung 1's per-provider route
// cards; Fassung 2 is one table with one row per task, so the flow it pinned no
// longer exists on the page.
//
// This is here rather than in the unit suite because what #820 rules is layout
// and reachability, and jsdom computes neither: whether the five columns still
// fit the card the table sits in (the operator found the Status column clipped
// away entirely at an ordinary desktop window -- the card is a few hundred
// pixels narrower than the viewport once the rail and a docked panel take their
// share, so no viewport media query can see it), whether 375px really becomes
// one card per task, and whether the page ever scrolls sideways.
//
// The stack behind it has no provider key and no mounted CLI (docker-compose.ci.yml
// drops both), so the "nothing is set up" half of the ruled sentences is the
// stack's own honest state rather than an arranged one: greyed route pills with
// their reason, "No models", an amber "Needs its API key", and a co-writer turn
// that ends with a named reason instead of silently switching provider.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';

import {
	ADMIN_TABS_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	MODELS_ADVANCED_LABEL,
	MODELS_COLUMN_MODEL_LABEL,
	MODELS_COLUMN_PROVIDER_LABEL,
	MODELS_COLUMN_ROUTE_LABEL,
	MODELS_COLUMN_STATUS_LABEL,
	MODELS_COLUMN_TASK_LABEL,
	MODELS_HISTORY_TAIL_LABEL,
	MODELS_NO_MODELS_LABEL,
	MODELS_ROUTE_KEY_NOT_SET_PHRASE,
	MODELS_ROUTE_NOT_LOGGED_IN_PHRASE,
	MODELS_SAVED_LABEL,
	MODELS_STATUS_NEEDS_API_KEY_LABEL,
	MODELS_TASK_COVER_LABEL,
	MODELS_TASK_COWRITER_LABEL,
	MODELS_TASK_SCORING_LABEL,
	PROVIDER_ROUTE_API_LABEL,
	PROVIDER_ROUTE_CLI_LABEL
} from '../src/lib/constants';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * What each test costs the API, measured on a green run against the CI recipe:
 * 11 for the table walked at four desktop widths, 24 for the Cover row's save,
 * reload and restore, 46 for the co-writer turn (a cold album open, the song,
 * the chat and the return to the tab), 9 for the phone cards. One ceiling for the file,
 * the same way `album-address.spec.ts` carries one for its four, with headroom
 * for the retry CI allows. The budget is a ceiling, not a knob: a flow that
 * suddenly needs several more round trips is a regression, so find the extra
 * requests instead of raising this number -- see
 * `LIBRARY_FLOW_API_REQUEST_BUDGET` in `helpers.ts` for the full reasoning.
 */
const MODELS_FLOW_API_REQUEST_BUDGET = 60;

// The desktop widths the operator actually works at, from a maximised screen
// down to the narrowest one that still shows the table rather than the cards.
const DESKTOP_WIDTHS = [1920, 1440, 1280, 1024] as const;
const PHONE_VIEWPORT = { width: 375, height: 844 };
const DESKTOP_HEIGHT = 900;

// The named failures a co-writer route can end a turn with
// (`cowriter/errors.py`). Which one this stack reports depends on how far the
// missing CLI gets before it fails; that it is one of them, and never a silent
// switch to another provider, is the ruled behaviour (#820, line 8).
const NAMED_TURN_FAILURES =
	/API key is not set\.|CLI is not signed in\.|CLI login was rejected or has expired\.|CLI is unavailable\.|Selected route failed\./;

async function openModelsTab(page: Page): Promise<void> {
	await page.goto('/settings/users');
	await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible();

	const compactTabs = page.getByRole('combobox', { name: ADMIN_TABS_LABEL, exact: true });
	if (await compactTabs.count()) {
		await compactTabs.selectOption('models');
	} else {
		await page.getByRole('button', { name: 'Models', exact: true }).click();
	}
}

function columnLabel(task: string, column: string): string {
	return `${task} ${column.toLowerCase()}`;
}

function providerSelect(page: Page, task: string): Locator {
	return page.getByRole('combobox', { name: columnLabel(task, MODELS_COLUMN_PROVIDER_LABEL) });
}

function routeSwitch(page: Page, task: string): Locator {
	return page.getByRole('group', { name: columnLabel(task, MODELS_COLUMN_ROUTE_LABEL) });
}

function modelSelect(page: Page, task: string): Locator {
	return page.getByRole('combobox', { name: columnLabel(task, MODELS_COLUMN_MODEL_LABEL) });
}

/**
 * A task's row and the table's header row. Both are grids of cells rather than
 * landmarks, so neither has an accessible name of its own to ask for -- two of
 * the four structural selectors this file uses. A row is narrowed by the task's own
 * labelled controls, so it can never match a neighbouring task.
 */
function taskRow(page: Page, task: string): Locator {
	return page.locator('.tt-row').filter({ has: providerSelect(page, task) });
}

function columnHeader(page: Page, column: string): Locator {
	return page.locator('.tt-head').getByText(column, { exact: true });
}

/**
 * A task's status. Every provider option carries its own state too ("Grok ·
 * needs its API key"), so the status has to be asked for as the status rather
 * than as its wording -- and the row's three ruled shapes (#820, line 6) are
 * exactly what that element's class says.
 */
function taskStatus(page: Page, task: string): Locator {
	return taskRow(page, task).locator('.st');
}

/**
 * The box a person reads for a select -- drawn beside the native control inside
 * the same field, rather than being it (#883), because a native select can only
 * show its selected option's own text and the provider's options carry their
 * state in that text. Both selects in a row are built this way, so both wear the
 * picture's one caret. Being decoration for the screen reader it has no role to
 * ask for, which makes it the fourth and last structural selector here.
 */
function fieldOf(select: Locator): Locator {
	return select.locator('xpath=..').locator('.pick-face');
}

/**
 * The field renders all of what it holds: nothing overflows its box, so nothing
 * is clipped or replaced by an ellipsis. This is the half of M3's defect that
 * applies to any field -- the model's included, which carries no state.
 */
async function expectFieldShownWhole(field: Locator): Promise<void> {
	await expect(field).toBeVisible();
	expect(await field.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
}

/**
 * Both halves of #820 line 5 in one measurement: the closed field reads as the
 * provider's bare name with nothing cut off it, while the option that field
 * stands for still carries that provider's state. This is the sentence M3 broke
 * -- "Claude · needs its API k" -- so it is asked at every width the operator
 * works at rather than once.
 */
async function expectProviderNameShownWhole(page: Page, task: string): Promise<void> {
	const field = fieldOf(providerSelect(page, task));
	await expectFieldShownWhole(field);

	const shown = ((await field.textContent()) ?? '').trim();
	const chosen = (
		(await providerSelect(page, task).locator('option:checked').textContent()) ?? ''
	).trim();
	expect(chosen.startsWith(shown)).toBe(true);
	expect(chosen.length).toBeGreaterThan(shown.length);
}

async function expectSaved(page: Page, task: string): Promise<void> {
	await expect(taskRow(page, task).getByText(MODELS_SAVED_LABEL)).toBeVisible();
}

async function expectNoSidewaysScroll(page: Page): Promise<void> {
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
}

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Models flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(MODELS_FLOW_API_REQUEST_BUDGET);
});

async function attachShot(
	page: Page,
	testInfo: TestInfo,
	name: string,
	fullPage = false
): Promise<void> {
	const path = testInfo.outputPath(`${name}.png`);
	await page.screenshot({ path, fullPage });
	await testInfo.attach(name, { path, contentType: 'image/png' });
}

test('the Models table keeps every task, route, model and status on screen at every desktop width', async ({
	page,
	isMobile
}, testInfo) => {
	test.skip(Boolean(isMobile), 'The phone shell shows cards; they have their own test below');

	await openModelsTab(page);

	// One row per task, and nothing else: the three tasks that ask the one
	// dispatch (#820, line 1).
	await expect(providerSelect(page, MODELS_TASK_COWRITER_LABEL)).toBeVisible();
	await expect(providerSelect(page, MODELS_TASK_COVER_LABEL)).toBeVisible();
	await expect(providerSelect(page, MODELS_TASK_SCORING_LABEL)).toBeVisible();
	await expect(page.locator('.tt-row')).toHaveCount(3);

	// Both routes stay offered in every row, and the one that is not set up
	// says why rather than disappearing (line 4).
	for (const task of [
		MODELS_TASK_COWRITER_LABEL,
		MODELS_TASK_COVER_LABEL,
		MODELS_TASK_SCORING_LABEL
	]) {
		const routes = routeSwitch(page, task);
		await expect(routes.getByRole('button', { name: PROVIDER_ROUTE_CLI_LABEL })).toBeVisible();
		await expect(routes.getByRole('button', { name: PROVIDER_ROUTE_API_LABEL })).toBeVisible();
	}
	await expect(routeSwitch(page, MODELS_TASK_COWRITER_LABEL)).toHaveAccessibleDescription(
		new RegExp(`${MODELS_ROUTE_NOT_LOGGED_IN_PHRASE}[\\s\\S]*${MODELS_ROUTE_KEY_NOT_SET_PHRASE}`)
	);

	// A model list nothing can fetch says so instead of inventing a value (line 7).
	const coverModel = modelSelect(page, MODELS_TASK_COVER_LABEL);
	await expect(coverModel).toHaveText(MODELS_NO_MODELS_LABEL);
	await expect(coverModel).toBeDisabled();

	// The row-level extra sits under a collapsed Advanced, in the Co-Writer row
	// alone (line 13).
	const advanced = page.getByText(MODELS_ADVANCED_LABEL, { exact: true });
	await expect(advanced).toHaveCount(1);
	await expect(page.getByText(MODELS_HISTORY_TAIL_LABEL)).toBeHidden();
	await advanced.click();
	await expect(page.getByText(MODELS_HISTORY_TAIL_LABEL)).toBeVisible();

	// The columns are the picture's five, and every one of them -- Status
	// included, the one the operator found clipped away -- stays on screen at
	// every width, without the page ever scrolling sideways.
	const scoringStatus = taskStatus(page, MODELS_TASK_SCORING_LABEL);
	await expect(scoringStatus).toContainText(MODELS_STATUS_NEEDS_API_KEY_LABEL);
	for (const width of DESKTOP_WIDTHS) {
		await page.setViewportSize({ width, height: DESKTOP_HEIGHT });
		for (const column of [
			MODELS_COLUMN_TASK_LABEL,
			MODELS_COLUMN_PROVIDER_LABEL,
			MODELS_COLUMN_ROUTE_LABEL,
			MODELS_COLUMN_MODEL_LABEL,
			MODELS_COLUMN_STATUS_LABEL
		]) {
			await expect(columnHeader(page, column)).toBeInViewport();
		}
		await expect(scoringStatus).toBeInViewport();
		for (const task of [
			MODELS_TASK_COWRITER_LABEL,
			MODELS_TASK_COVER_LABEL,
			MODELS_TASK_SCORING_LABEL
		]) {
			await expectProviderNameShownWhole(page, task);
			await expectFieldShownWhole(fieldOf(modelSelect(page, task)));
		}
		await expectNoSidewaysScroll(page);
		await attachShot(page, testInfo, `admin-models-${width}`);
	}
});

test('a task keeps the provider it was given, even one no route can run', async ({
	page,
	isMobile
}) => {
	test.skip(
		Boolean(isMobile),
		'Saving a row is shell-independent; the two shells share one budget'
	);

	await openModelsTab(page);

	// Cover is the row whose selection the server keeps whatever the routes can
	// do (#820, lines 2, 3 and 8), so this is where a real save can be driven
	// end to end against a stack where nothing is set up.
	const cover = providerSelect(page, MODELS_TASK_COVER_LABEL);
	const before = await cover.inputValue();
	const options = await cover
		.locator('option')
		.evaluateAll((nodes) => nodes.map((node) => (node as HTMLOptionElement).value));
	const chosen = options.indexOf(before);
	const neighbour = chosen + 1 < options.length ? chosen + 1 : chosen - 1;
	expect(options[neighbour], 'the Cover row offers more than one provider').toBeTruthy();

	try {
		// Chosen from the keyboard, because the box a person reads is drawn beside
		// the native select rather than being it (#883): only a select that still
		// takes focus and still answers the arrow keys can be driven this way.
		await cover.focus();
		await page.keyboard.press(neighbour > chosen ? 'ArrowDown' : 'ArrowUp');
		await expect(cover).toHaveValue(options[neighbour]);
		await expectSaved(page, MODELS_TASK_COVER_LABEL);

		await openModelsTab(page);
		await expect(providerSelect(page, MODELS_TASK_COVER_LABEL)).toHaveValue(options[neighbour]);
	} finally {
		// The selection is instance-wide and outlives the test, so it is put back
		// through the same control: `album-cover.spec.ts` runs against this stack
		// afterwards and asks the provider left here to draw.
		await providerSelect(page, MODELS_TASK_COVER_LABEL).selectOption(before);
		await expectSaved(page, MODELS_TASK_COVER_LABEL);
	}
});

test('a route that is not set up ends the next co-writer turn with its reason', async ({
	page,
	isMobile
}) => {
	test.skip(
		Boolean(isMobile),
		'The compact shell opens the same chat in a sheet; the turn is the same'
	);

	const library = readSeededLibrary();
	const surface = workspace(page);

	await openModelsTab(page);
	const chosenProvider = await providerSelect(page, MODELS_TASK_COWRITER_LABEL).inputValue();

	await page.goto(`/album/${library.albumId}`);
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await surface.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();

	const ask = surface.getByPlaceholder('Ask the co-writer... (@song, @album, or @v1)');
	await ask.fill('Write me a second verse.');
	await surface.getByRole('button', { name: 'Send', exact: true }).click();

	// The turn ends with the reason the chosen route failed for -- never with a
	// quiet switch to a provider that would have worked (#820, line 8).
	const failure = surface.getByRole('alert');
	await expect(failure).toBeVisible();
	await expect(failure).toContainText(NAMED_TURN_FAILURES);

	await openModelsTab(page);
	await expect(providerSelect(page, MODELS_TASK_COWRITER_LABEL)).toHaveValue(chosenProvider);
});

test('at 375px every task is a card with its own labelled lines', async ({
	page,
	isMobile
}, testInfo) => {
	test.skip(!isMobile, 'The desktop shell shows the table; it has its own test above');

	await page.setViewportSize(PHONE_VIEWPORT);
	await openModelsTab(page);

	// The table's one header row gives way to a label on every line of every
	// card, so each value still says what it is (#820, line 12).
	await expect(columnHeader(page, MODELS_COLUMN_TASK_LABEL)).toBeHidden();
	for (const task of [
		MODELS_TASK_COWRITER_LABEL,
		MODELS_TASK_COVER_LABEL,
		MODELS_TASK_SCORING_LABEL
	]) {
		const card = taskRow(page, task);
		for (const column of [
			MODELS_COLUMN_PROVIDER_LABEL,
			MODELS_COLUMN_ROUTE_LABEL,
			MODELS_COLUMN_MODEL_LABEL,
			MODELS_COLUMN_STATUS_LABEL
		]) {
			await expect(card.getByText(column, { exact: true })).toBeVisible();
		}
	}
	// The cards stack, so the last task's status is reached by scrolling down --
	// never by scrolling sideways.
	const scoringStatus = taskStatus(page, MODELS_TASK_SCORING_LABEL);
	await expect(scoringStatus).toContainText(MODELS_STATUS_NEEDS_API_KEY_LABEL);
	await scoringStatus.scrollIntoViewIfNeeded();
	await expect(scoringStatus).toBeInViewport();

	// The narrowest provider column there is, and the name still stands in it
	// whole (#820, line 5; #883).
	for (const task of [
		MODELS_TASK_COWRITER_LABEL,
		MODELS_TASK_COVER_LABEL,
		MODELS_TASK_SCORING_LABEL
	]) {
		await expectProviderNameShownWhole(page, task);
		await expectFieldShownWhole(fieldOf(modelSelect(page, task)));
	}

	await expectNoSidewaysScroll(page);
	await attachShot(page, testInfo, 'admin-models-375', true);
});
