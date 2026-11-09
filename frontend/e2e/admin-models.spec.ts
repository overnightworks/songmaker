// The admin Models tab, driven the way the admin drives it (issues #820, #846, #2055).
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
// Both rows are read-only: each agent file names its model and the gateway runs
// it (#2055 C1). The stack behind it
// configures a gateway it cannot reach, so a co-writer turn ends with a named
// problem instead of silently switching provider.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';

import { ADMIN_TABS_LABEL } from '../src/lib/constants/admin';
import { COWRITER_COMPOSER_PLACEHOLDER, COWRITER_SEND_LABEL } from '../src/lib/constants/cowriter';
import { EDITOR_VIEW_COWRITER_LABEL, songEditorOpenLabel } from '../src/lib/constants/song';
import {
	MODELS_ADVANCED_LABEL,
	MODELS_COLUMN_MODEL_LABEL,
	MODELS_COLUMN_PROVIDER_LABEL,
	MODELS_COLUMN_ROUTE_LABEL,
	MODELS_COLUMN_STATUS_LABEL,
	MODELS_COLUMN_TASK_LABEL,
	MODELS_HISTORY_TAIL_LABEL,
	MODELS_ROUTE_GATEWAY_LABEL,
	MODELS_SET_BY_AGENT_FILE_LABEL,
	MODELS_TASK_COVER_LABEL,
	MODELS_TASK_COWRITER_LABEL
} from '../src/lib/constants/models';
import { FlowGuard, ONLY_IN_SHELL, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * What each test costs the API, measured on a green run against the CI recipe:
 * 8 for the table walked at four desktop widths, 32 for the co-writer turn (a
 * cold album open, the song, the chat and the return to the tab) and 6 for the
 * phone cards.
 * One ceiling for the file, the same way `album-address.spec.ts` carries one
 * for its four: the ceiling of the largest test plus headroom for the retry CI
 * allows. The budget is a ceiling, not a knob: a flow that
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

// The named problems a co-writer turn ends with when the agent did not run it. This stack
// sets a gateway it cannot reach, so a real turn ends with a named problem. That it is a
// named problem, and never a silent switch to a local provider, is the ruled behaviour
// (#820, line 8; #1476).
const NAMED_TURN_FAILURES =
	/The co-writer is unavailable|The co-writer is busy|The co-writer is not enabled for your account|Log in again to use the co-writer/;

// Every row of the Models table: words, no control, no model and no status (#1949, #2055):
// the agent file names the model, so the row says so.
const SERVICE_ROW_WORDS = [MODELS_SET_BY_AGENT_FILE_LABEL, MODELS_ROUTE_GATEWAY_LABEL];
const TASKS = [MODELS_TASK_COWRITER_LABEL, MODELS_TASK_COVER_LABEL];

async function openModelsTab(page: Page): Promise<void> {
	await page.goto('/settings/users');
	await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible();

	const compactTabs = page.getByRole('combobox', { name: ADMIN_TABS_LABEL, exact: true });
	if (await compactTabs.count()) {
		await compactTabs.selectOption('models');
	} else {
		await page.getByRole('button', { name: 'Models', exact: true }).click();
	}
	await expect(page.getByRole('heading', { name: 'Models', exact: true })).toBeVisible();
}

/**
 * A task's row and the table's header row. Both are grids of cells rather than
 * landmarks, so neither has an accessible name of its own to ask for -- the two
 * structural selectors this file uses. A row is narrowed by its task cell, so it
 * can never match a neighbouring task.
 */
function taskRow(page: Page, task: string): Locator {
	return page
		.locator('.tt-row')
		.filter({ has: page.locator('.cell-task').getByText(task, { exact: true }) });
}

async function expectRowsReadOnly(page: Page): Promise<void> {
	await expect(page.locator('.tt-row')).toHaveCount(TASKS.length);
	for (const task of TASKS) {
		const row = taskRow(page, task);
		for (const word of SERVICE_ROW_WORDS) {
			await expect(row).toContainText(word);
		}
		await expect(row).not.toContainText(/opus|Claude|Codex|Ready|offer/);
		await expect(row.getByRole('combobox')).toHaveCount(0);
		await expect(row.getByRole('button')).toHaveCount(0);
		await expect(row.getByRole('link')).toHaveCount(0);
	}
}

function columnHeader(page: Page, column: string): Locator {
	return page.locator('.tt-head').getByText(column, { exact: true });
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
	subject: Page | Locator,
	testInfo: TestInfo,
	name: string,
	fullPage = false
): Promise<void> {
	const path = testInfo.outputPath(`${name}.png`);
	await subject.screenshot({ path, fullPage });
	await testInfo.attach(name, { path, contentType: 'image/png' });
}

// The phone shell shows cards; they have their own test below.
test(
	'the Models table shows both rows read-only and keeps every column on screen at every desktop width',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }, testInfo) => {
		await openModelsTab(page);

		// One row per task, and nothing else; each only reads, because its agent
		// file names the model and the gateway runs it (#1476, #2055).
		await expectRowsReadOnly(page);

		// The row-level extra sits under a collapsed Advanced, in the Co-Writer row
		// alone (line 13).
		const advanced = page.getByText(MODELS_ADVANCED_LABEL, { exact: true });
		await expect(advanced).toHaveCount(1);
		await expect(page.getByText(MODELS_HISTORY_TAIL_LABEL)).toBeHidden();
		await advanced.click();
		await expect(page.getByText(MODELS_HISTORY_TAIL_LABEL)).toBeVisible();

		// The columns are the picture's five, and every one of them stays on
		// screen at every width, without the page ever scrolling sideways.
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
			await expect(taskRow(page, MODELS_TASK_COVER_LABEL)).toBeInViewport();
			await expectNoSidewaysScroll(page);
			await attachShot(page, testInfo, `admin-models-${width}`);
		}
	}
);

