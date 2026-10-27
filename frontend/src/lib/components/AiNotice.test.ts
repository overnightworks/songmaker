import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import AiNotice from './AiNotice.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(look: 'badge' | 'line'): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AiNotice, { target, props: { look } });
	await tick();
	const notice = target.querySelector<HTMLElement>('[data-testid="ai-notice"]');
	if (!notice) throw new Error('Expected the AI notice');
	return notice;
}

describe('AiNotice (#1906, Art. 50 AI Act)', () => {
	it.each([
		{ look: 'badge' as const, words: 'KI-generiert' },
		{ look: 'line' as const, words: 'Du schreibst mit einer KI' }
	])('the $look says exactly the ruled German words, marked as German', async ({ look, words }) => {
		const notice = await render(look);
		expect(notice.textContent?.trim()).toBe(words);
		expect(notice).toHaveAttribute('lang', 'de');
	});

	it.each(['badge', 'line'] as const)(
		'the %s hides its spark icon from a screen reader',
		async (look) => {
			const notice = await render(look);
			expect(notice.querySelector('[aria-hidden="true"] svg')).not.toBeNull();
		}
	);
});
