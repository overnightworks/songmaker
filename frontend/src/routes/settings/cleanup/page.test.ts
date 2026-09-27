import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationRetentionReport } from '$lib/api/client';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork } from '$lib/test-utils/network';
import { addToast } from '$lib/stores/toast';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/api/client', () => ({
	previewGenerationRetention: vi.fn(),
	runGenerationRetention: vi.fn()
}));

import { previewGenerationRetention, runGenerationRetention } from '$lib/api/client';
import { currentUser } from '$lib/stores/auth';
import Page from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function report(overrides: Partial<GenerationRetentionReport> = {}): GenerationRetentionReport {
	return {
		archived_ids: ['g1'],
		deleted_ids: ['g2', 'g3'],
		archived_count: 1,
		deleted_count: 2,
		retention_days: 30,
		hard_delete_days: 14,
		dry_run: true,
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Page, { target });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

beforeEach(() => {
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin' });
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	currentUser.set(null);
	vi.mocked(previewGenerationRetention).mockReset();
	vi.mocked(runGenerationRetention).mockReset();
	vi.mocked(addToast).mockReset();
	resetConnectivityForTests();
});

describe('generation retention failures', () => {
	it('offline, shows no failure of its own and the preview comes back once online', async () => {
		reportResourceStreamReachable(false);
		vi.mocked(previewGenerationRetention).mockRejectedValueOnce(lostNetwork());
		const target = await render();
		expect(addToast).not.toHaveBeenCalled();
		expect(target.querySelector('.counts')).toBeNull();

		vi.mocked(previewGenerationRetention).mockResolvedValue(report());
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelector('.counts')).not.toBeNull());
		expect(addToast).not.toHaveBeenCalled();
	});

	it('names a preview the server refused in its own words', async () => {
		vi.mocked(previewGenerationRetention).mockRejectedValueOnce(
			new ApiError(503, 'Retention is paused', '/api/admin/retention')
		);
		await render();

		expect(addToast).toHaveBeenCalledWith('Retention is paused', 'error');
	});

	it('names a cleanup run the network swallowed without browser text', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(report());
		vi.mocked(runGenerationRetention).mockRejectedValueOnce(lostNetwork());
		const target = await render();
		clickButton(target, 'Run cleanup now');
		await tick();
		clickButton(target, 'Confirm cleanup');

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Cleanup failed', 'error'));
	});
});

function clickButton(target: HTMLElement, label: string): void {
	Array.from(target.querySelectorAll<HTMLButtonElement>('button'))
		.find((el) => el.textContent?.trim() === label)
		?.click();
}

describe('generation retention settings', () => {
	it('names what it archives and deletes as takes, the word the rest of the app uses', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(report());
		const target = await render();

		expect(target.textContent).not.toMatch(/generation/i);
		expect(target.querySelector('h1')?.textContent).toBe('Take Retention');
		expect(target.textContent).toContain('Takes that are neither');

		const summaries = Array.from(target.querySelectorAll('summary')).map((el) =>
			el.textContent?.trim()
		);
		expect(summaries).toEqual(['2 take ids to hard-delete', '1 take ids to archive']);
	});

	it('counts a single take in the confirmation without a stray plural', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 1, deleted_count: 1, archived_ids: ['g1'], deleted_ids: ['g2'] })
		);
		const target = await render();

		const runNow = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(el) => el.textContent?.trim() === 'Run cleanup now'
		);
		runNow?.click();
		await tick();

		const confirm = target.querySelector('.confirm p')?.textContent?.replace(/\s+/g, ' ').trim();
		expect(confirm).toContain('Archive 1 take and permanently delete 1 archived one?');
	});
});
