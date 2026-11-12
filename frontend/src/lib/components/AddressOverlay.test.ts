import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AddressOverlay from './AddressOverlay.svelte';

type OverlayProps = Parameters<typeof AddressOverlay>[1];

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function mountOverlay(props: OverlayProps): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AddressOverlay, { target, props });
	await tick();
	return target;
}

describe('AddressOverlay', () => {
	it('shows only the loading message while an address resolves, and announces nothing', async () => {
		const target = await mountOverlay({ kind: 'loading', message: 'Loading thing...' });

		expect(target.textContent?.trim()).toBe('Loading thing...');
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(target.querySelector('a, button')).toBeNull();
	});

	it('announces an unknown address with its head, explanation and a link back', async () => {
		const target = await mountOverlay({
			kind: 'unknown',
			head: 'No such thing',
			explanation: 'The address names nothing.',
			backLabel: 'Back to start',
			backHref: '/start'
		});

		const alert = target.querySelector('[role="alert"]');
		expect(alert?.querySelector('h1')?.textContent).toBe('No such thing');
		expect(alert?.querySelector('p')?.textContent).toBe('The address names nothing.');
		const back = alert?.querySelector('a');
		expect(back?.textContent).toBe('Back to start');
		expect(back?.getAttribute('href')).toBe('/start');
		expect(alert?.querySelector('button')).toBeNull();
	});

	it('announces an unreachable address with its message and a retry button that calls its action', async () => {
		const onRetry = vi.fn();
		const target = await mountOverlay({
			kind: 'unreachable',
			message: 'The thing could not be loaded.',
			retryLabel: 'Try once more',
			onRetry
		});

		const alert = target.querySelector('[role="alert"]');
		expect(alert?.querySelector('p')?.textContent).toBe('The thing could not be loaded.');
		expect(alert?.querySelector('h1')).toBeNull();
		expect(alert?.querySelector('a')).toBeNull();
		const retry = alert?.querySelector('button');
		expect(retry?.textContent).toBe('Try once more');
		retry?.click();
		expect(onRetry).toHaveBeenCalledOnce();
	});
});
