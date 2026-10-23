import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { removePhoneViewport, phoneViewport } from '$lib/test-utils/on-screen-keyboard';
import { watchTypingOnPhone } from '$lib/stores/ui';
import GrowingTextarea from './GrowingTextarea.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function render(value: string, oninput: (typed: string) => void = () => {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const label = document.createElement('label');
	label.textContent = 'Lyrics';
	target.append(label);
	mounted.push(
		mount(GrowingTextarea, { target: label, props: { value, oninput, minimumLines: 3 } })
	);
	return target;
}

function sectionLabels(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.mirror span'), (span) => span.textContent ?? '');
}

describe('GrowingTextarea', () => {
	it('shows [Intro] and [Verse 1] lines as section labels in the mirror', () => {
		const target = render('[Intro]\nla la\n[Verse 1]\nhello');
		expect(sectionLabels(target)).toEqual(['[Intro]', '[Verse 1]']);
	});

	it('leaves text without brackets unhighlighted', () => {
		expect(sectionLabels(render('just words'))).toEqual([]);
	});

	it('keeps the typed text, tags included, as the textarea value', () => {
		const typed = '[Chorus]\nline one\n\n';
		const textarea = render(typed).querySelector('textarea');
		expect(textarea?.value).toBe(typed);
	});

	it('hides the mirror from assistive technology and names the field by its label', () => {
		const target = render('[Intro]');
		expect(target.querySelector('.mirror')?.getAttribute('aria-hidden')).toBe('true');
		expect(target.querySelector('label')?.control).toBe(target.querySelector('textarea'));
	});

	it('reports what is typed', async () => {
		const oninput = vi.fn();
		const textarea = render('a', oninput).querySelector('textarea');
		if (!textarea) throw new Error('Expected a textarea');
		textarea.value = 'ab [Bridge]';
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(oninput).toHaveBeenCalledWith('ab [Bridge]');
	});
});

describe('GrowingTextarea on the phone with the keyboard open', () => {
	const KEYBOARD_TOP = 500;
	const LINE_HEIGHT = 20;
	let unwatch: (() => void) | undefined;

	afterEach(() => {
		unwatch?.();
		unwatch = undefined;
		removePhoneViewport();
		Reflect.deleteProperty(Range.prototype, 'getBoundingClientRect');
		vi.restoreAllMocks();
	});

	async function typeOnPhone(caretLineBottom: number) {
		Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
			configurable: true,
			value: () => new DOMRect(0, caretLineBottom - LINE_HEIGHT, 0, LINE_HEIGHT)
		});
		const scroller = document.createElement('main');
		scroller.style.overflowY = 'auto';
		vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 40, 390, 804));
		const scrollBy = vi.fn();
		scroller.scrollBy = scrollBy;
		document.body.append(scroller);
		const target = render('one\ntwo');
		scroller.append(target);
		const viewport = phoneViewport();
		viewport.show(KEYBOARD_TOP);
		const textarea = target.querySelector('textarea');
		if (!textarea) throw new Error('Expected a textarea');
		textarea.focus();
		unwatch = watchTypingOnPhone(document, true);
		await tick();
		scrollBy.mockClear();
		return { textarea, scrollBy, viewport };
	}

	async function typeIn(textarea: HTMLTextAreaElement) {
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		await tick();
	}

	it('scrolls the scroller when the typed line sits behind the keyboard', async () => {
		const { textarea, scrollBy } = await typeOnPhone(KEYBOARD_TOP + 60);
		await typeIn(textarea);
		expect(scrollBy).toHaveBeenCalledWith(0, 60);
	});

	it('scrolls the scroller back when the typed line sits under its top edge', async () => {
		const { textarea, scrollBy } = await typeOnPhone(40 + LINE_HEIGHT - 15);
		await typeIn(textarea);
		expect(scrollBy).toHaveBeenCalledWith(0, -15);
	});

	it('follows a caret moved without typing', async () => {
		const { textarea, scrollBy } = await typeOnPhone(KEYBOARD_TOP + 60);
		textarea.setSelectionRange(2, 2);
		document.dispatchEvent(new Event('selectionchange'));
		await tick();
		await tick();
		expect(scrollBy).toHaveBeenCalledWith(0, 60);
	});

	it('leaves the scroller alone when the typed line is above the keyboard', async () => {
		const { textarea, scrollBy } = await typeOnPhone(KEYBOARD_TOP - 10);
		await typeIn(textarea);
		expect(scrollBy).not.toHaveBeenCalled();
	});

	it('leaves the scroller alone when no keyboard is open', async () => {
		const { textarea, scrollBy, viewport } = await typeOnPhone(KEYBOARD_TOP + 60);
		viewport.closeKeyboard();
		await tick();
		await typeIn(textarea);
		expect(scrollBy).not.toHaveBeenCalled();
	});
});
