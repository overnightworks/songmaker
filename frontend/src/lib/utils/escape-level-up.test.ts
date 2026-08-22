import { describe, expect, it } from 'vitest';
import {
	escapeLevelUpTarget,
	hasOpenOverlay,
	isEditableElement,
	shouldHandleGlobalEscape
} from './escape-level-up';

describe('escapeLevelUpTarget', () => {
	it('goes from a song to its collection', () => {
		expect(escapeLevelUpTarget(true, true)).toBe('collection');
	});

	it('goes from a collection to the wall', () => {
		expect(escapeLevelUpTarget(false, true)).toBe('wall');
	});

	it('does nothing at the wall', () => {
		expect(escapeLevelUpTarget(false, false)).toBeNull();
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

	it('reports no overlay when none is mounted', () => {
		expect(hasOpenOverlay(document)).toBe(false);
	});
});

describe('shouldHandleGlobalEscape', () => {
	it('handles Escape with no overlay and no editable focus', () => {
		expect(shouldHandleGlobalEscape({ key: 'Escape', target: document.body }, document)).toBe(true);
	});

	it('ignores keys other than Escape', () => {
		expect(shouldHandleGlobalEscape({ key: 'Enter', target: document.body }, document)).toBe(false);
	});

	it('yields while typing in a textarea', () => {
		const textarea = document.createElement('textarea');
		expect(shouldHandleGlobalEscape({ key: 'Escape', target: textarea }, document)).toBe(false);
	});

	it('yields while a dialog is open', () => {
		const dialog = document.createElement('div');
		dialog.setAttribute('aria-modal', 'true');
		document.body.append(dialog);
		expect(shouldHandleGlobalEscape({ key: 'Escape', target: document.body }, document)).toBe(
			false
		);
		dialog.remove();
	});
});
