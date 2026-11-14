import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationRetentionReport } from '#lib/api/client.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { lostNetwork } from '#lib/test-utils/network.ts';
import { addToast } from '#lib/stores/toast.ts';
import { words } from '#lib/words/en.ts';
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
		clickButton(target, words['takeRetention.delete']({ count: 2 }));

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith(words['takeRetention.runFailed'], 'error')
		);
	});
});

async function openConfirmation(target: HTMLElement): Promise<void> {
	clickButton(target, words['takeRetention.runNow']);
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
		expect(target.querySelector('h2')?.textContent).toBe(words['takeRetention.heading']);
		expect(target.querySelector('.auto')?.textContent).toContain(
			words['takeRetention.schedule']({ hour: '05' })
		);
		expect(buttonLabels(target)).toEqual([
			words['takeRetention.whatThisDoes'],
			words['takeRetention.refresh'],
			words['takeRetention.runNow']
		]);
	});

	it('draws the explanation button as an icon, not a letter', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(report());
		const target = await render();

		const info = target.querySelector('.info');
		expect(info?.querySelector('svg')).not.toBeNull();
		expect(info?.textContent?.trim()).toBe('');
	});

	it('asks with both numbers before it deletes anything, and Cancel runs nothing', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 12, deleted_count: 3 })
		);
		const target = await render();

		await openConfirmation(target);

		expect(runGenerationRetention).not.toHaveBeenCalled();
		expect(target.querySelector('.confirm p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			confirmSentence(12, 3)
		);
		expect(buttonLabels(target).slice(-2)).toEqual([
			words['takeRetention.cancel'],
			words['takeRetention.delete']({ count: 3 })
		]);

		clickButton(target, words['takeRetention.cancel']);
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
		clickButton(target, words['takeRetention.delete']({ count: 3 }));

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith(
				words['takeRetention.outcome']({ archived: '12', deleted: '3' }),
				'success'
			)
		);
	});

	it('counts a single take without a stray plural', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 1, deleted_count: 1 })
		);
		const target = await render();

		await openConfirmation(target);

		expect(target.querySelector('.confirm p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			confirmSentence(1, 1)
		);
	});

	it.each([
		{ days: 1, expected: '1 day' },
		{ days: 30, expected: '30 days' }
	])('reads a window of $days as "$expected"', async ({ days, expected }) => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(report({ retention_days: days }));
		const target = await render();

		expect(target.querySelector('.card .number')?.textContent).toBe(expected);
	});

	it('groups the thousands of a large count', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 1234, deleted_count: 0 })
		);
		const target = await render();

		expect(target.querySelectorAll('.card .number')[2]?.textContent).toBe('1,234');
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
		clickButton(target, words['takeRetention.delete']({ count: 3 }));

		await vi.waitFor(() => expect(target.textContent).toContain(words['takeRetention.nothingDue']));
		expect(addToast).toHaveBeenCalledWith(
			words['takeRetention.outcome']({ archived: '12', deleted: '3' }),
			'success'
		);
		expect(buttonLabels(target)).toEqual([words['takeRetention.whatThisDoes']]);
	});

	it('confirms with the counts that are current when Run now is pressed', async () => {
		vi.mocked(previewGenerationRetention)
			.mockResolvedValueOnce(report({ archived_count: 1, deleted_count: 2 }))
			.mockResolvedValue(report({ archived_count: 5, deleted_count: 9 }));
		const target = await render();

		await openConfirmation(target);

		expect(buttonLabels(target).slice(-2)).toEqual([
			words['takeRetention.cancel'],
			words['takeRetention.delete']({ count: 9 })
		]);
	});

	it('shows the empty state and no confirmation when the fresh preview has nothing due', async () => {
		vi.mocked(previewGenerationRetention)
			.mockResolvedValueOnce(report({ archived_count: 1, deleted_count: 2 }))
			.mockResolvedValue(report({ archived_count: 0, deleted_count: 0 }));
		const target = await render();

		clickButton(target, words['takeRetention.runNow']);

		await vi.waitFor(() => expect(target.textContent).toContain(words['takeRetention.nothingDue']));
		expect(target.querySelector('.confirm')).toBeNull();
	});

	it('says there is nothing to clean up and offers no buttons when nothing is due', async () => {
		vi.mocked(previewGenerationRetention).mockResolvedValue(
			report({ archived_count: 0, deleted_count: 0, archived_ids: [], deleted_ids: [] })
		);
		const target = await render();

		expect(target.textContent).toContain(words['takeRetention.nothingDue']);
		expect(buttonLabels(target)).toEqual([words['takeRetention.whatThisDoes']]);
	});
});

function buttonLabels(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('button')).map(
		(el) => el.getAttribute('aria-label') ?? el.textContent?.trim() ?? ''
	);
}

// The confirmation sentence read from its parts, as the person sees it.
function confirmSentence(archived: number, deleted: number): string {
	return words['takeRetention.confirm'](archived, { deleted: String(deleted) })
		.map((part) => (typeof part === 'string' ? part : part.text))
		.join('');
}
