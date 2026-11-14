import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NetworkError } from '#lib/api/fetch.ts';
import type { ReleaseInfo } from '#lib/api/types.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants/connectivity.ts';
import { APP_NAME, APP_REPOSITORY_URL } from '#lib/constants/app.ts';
import { words } from '#lib/words/en.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';

const LABELS = {
	app: words['aboutPage.app'],
	version: words['aboutPage.version'],
	released: words['aboutPage.released'],
	commit: words['aboutPage.commit'],
	whatsNew: words['aboutPage.whatsNew'],
	licence: words['aboutPage.licence']
};

const mocks = vi.hoisted(() => ({ fetchRelease: vi.fn() }));

vi.mock('#lib/api/settings.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/settings.ts')>();
	return { ...actual, fetchRelease: (...args: unknown[]) => mocks.fetchRelease(...args) };
});

import AboutPage from './+page.svelte';

const COMMIT = '15d8557508fe726d732335875a524b6a817e4621';
const TAG = 'v2026.10.28.4';

let mounted: ReturnType<typeof mount> | undefined;

async function renderAboutPage(release: ReleaseInfo): Promise<HTMLElement> {
	mocks.fetchRelease.mockResolvedValue(release);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AboutPage, { target });
	await vi.waitFor(() => expect(target.querySelector('.about-list')).not.toBeNull());
	return target;
}

function rows(target: HTMLElement): Record<string, { value: string; href: string | null }> {
	return Object.fromEntries(
		Array.from(target.querySelectorAll('.about-row')).map((row) => [
			row.querySelector('.about-label')?.textContent?.trim() ?? '',
			{
				value: row.querySelector('.about-value')?.textContent?.trim() ?? '',
				href: row.getAttribute('href')
			}
		])
	);
}

function opensInNewTab(target: HTMLElement): boolean {
	return Array.from(target.querySelectorAll('a.about-row')).every(
		(link) => link.getAttribute('target') === '_blank' && link.getAttribute('rel') === 'noopener'
	);
}

beforeEach(() => {
	mocks.fetchRelease.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
});

describe('about page', () => {
	it('names the release, its day, its commit and where to read more', async () => {
		const target = await renderAboutPage({ tag: TAG, commit: COMMIT });

		expect(rows(target)).toEqual({
			[LABELS.app]: { value: APP_NAME, href: null },
			[LABELS.version]: { value: TAG, href: null },
			[LABELS.released]: { value: '28 Oct 2026', href: null },
			[LABELS.commit]: {
				value: COMMIT.slice(0, 8),
				href: `${APP_REPOSITORY_URL}/commit/${COMMIT}`
			},
			[LABELS.whatsNew]: { value: '', href: `${APP_REPOSITORY_URL}/releases/tag/${TAG}` },
			[LABELS.licence]: { value: 'MIT', href: `${APP_REPOSITORY_URL}/blob/main/LICENSE` }
		});
		expect(opensInNewTab(target)).toBe(true);
		expect(target.querySelector('h1')?.textContent).toBe(words['settingsSections.about']);
	});

	it('says there is no release for a build without a tag and still links its commit', async () => {
		const target = await renderAboutPage({ tag: 'unreleased', commit: COMMIT });

		const shown = rows(target);
		expect(Object.keys(shown)).toEqual([LABELS.app, LABELS.version, LABELS.commit, LABELS.licence]);
		expect(shown[LABELS.version].value).toBe(words['aboutPage.noRelease']);
		expect(shown[LABELS.commit].href).toBe(`${APP_REPOSITORY_URL}/commit/${COMMIT}`);
	});

	it('shows an unknown commit as plain text when there is no release either', async () => {
		const target = await renderAboutPage({ tag: 'unreleased', commit: 'unknown' });

		const shown = rows(target);
		expect(shown[LABELS.version].value).toBe(words['aboutPage.noRelease']);
		expect(shown[LABELS.commit]).toEqual({ value: words['aboutPage.unknown'], href: null });
	});

	it('keeps the release rows of a tag whose commit is unknown', async () => {
		const target = await renderAboutPage({ tag: TAG, commit: 'unknown' });

		const shown = rows(target);
		expect(Object.keys(shown)).toEqual([
			LABELS.app,
			LABELS.version,
			LABELS.released,
			LABELS.commit,
			LABELS.whatsNew,
			LABELS.licence
		]);
		expect(shown[LABELS.commit]).toEqual({ value: words['aboutPage.unknown'], href: null });
	});

	it('shows no day for a tag that names none, and invents none', async () => {
		const target = await renderAboutPage({ tag: 'v1.2.3', commit: COMMIT });

		const shown = rows(target);
		expect(shown[LABELS.version].value).toBe('v1.2.3');
		expect(shown).not.toHaveProperty(LABELS.released);
		expect(shown[LABELS.whatsNew].href).toBe(`${APP_REPOSITORY_URL}/releases/tag/v1.2.3`);
	});

	it('names the failed read, then shows the rows once the connection is back', async () => {
		vi.useFakeTimers();
		mocks.fetchRelease.mockRejectedValue(
			new NetworkError('/api/release', new TypeError('Failed to fetch'))
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(AboutPage, { target });
		await tick();
		for (const delay of UNREACHABLE_RELOAD_DELAYS_MS) await vi.advanceTimersByTimeAsync(delay);

		expect(target.querySelector('.error')?.textContent).toBe(words['aboutPage.loadFailed']);
		expect(target.querySelector('.about-list')).toBeNull();

		mocks.fetchRelease.mockResolvedValue({ tag: TAG, commit: COMMIT });
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		await vi.waitFor(() => expect(target.querySelector('.about-list')).not.toBeNull());

		expect(target.querySelector('.error')).toBeNull();
		expect(rows(target)[LABELS.version].value).toBe(TAG);
	});
});
