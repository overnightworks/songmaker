import { describe, expect, it } from 'vitest';
import { isRedirect } from '@sveltejs/kit';

import { load } from './+page';

describe('/loras redirect', () => {
	it('redirects to /settings/voices', () => {
		expect.assertions(3);
		try {
			load();
		} catch (err) {
			expect(isRedirect(err)).toBe(true);
			if (isRedirect(err)) {
				expect(err.status).toBe(308);
				expect(err.location).toBe('/settings/voices');
			}
		}
	});
});
