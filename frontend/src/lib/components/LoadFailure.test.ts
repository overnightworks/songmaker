import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LoadFailure from './LoadFailure.svelte';

const MESSAGE = 'Could not load the shelf';
const RETRY_LABEL = 'Once more';

let shown: ReturnType<typeof mount> | null = null;

afterEach(async () => {
	if (shown) await unmount(shown);
	shown = null;
	document.body.replaceChildren();
});

function showFailure(onretry: () => void): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	shown = mount(LoadFailure, {
		target,
		props: { message: MESSAGE, retryLabel: RETRY_LABEL, onretry }
	});
	return target;
}

describe('the load-failure card', () => {
	it('announces what failed as an alert', () => {
		const alert = showFailure(() => undefined).querySelector('[role="alert"]');

		expect(alert?.textContent).toContain(MESSAGE);
	});

	it('offers a retry button named by its caller that asks to retry once per press', async () => {
		const onretry = vi.fn();
		const target = showFailure(onretry);

		target.querySelector<HTMLButtonElement>(`button[aria-label="${RETRY_LABEL}"]`)?.click();
		await tick();

		expect(onretry).toHaveBeenCalledOnce();
	});
});
