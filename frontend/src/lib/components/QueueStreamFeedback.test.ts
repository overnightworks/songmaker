import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { QueueStreamSkipItem } from '$lib/api/types';
import QueueStreamFeedback from './QueueStreamFeedback.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function render(props: {
	skipped?: QueueStreamSkipItem[];
	skippedComplete?: boolean;
	windowEnded?: boolean;
}) {
	const target = document.createElement('div');
	document.body.appendChild(target);
	mounted.push(mount(QueueStreamFeedback, { target, props }));
	return target;
}

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

describe('QueueStreamFeedback', () => {
	it('starts closed and groups skips with the terminal notice', async () => {
		const target = render({
			skippedComplete: false,
			windowEnded: true,
			skipped: [
				{ song_id: 's1', generation_id: 'g1', reason: 'missing_file' },
				{ song_id: 's2', generation_id: 'g2', reason: 'missing_file' },
				{ song_id: 's3', generation_id: 'g3', reason: 'unreadable_file' }
			]
		});
		await tick();

		const details = target.querySelector('details') as HTMLDetailsElement;
		expect(details.open).toBe(false);
		expect(details.querySelector('summary')?.textContent).toContain('3+');

		const summary = details.querySelector('summary') as HTMLElement;
		expect(summary.getAttribute('aria-label')).toBe(
			'3 Takes übersprungen, Prüfung unvollständig, Stream-Ende'
		);
		summary.focus();
		expect(document.activeElement).toBe(summary);
		summary.click();
		expect(details.open).toBe(true);
		expect(details.textContent).toContain('2 Datei nicht gefunden');
		expect(details.textContent).toContain('1 Datei nicht lesbar');
		expect(details.textContent).toContain('Weitere Takes nicht geprüft');
		expect(details.textContent).toContain('Weitere Takes nicht geladen');
	});
});
