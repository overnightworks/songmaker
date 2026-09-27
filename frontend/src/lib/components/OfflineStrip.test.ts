import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OFFLINE_STRIP_MESSAGE } from '$lib/constants';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { browserReportsOnline } from '$lib/test-utils/network';
import OfflineStrip from './OfflineStrip.svelte';

let component: ReturnType<typeof mount>;
let target: HTMLDivElement;

function liveRegion(): HTMLElement | null {
	return target.querySelector('[role="status"]');
}

beforeEach(() => {
	target = document.createElement('div');
	document.body.append(target);
	component = mount(OfflineStrip, { target });
});

afterEach(async () => {
	await unmount(component);
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.restoreAllMocks();
});

describe('OfflineStrip', () => {
	it('says nothing while the page reaches the server', () => {
		expect(liveRegion()?.textContent?.trim()).toBe('');
	});

	it('says once, calmly and without a button, that the page is offline and retrying', async () => {
		browserReportsOnline(false);
		await tick();

		expect(liveRegion()).toHaveAttribute('aria-live', 'polite');
		expect(liveRegion()?.textContent?.trim()).toBe(OFFLINE_STRIP_MESSAGE);
		expect(target.querySelector('button')).toBeNull();
	});

	it('wears the cloud glyph beside its sentence', async () => {
		browserReportsOnline(false);
		await tick();

		expect(liveRegion()?.querySelector('svg path')).not.toBeNull();
	});

	it('says the same when the browser is online but the live stream cannot reach the server', async () => {
		reportResourceStreamReachable(false);
		await tick();

		expect(liveRegion()?.textContent?.trim()).toBe(OFFLINE_STRIP_MESSAGE);
	});

	it('goes by itself once back online, with no message of its own', async () => {
		browserReportsOnline(false);
		await tick();

		browserReportsOnline(true);
		await tick();

		expect(liveRegion()?.textContent?.trim()).toBe('');
	});
});
