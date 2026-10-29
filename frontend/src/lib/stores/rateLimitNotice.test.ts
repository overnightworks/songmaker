import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import { RATE_LIMITED_TOAST_MESSAGE } from '#lib/constants.ts';
import { notifyRateLimited } from '#lib/stores/rateLimitNotice.ts';
import { dismissToast, toasts } from '#lib/stores/toast.ts';

describe('the throttle notice', () => {
	function throttleToasts() {
		return get(toasts).filter((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
	}

	beforeEach(() => {
		toasts.set([]);
	});

	it.each(['/api/auth/me', '/api/albums/a1/cover-suggestions'])(
		'925_M3_N1: a 429 on %s raises no throttle toast, the surface shows its own',
		(path) => {
			notifyRateLimited(path);

			expect(get(toasts)).toHaveLength(0);
		}
	);

	it('925_M3_N2: a burst of 429s shows exactly one toast', () => {
		for (let refused = 0; refused < 5; refused++) notifyRateLimited('/api/songs');

		expect(throttleToasts()).toHaveLength(1);
	});

	it('925_M3_N2: a fresh toast follows once the earlier one is gone', () => {
		notifyRateLimited('/api/songs');
		const [first] = throttleToasts();
		dismissToast(first.id);

		notifyRateLimited('/api/songs');

		const shown = throttleToasts();
		expect(shown).toHaveLength(1);
		expect(shown[0].id).not.toBe(first.id);
	});
});
