import { afterEach, describe, expect, it, vi } from 'vitest';
import { closeTopLayer, holdLayer, resetNavigationForTests } from '$lib/stores/navigation';
import { escapeLevelUpTarget, handleGlobalEscape, isEditableElement } from './escape-level-up';

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

describe('handleGlobalEscape', () => {
	afterEach(() => {
		resetNavigationForTests();
		document.body.replaceChildren();
	});

	function fieldOnPage(tag: 'input' | 'textarea'): HTMLElement {
		const field = document.createElement(tag);
		document.body.append(field);
		return field;
	}

	function pressEscape(target: EventTarget, levelUp: () => void): KeyboardEvent {
		const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
		function onWindowKeydown(keydown: KeyboardEvent): void {
			handleGlobalEscape(keydown, { closeTopLayer, levelUp });
		}
		window.addEventListener('keydown', onWindowKeydown);
		target.dispatchEvent(event);
		window.removeEventListener('keydown', onWindowKeydown);
		return event;
	}

	it('moves one level up when nothing is open', () => {
		const levelUp = vi.fn();

		pressEscape(document.body, levelUp);

		expect(levelUp).toHaveBeenCalledOnce();
	});

	it('closes the topmost layer, not one below it, and stays on the page', () => {
		const closed: string[] = [];
		holdLayer('song', () => closed.push('song'));
		holdLayer('song-menu', () => closed.push('song-menu'));
		const levelUp = vi.fn();

		const event = pressEscape(document.body, levelUp);

		expect(closed).toEqual(['song-menu']);
		expect(event.defaultPrevented).toBe(true);
		expect(levelUp).not.toHaveBeenCalled();
	});

	it('moves up again once the layer it closed has left', () => {
		const leave = holdLayer('sheet', () => leave());
		const levelUp = vi.fn();

		pressEscape(document.body, levelUp);
		pressEscape(document.body, levelUp);

		expect(levelUp).toHaveBeenCalledOnce();
	});

	it('closes the layer a text field sits in', () => {
		const close = vi.fn();
		holdLayer('details-editing', close);

		pressEscape(fieldOnPage('input'), vi.fn());

		expect(close).toHaveBeenCalledOnce();
	});

	it('never leaves the page from a text field', () => {
		const levelUp = vi.fn();

		pressEscape(fieldOnPage('textarea'), levelUp);

		expect(levelUp).not.toHaveBeenCalled();
	});

	it('yields to an Escape a component already claimed', () => {
		const close = vi.fn();
		holdLayer('rail-drawer', close);
		const levelUp = vi.fn();
		const search = fieldOnPage('input');
		search.addEventListener('keydown', (event) => event.preventDefault());

		pressEscape(search, levelUp);

		expect(close).not.toHaveBeenCalled();
		expect(levelUp).not.toHaveBeenCalled();
	});

	it('ignores keys other than Escape', () => {
		const close = vi.fn();
		holdLayer('song-menu', close);
		const levelUp = vi.fn();

		handleGlobalEscape(new KeyboardEvent('keydown', { key: 'Enter' }), { closeTopLayer, levelUp });

		expect(close).not.toHaveBeenCalled();
		expect(levelUp).not.toHaveBeenCalled();
	});
});
