import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { toasts, addToast, dismissToast } from './toast';

beforeEach(() => {
	toasts.set([]);
	vi.useFakeTimers();
});

describe('toast store', () => {
	it('addToast creates a toast with correct fields', () => {
		addToast('test message', 'error');
		const all = get(toasts);
		expect(all).toHaveLength(1);
		expect(all[0].message).toBe('test message');
		expect(all[0].type).toBe('error');
		expect(typeof all[0].id).toBe('number');
	});

	it('addToast defaults to info type', () => {
		addToast('info message');
		expect(get(toasts)[0].type).toBe('info');
	});

	it('toasts auto-dismiss after 5 seconds', () => {
		addToast('temporary', 'success');
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(5000);
		expect(get(toasts)).toHaveLength(0);
	});

	it('dismissToast removes a specific toast', () => {
		addToast('first', 'info');
		addToast('second', 'error');
		const all = get(toasts);
		expect(all).toHaveLength(2);
		dismissToast(all[0].id);
		expect(get(toasts)).toHaveLength(1);
		expect(get(toasts)[0].message).toBe('second');
	});

	it('multiple toasts stack', () => {
		addToast('one', 'info');
		addToast('two', 'error');
		addToast('three', 'success');
		expect(get(toasts)).toHaveLength(3);
	});

	it('each toast gets a unique id', () => {
		addToast('a', 'info');
		addToast('b', 'info');
		const all = get(toasts);
		expect(all[0].id).not.toBe(all[1].id);
	});

	it('auto-dismiss only removes the specific toast', () => {
		addToast('early', 'info');
		vi.advanceTimersByTime(3000);
		addToast('late', 'info');
		vi.advanceTimersByTime(2000);
		const remaining = get(toasts);
		expect(remaining).toHaveLength(1);
		expect(remaining[0].message).toBe('late');
	});
});
