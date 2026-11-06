import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceUsesResponse } from '#lib/api/types.ts';

const mocks = vi.hoisted(() => ({ getReferenceUses: vi.fn() }));

vi.mock('#lib/api/references.ts', () => ({
	getReferenceUses: (...args: unknown[]) => mocks.getReferenceUses(...args)
}));

import { takeUse, versionUse } from '#lib/test-utils/references.ts';
import ReferenceUses from './ReferenceUses.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

async function renderUses(answer: Promise<ReferenceUsesResponse>): Promise<HTMLElement> {
	mocks.getReferenceUses.mockReturnValue(answer);
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(ReferenceUses, { target, props: { id: 'uses-1', referenceId: 'reference-1' } })
	);
	await tick();
	return target;
}

function rowsOf(target: HTMLElement): { text: string; href: string | null }[] {
	return Array.from(target.querySelectorAll('.uses-row')).map((row) => ({
		text: row.textContent?.replace(/\s+/g, ' ').trim() ?? '',
		href: row.getAttribute('href')
	}));
}

afterEach(async () => {
	await Promise.all(mounted.splice(0).map((component) => unmount(component)));
	document.body.replaceChildren();
	mocks.getReferenceUses.mockReset();
});

describe('ReferenceUses', () => {
	it('says it is loading until the read answers', async () => {
		const target = await renderUses(new Promise(() => {}));

		expect(target.textContent).toContain('Loading');
	});

	it('names the failure when the read fails', async () => {
		const target = await renderUses(Promise.reject(new Error('boom')));

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toBe(
				"Couldn't load where it is used"
			)
		);
	});

	it('groups takes and versions under their song and links each to its address', async () => {
		const target = await renderUses(
			Promise.resolve({
				takes: [
					takeUse({ generation_number: 11, version_number: 6, audio_duration_sec: 193 }),
					takeUse({ generation_number: 2, version_number: null, audio_duration_sec: null }),
					takeUse({
						song_id: 'song-2',
						song_title: 'Other',
						song_slug: 'other',
						generation_number: 1
					})
				],
				versions: [versionUse({ version_number: 3 })]
			})
		);

		await vi.waitFor(() => expect(target.querySelectorAll('.uses-song')).toHaveLength(2));

		expect(
			Array.from(target.querySelectorAll('.uses-song-title')).map((h) => h.textContent?.trim())
		).toEqual(['Storytime', 'Other']);
		expect(rowsOf(target)).toEqual([
			{ text: 'Take 11 · v6 · 3:13', href: '/album/album-1/storytime/take/11' },
			{ text: 'Take 2', href: '/album/album-1/storytime/take/2' },
			{ text: 'Version v3', href: '/album/album-1/storytime' },
			{ text: 'Take 1 · v6 · 3:13', href: '/album/album-1/other/take/1' }
		]);
		expect(target.textContent).toContain('It stays while a take or version uses it.');
	});

	it('tags an archived take and keeps it linked', async () => {
		const target = await renderUses(
			Promise.resolve({ takes: [takeUse({ is_archived: true })], versions: [] })
		);

		await vi.waitFor(() => expect(rowsOf(target)).toHaveLength(1));

		expect(rowsOf(target)[0].text).toContain('Archived');
		expect(rowsOf(target)[0].href).not.toBeNull();
	});

	it('tags a deleted song and shows its rows as plain text', async () => {
		const target = await renderUses(
			Promise.resolve({
				takes: [takeUse({ is_trashed: true, is_archived: true })],
				versions: [versionUse({ is_trashed: true })]
			})
		);

		await vi.waitFor(() => expect(rowsOf(target)).toHaveLength(2));

		expect(target.querySelector('.uses-song-title')?.textContent).toContain('Deleted');
		expect(rowsOf(target).map((row) => row.href)).toEqual([null, null]);
		expect(target.querySelector('a')).toBeNull();
	});
});
