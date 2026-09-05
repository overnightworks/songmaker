import { describe, expect, it, vi } from 'vitest';
import { focusFirstIn, handleFocusTrapKeydown } from './focus-trap';

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function buildContainer(): HTMLDivElement {
	const container = document.createElement('div');
	container.innerHTML = `
		<button id="first">First</button>
		<a id="middle" href="/x">Middle</a>
		<button id="last">Last</button>
	`;
	document.body.append(container);
	return container;
}

describe('focusFirstIn', () => {
	it('focuses the first focusable descendant', () => {
		const container = buildContainer();
		focusFirstIn(container);
		expect(document.activeElement?.id).toBe('first');
		container.remove();
	});

	it('focuses the container itself when nothing inside is focusable', () => {
		const container = document.createElement('div');
		container.tabIndex = -1;
		document.body.append(container);
		focusFirstIn(container);
		expect(document.activeElement).toBe(container);
		container.remove();
	});
});

describe('handleFocusTrapKeydown', () => {
	it('calls onEscape and prevents default', () => {
		const container = buildContainer();
		const onEscape = vi.fn();
		const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
		handleFocusTrapKeydown(container, event, onEscape);
		expect(onEscape).toHaveBeenCalledTimes(1);
		expect(event.defaultPrevented).toBe(true);
		container.remove();
	});

	it('leaves an Escape event consumed by a descendant alone', () => {
		const container = buildContainer();
		const onEscape = vi.fn();
		const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
		event.preventDefault();

		handleFocusTrapKeydown(container, event, onEscape);

		expect(onEscape).not.toHaveBeenCalled();
		container.remove();
	});

	it('wraps Tab from the last element back to the first', () => {
		const container = buildContainer();
		const last = requireElement<HTMLElement>(container, '#last');
		last.focus();
		const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });
		handleFocusTrapKeydown(container, event, vi.fn());
		expect(document.activeElement?.id).toBe('first');
		container.remove();
	});

	it('includes an enabled search field in the tab order', () => {
		const container = document.createElement('div');
		container.innerHTML = '<input type="search"><button>Last</button>';
		document.body.append(container);
		const last = requireElement<HTMLElement>(container, 'button');
		last.focus();
		const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });

		handleFocusTrapKeydown(container, event, vi.fn());

		expect(document.activeElement).toBe(requireElement(container, 'input'));
		container.remove();
	});

	it('wraps Shift+Tab from the first element back to the last', () => {
		const container = buildContainer();
		const first = requireElement<HTMLElement>(container, '#first');
		first.focus();
		const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true });
		handleFocusTrapKeydown(container, event, vi.fn());
		expect(document.activeElement?.id).toBe('last');
		container.remove();
	});

	it('pulls focus back in when it escapes the container', () => {
		const container = buildContainer();
		const outside = document.createElement('button');
		document.body.append(outside);
		outside.focus();
		const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });
		handleFocusTrapKeydown(container, event, vi.fn());
		expect(document.activeElement?.id).toBe('first');
		container.remove();
		outside.remove();
	});

	it('ignores keys other than Escape and Tab', () => {
		const container = buildContainer();
		const middle = requireElement<HTMLElement>(container, '#middle');
		middle.focus();
		const event = new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });
		handleFocusTrapKeydown(container, event, vi.fn());
		expect(document.activeElement?.id).toBe('middle');
		expect(event.defaultPrevented).toBe(false);
		container.remove();
	});
});
