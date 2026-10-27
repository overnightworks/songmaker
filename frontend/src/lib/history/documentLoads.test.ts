import { afterEach, describe, expect, it, vi } from 'vitest';

import { browserDocumentLoads } from './documentLoads';

describe('browserDocumentLoads.submitPost', () => {
	afterEach(() => {
		vi.restoreAllMocks();
		document.body.replaceChildren();
	});

	it('submits one form with method post, the resolved action and no fields', () => {
		// jsdom implements no navigation, so the submission itself is only observed.
		const submitted: HTMLFormElement[] = [];
		vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function (
			this: HTMLFormElement
		) {
			submitted.push(this);
		});

		browserDocumentLoads.submitPost('/auth/logout');

		expect(submitted).toHaveLength(1);
		expect(submitted[0].method).toBe('post');
		expect(submitted[0].action).toBe(`${window.location.origin}/auth/logout`);
		expect(submitted[0].elements).toHaveLength(0);
	});
});
