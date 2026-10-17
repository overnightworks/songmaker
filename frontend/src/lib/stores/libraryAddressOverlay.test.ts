import { afterEach, describe, expect, it } from 'vitest';
import { inertWhileAddressOverlay, libraryAddressOverlayActive } from './libraryAddressOverlay';

afterEach(() => {
	libraryAddressOverlayActive.set(false);
});

describe('inertWhileAddressOverlay', () => {
	it('defect:#1531: makes the element inert exactly while an address overlay is up, until detached', () => {
		const element = document.createElement('div');
		libraryAddressOverlayActive.set(true);

		const detach = inertWhileAddressOverlay(element);
		expect(element.hasAttribute('inert')).toBe(true);

		libraryAddressOverlayActive.set(false);
		expect(element.hasAttribute('inert')).toBe(false);

		libraryAddressOverlayActive.set(true);
		expect(element.hasAttribute('inert')).toBe(true);

		detach();
		libraryAddressOverlayActive.set(false);
		expect(element.hasAttribute('inert')).toBe(true);
	});
});
