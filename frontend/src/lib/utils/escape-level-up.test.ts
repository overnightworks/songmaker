import { describe, expect, it } from 'vitest';
import {
	escapeLevelUpTarget,
	hasOpenOverlay,
	isEditableElement,
	shouldHandleGlobalEscape
} from './escape-level-up';

describe('escapeLevelUpTarget', () => {
	it('leaves the docked Now Playing panel before any navigation level', () => {
		expect(escapeLevelUpTarget(true, true, true)).toBe('now-playing');
	});

	it('goes from a song to its collection', () => {
		expect(escapeLevelUpTarget(false, true, true)).toBe('collection');
	});

	it('goes from a collection to the wall', () => {
		expect(escapeLevelUpTarget(false, false, true)).toBe('wall');
	});

	it('does nothing at the wall', () => {
		expect(escapeLevelUpTarget(false, false, false)).toBeNull();
	});
});

describe('isEditableElement', () => {
	it('treats an input as editable', () => {
		expect(isEditableElement(document.createElement('input'))).toBe(true);
	});

	it('treats a textarea as editable', () => {
		expect(isEditableElement(document.createElement('textarea'))).toBe(true);
	});

	it('treats contenteditable as editable', () => {
		const div = document.createElement('div');
		div.contentEditable = 'true';
		document.body.append(div);
		expect(isEditableElement(div)).toBe(true);
		div.remove();
	});

	it('treats a plain button as not editable', () => {
		expect(isEditableElement(document.createElement('button'))).toBe(false);
	});
});

describe('hasOpenOverlay', () => {
	it('finds an aria-modal dialog', () => {
		const dialog = document.createElement('div');
		dialog.setAttribute('aria-modal', 'true');
		document.body.append(dialog);
		expect(hasOpenOverlay(document)).toBe(true);
		dialog.remove();
	});

	it('finds a data-escape-overlay popover whose role does not permit aria-modal', () => {
		const menu = document.createElement('div');
		menu.setAttribute('role', 'menu');
		menu.setAttribute('data-escape-overlay', 'true');
		document.body.append(menu);
		expect(hasOpenOverlay(document)).toBe(true);
		menu.remove();
	});

	it('reports no overlay when none is mounted', () => {
		expect(hasOpenOverlay(document)).toBe(false);
	});
});

describe('shouldHandleGlobalEscape', () => {
	it('handles Escape with no overlay and no editable focus', () => {
		expect(
			shouldHandleGlobalEscape(
				{ key: 'Escape', target: document.body, defaultPrevented: false },
				document
			)
		).toBe(true);
	});

	it('ignores keys other than Escape', () => {
		expect(
			shouldHandleGlobalEscape(
				{ key: 'Enter', target: document.body, defaultPrevented: false },
				document
			)
		).toBe(false);
	});

	it('yields while typing in a textarea', () => {
		const textarea = document.createElement('textarea');
		expect(
			shouldHandleGlobalEscape(
				{ key: 'Escape', target: textarea, defaultPrevented: false },
				document
			)
		).toBe(false);
	});

	it('yields while a dialog is open', () => {
		const dialog = document.createElement('div');
		dialog.setAttribute('aria-modal', 'true');
		document.body.append(dialog);
		expect(
			shouldHandleGlobalEscape(
				{ key: 'Escape', target: document.body, defaultPrevented: false },
				document
			)
		).toBe(false);
		dialog.remove();
	});

	it('yields when a popover already handled Escape and called preventDefault', () => {
		expect(
			shouldHandleGlobalEscape(
				{ key: 'Escape', target: document.body, defaultPrevented: true },
				document
			)
		).toBe(false);
	});

	// Reproduces the real browser sequence: a popover's Escape handler is
	// registered on `document` in the capture phase and unmounts the overlay
	// (removing its aria-modal/data-escape-overlay marker) synchronously,
	// inside the same keydown dispatch that the global handler also observes
	// on `window` in the bubble phase. The old jsdom tests passed because they
	// called `shouldHandleGlobalEscape` directly against a mocked event
	// object and never exercised this ordering; dispatching one real
	// KeyboardEvent through both phases is what actually caught the bug.
	describe('one real keydown through capture and bubble phases', () => {
		function attachPopoverCaptureHandler(overlay: HTMLElement): () => void {
			function onCapture(event: KeyboardEvent): void {
				if (event.key !== 'Escape') return;
				event.preventDefault();
				overlay.remove();
			}
			document.addEventListener('keydown', onCapture, true);
			return () => document.removeEventListener('keydown', onCapture, true);
		}

		it('does not also fire the global level-up once the popover closes itself', () => {
			const overlay = document.createElement('div');
			overlay.setAttribute('aria-modal', 'true');
			const focusedButton = document.createElement('button');
			overlay.append(focusedButton);
			document.body.append(overlay);
			const detachPopover = attachPopoverCaptureHandler(overlay);

			let globalEscapeFired = false;
			function onWindowKeydown(event: KeyboardEvent): void {
				if (shouldHandleGlobalEscape(event, document)) globalEscapeFired = true;
			}
			window.addEventListener('keydown', onWindowKeydown);

			focusedButton.dispatchEvent(
				new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
			);

			window.removeEventListener('keydown', onWindowKeydown);
			detachPopover();
			expect(document.body.contains(overlay)).toBe(false);
			expect(globalEscapeFired).toBe(false);
		});

		it('still fires the global level-up when no popover is open', () => {
			let globalEscapeFired = false;
			function onWindowKeydown(event: KeyboardEvent): void {
				if (shouldHandleGlobalEscape(event, document)) globalEscapeFired = true;
			}
			window.addEventListener('keydown', onWindowKeydown);

			document.dispatchEvent(
				new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
			);

			window.removeEventListener('keydown', onWindowKeydown);
			expect(globalEscapeFired).toBe(true);
		});
	});
});
