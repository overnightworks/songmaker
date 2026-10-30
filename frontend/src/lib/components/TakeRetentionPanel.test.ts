import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationRetentionReport } from '#lib/api/client.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { lostNetwork } from '#lib/test-utils/network.ts';
import { addToast } from '#lib/stores/toast.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';

vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn() }));
vi.mock('#lib/api/client.ts', () => ({
	previewGenerationRetention: vi.fn(),
	runGenerationRetention: vi.fn()
}));

import { previewGenerationRetention, runGenerationRetention } from '#lib/api/client.ts';
import Panel from './TakeRetentionPanel.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function report(overrides: Partial<GenerationRetentionReport> = {}): GenerationRetentionReport {
	return {
		archived_ids: ['g1'],
		deleted_ids: ['g2', 'g3'],
		archived_count: 1,
		deleted_count: 2,
		retention_days: 30,
		hard_delete_days: 14,
		scheduled_hour_utc: 3,
		dry_run: true,
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Panel, { target });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
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
		expect(target.querySelector('.cards')).toBeNull();

		vi.mocked(previewGenerationRetention).mockResolvedValue(report());
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelector('.cards')).not.toBeNull());
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
		await openConfirmation(target);
		clickButton(target, 'Delete 2');

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Cleanup failed', 'error'));
	});
});

async function openConfirmation(target: HTMLElement): Promise<void> {
	clickButton(target, 'Run now');
	await vi.waitFor(() => expect(target.querySelector('.confirm')).not.toBeNull());
}

function clickButton(target: HTMLElement, label: string): void {
	Array.from(target.querySelectorAll<HTMLButtonElement>('button'))
		.find((el) => el.textContent?.trim() === label)
		?.click();
}

describe('generation retention panel', () => {
	it('names what it archives and deletes as takes and shows the real automatic schedule', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(report({ scheduled_hour_utc: 5 }));
		const target = await render();

		expect(target.textContent).not.toMatch(/generation/i);
		expect(target.querySelector('h2')?.textContent).toBe('Take Retention');
		expect(target.querySelector('.auto')?.textContent).toContain('daily 05:00 UTC');
		expect(buttonLabels(target)).toEqual(['What this does', 'Refresh', 'Run now']);
	});

	it('asks with both numbers before it deletes anything, and Cancel runs nothing', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 12, deleted_count: 3 })
		);
		const target = await render();

		await openConfirmation(target);

		expect(runGenerationRetention).not.toHaveBeenCalled();
		expect(target.querySelector('.confirm p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'Archive 12 takes and permanently delete 3. Deleting cannot be undone.'
		);
		expect(buttonLabels(target).slice(-2)).toEqual(['Cancel', 'Delete 3']);

		clickButton(target, 'Cancel');
		await tick();
		expect(target.querySelector('.confirm')).toBeNull();
		expect(runGenerationRetention).not.toHaveBeenCalled();
	});

	it('runs the cleanup only on the red Delete button and reports the outcome', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 12, deleted_count: 3 })
		);
		vi.mocked(runGenerationRetention).mockResolvedValue(
			report({ archived_count: 12, deleted_count: 3, dry_run: false })
		);
		const target = await render();

		await openConfirmation(target);
		clickButton(target, 'Delete 3');

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith('Archived 12, deleted 3', 'success')
		);
	});

	it('counts a single take without a stray plural', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 1, deleted_count: 1 })
		);
		const target = await render();

		await openConfirmation(target);

		expect(target.querySelector('.confirm p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'Archive 1 take and permanently delete 1. Deleting cannot be undone.'
		);
	});

	it('shows what is due after a run, not what the run just did', async () => {
		vi.mocked(previewGenerationRetention)
			.mockResolvedValueOnce(report({ archived_count: 12, deleted_count: 3 }))
			.mockResolvedValueOnce(report({ archived_count: 12, deleted_count: 3 }))
			.mockResolvedValue(report({ archived_count: 0, deleted_count: 0 }));
		vi.mocked(runGenerationRetention).mockResolvedValue(
			report({ archived_count: 12, deleted_count: 3, dry_run: false })
		);
		const target = await render();

		await openConfirmation(target);
		clickButton(target, 'Delete 3');

		await vi.waitFor(() => expect(target.textContent).toContain('Nothing to clean up right now'));
		expect(addToast).toHaveBeenCalledWith('Archived 12, deleted 3', 'success');
		expect(buttonLabels(target)).toEqual(['What this does']);
	});

	it('confirms with the counts that are current when Run now is pressed', async () => {
		vi.mocked(previewGenerationRetention)
			.mockResolvedValueOnce(report({ archived_count: 1, deleted_count: 2 }))
			.mockResolvedValue(report({ archived_count: 5, deleted_count: 9 }));
		const target = await render();

		await openConfirmation(target);

		expect(buttonLabels(target).slice(-2)).toEqual(['Cancel', 'Delete 9']);
	});

	it('shows the empty state and no confirmation when the fresh preview has nothing due', async () => {
		vi.mocked(previewGenerationRetention)
			.mockResolvedValueOnce(report({ archived_count: 1, deleted_count: 2 }))
			.mockResolvedValue(report({ archived_count: 0, deleted_count: 0 }));
		const target = await render();

		clickButton(target, 'Run now');

		await vi.waitFor(() => expect(target.textContent).toContain('Nothing to clean up right now'));
		expect(target.querySelector('.confirm')).toBeNull();
	});

	it('says there is nothing to clean up and offers no buttons when nothing is due', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 0, deleted_count: 0, archived_ids: [], deleted_ids: [] })
		);
		const target = await render();

		expect(target.textContent).toContain('Nothing to clean up right now');
		expect(buttonLabels(target)).toEqual(['What this does']);
	});
});

function buttonLabels(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('button')).map(
		(el) => el.getAttribute('aria-label') ?? el.textContent?.trim() ?? ''
	);
}