// The compact shell opens the same chat in a sheet; the turn is the same.
test(
	'a co-writer turn that cannot run ends with a named problem and leaves the row alone',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const library = readSeededLibrary();
		const surface = workspace(page);

		await page.goto(`/album/${library.albumId}`);
		await surface
			.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle) })
			.click();
		await surface.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();

		const ask = surface.getByPlaceholder(COWRITER_COMPOSER_PLACEHOLDER);
		await ask.fill('Write me a second verse.');
		await surface.getByRole('button', { name: COWRITER_SEND_LABEL, exact: true }).click();

		// The turn ends with the problem the service could not run it for -- never
		// with a quiet switch to a provider that would have worked (#820, line 8; #1069).
		const failure = surface.getByRole('alert');
		await expect(failure).toBeVisible();
		await expect(failure).toContainText(NAMED_TURN_FAILURES);

		await openModelsTab(page);
		await expectRowsReadOnly(page);
	}
);

// The desktop shell shows the table; it has its own test above.
test(
	'at 375px every task is a card with its own labelled lines',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }, testInfo) => {
		await page.setViewportSize(PHONE_VIEWPORT);
		await openModelsTab(page);

		// The table's one header row gives way to a label on every line of every
		// card, so each value still says what it is (#820, line 12). No card has
		// a Status line: nothing is checked for a row the agent file decides (#1949).
		await expect(columnHeader(page, MODELS_COLUMN_TASK_LABEL)).toBeHidden();
		await expectRowsReadOnly(page);
		for (const task of TASKS) {
			const card = taskRow(page, task);
			for (const column of [
				MODELS_COLUMN_PROVIDER_LABEL,
				MODELS_COLUMN_ROUTE_LABEL,
				MODELS_COLUMN_MODEL_LABEL
			]) {
				await expect(card.getByText(column, { exact: true })).toBeVisible();
			}
			await expect(card.getByText(MODELS_COLUMN_STATUS_LABEL, { exact: true })).toHaveCount(0);
		}
		// The cards stack, so the last task is reached by scrolling down --
		// never by scrolling sideways.
		const cover = taskRow(page, MODELS_TASK_COVER_LABEL);
		await cover.scrollIntoViewIfNeeded();
		await expect(cover).toBeInViewport();

		await expectNoSidewaysScroll(page);
		await attachShot(page, testInfo, 'admin-models-375', true);
	}
);
