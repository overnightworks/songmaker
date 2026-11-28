import { makeGeneration as generation } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { GenerationItem } from '#lib/api/types.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import { words } from '#lib/words/en.ts';
import NowPlayingScores from './NowPlayingScores.svelte';

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	activeJobs.set([]);
});

async function showScores(take: GenerationItem, look: 'footer' | 'chips' = 'footer') {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlayingScores, { target, props: { generation: take, look } });
	await tick();
}

function entryTexts(): string[] {
	return Array.from(target.querySelectorAll('.entry')).map(
		(entry) => entry.textContent?.replace(/\s+/g, ' ').trim() ?? ''
	);
}

describe('NowPlayingScores', () => {
	it.each(['footer', 'chips'] as const)(
		'lists the automatic scores in the %s look, with no Rating and no control',
		async (look) => {
			await showScores(
				generation({
					id: 'g1',
					scores: {
						user_rating: 82,
						text_accuracy: 91,
						dynamics: 74,
						bpm_detected: 92.4
					}
				}),
				look
			);

			expect(entryTexts()).toEqual([
				`${words['nowPlayingScores.lyricsSung']} 91%`,
				`${words['nowPlayingScores.dynamics']} 74`,
				`${words['nowPlayingScores.bpm']} 92`
			]);
			expect(target.textContent).not.toContain('82');
			expect(target.querySelector('button, a, input')).toBeNull();
		}
	);

	it('names the footer by its heading and the chips by none', async () => {
		const take = generation({ id: 'g1', scores: { dynamics: 74 } });

		await showScores(take, 'footer');
		expect(target.querySelector('.heading')?.textContent).toBe(words['nowPlayingScores.heading']);
		await unmount(mounted as ReturnType<typeof mount>);
		target.remove();

		await showScores(take, 'chips');
		expect(target.querySelector('.heading')).toBeNull();
	});

	it('says there are no scores yet for a take nobody scored', async () => {
		await showScores(generation({ id: 'g1', scores: null }));

		expect(target.textContent).toContain(words['nowPlayingScores.empty']);
	});

	it('shows the pending word while the take re-scores', async () => {
		activeJobs.set([
			{
				job: {
					id: 'j1',
					type: 'score',
					status: 'running',
					progress: 0.2,
					error: null,
					error_type: null,
					started_at: null,
					completed_at: null
				},
				songId: 's1',
				genId: 'g1'
			}
		]);

		await showScores(generation({ id: 'g1', scores: { dynamics: 74 } }));

		expect(target.querySelector('[role="status"]')?.textContent).toBe(
			words['nowPlayingScores.rescoring']
		);
	});
});
