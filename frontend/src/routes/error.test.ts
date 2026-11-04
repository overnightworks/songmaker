import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { browserReportsOnline } from '#lib/test-utils/network.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';

const { goto, page } = vi.hoisted(() => ({
	goto: vi.fn(),
	page: {} as { status: number; error: { message: string } | null; url: URL }
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/state', () => ({ page }));

import ErrorPage from './+error.svelte';

const OFFLINE_SENTENCE =
	'This page needs the network. It opens by itself when you are back online.';
const ADDRESS = 'http://localhost/settings/references';

let mounted: ReturnType<typeof mount> | undefined;

function failNavigationWith(status: number, message: string): void {
	Object.assign(page, { status, error: { message }, url: new URL(ADDRESS) });
}

async function mountErrorPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ErrorPage, { target });
	await tick();
	return target;
}

beforeEach(() => {
	goto.mockReset();
	goto.mockResolvedValue(undefined);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.restoreAllMocks();
});

describe('route error page', () => {
	it('tells an offline failed load that the page opens by itself, without a status code', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');

		const target = await mountErrorPage();

		expect(target.textContent).toContain(OFFLINE_SENTENCE);
		expect(target.textContent).not.toContain('500');
		expect(target.textContent).not.toContain('Internal Error');
	});

	it('opens the same address once when the network returns', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');
		await mountErrorPage();

		browserReportsOnline(true);
		await tick();

		expect(goto).toHaveBeenCalledTimes(1);
		expect(goto).toHaveBeenCalledWith(ADDRESS, { replace: true, refreshAll: true });
	});

	it('keeps the offline state, not the status, while the retry is still loading', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');
		const target = await mountErrorPage();
		goto.mockReturnValue(new Promise(() => {}));

		browserReportsOnline(true);
		await tick();

		expect(target.textContent).not.toContain('500');
		expect(target.textContent).not.toContain('Internal Error');
	});

	it('shows the plain status once a retry fails while the browser is online', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');
		const target = await mountErrorPage();
		let failRetry: () => void = () => {};
		goto.mockReturnValue(new Promise<void>((resolve) => (failRetry = resolve)));

		browserReportsOnline(true);
		await tick();
		failRetry();
		await vi.waitFor(() => expect(target.textContent).toContain('500'));

		expect(target.textContent).not.toContain(OFFLINE_SENTENCE);
	});

	it('keeps the offline state while only an earlier, superseded retry has finished', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');
		const target = await mountErrorPage();
		const finishers: Array<() => void> = [];
		goto.mockImplementation(() => new Promise<void>((resolve) => finishers.push(resolve)));

		browserReportsOnline(true);
		await tick();
		browserReportsOnline(false);
		await tick();
		browserReportsOnline(true);
		await tick();
		finishers[0]();
		await new Promise((resolve) => setTimeout(resolve));
		await tick();

		expect(goto).toHaveBeenCalledTimes(2);
		expect(target.textContent).toContain(OFFLINE_SENTENCE);
		expect(target.textContent).not.toContain('500');
	});

	it('shows the status and message of a failure while online', async () => {
		failNavigationWith(500, 'Internal Error');

		const target = await mountErrorPage();

		expect(target.textContent).toContain('500');
		expect(target.textContent).toContain('Internal Error');
		expect(target.textContent).not.toContain(OFFLINE_SENTENCE);
	});

	it('shows a 404 even while offline and never retries it', async () => {
		browserReportsOnline(false);
		failNavigationWith(404, 'Not Found');

		const target = await mountErrorPage();
		browserReportsOnline(true);
		await tick();

		expect(target.textContent).toContain('404');
		expect(target.textContent).toContain('Not Found');
		expect(goto).not.toHaveBeenCalled();
	});

	it('stops waiting for the network once it is closed', async () => {
		browserReportsOnline(false);
		failNavigationWith(500, 'Internal Error');
		await mountErrorPage();

		await unmount(mounted as ReturnType<typeof mount>);
		mounted = undefined;
		browserReportsOnline(true);
		await tick();

		expect(goto).not.toHaveBeenCalled();
	});
});
