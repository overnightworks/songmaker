import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CoverRunElapsed from './CoverRunElapsed.svelte';

const NOW = new Date('2026-10-22T12:00:00Z');

function secondsBeforeNow(seconds: number): string {
	return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe('CoverRunElapsed', () => {
	let target: HTMLElement;
	let component: ReturnType<typeof mount> | null = null;

	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(NOW);
		target = document.createElement('div');
		document.body.append(target);
	});

	afterEach(() => {
		if (component) unmount(component);
		component = null;
		target.remove();
		vi.useRealTimers();
	});

	function show(startedAt: string) {
		component = mount(CoverRunElapsed, { target, props: { startedAt } });
		flushSync();
	}

	it('shows the time since the server started the run and ticks every second', () => {
		show(secondsBeforeNow(42));
		expect(target.textContent).toBe('0:42');

		vi.advanceTimersByTime(3000);
		flushSync();
		expect(target.textContent).toBe('0:45');
	});

	it('shows 0:00 when the client clock is behind the server', () => {
		show(secondsBeforeNow(-30));
		expect(target.textContent).toBe('0:00');
	});

	it('keeps the ticking time out of the announced text', () => {
		show(secondsBeforeNow(5));
		expect(target.querySelector('[aria-hidden="true"]')?.textContent).toBe('0:05');
	});
});
