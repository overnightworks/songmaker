import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationRetentionReport } from '$lib/api/client';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/api/client', () => ({
	previewGenerationRetention: vi.fn(),
	runGenerationRetention: vi.fn()
}));

import { previewGenerationRetention } from '$lib/api/client';
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
});

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
