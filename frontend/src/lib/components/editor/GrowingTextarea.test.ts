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

	afterEach(() => {
		removePhoneViewport();
		Reflect.deleteProperty(Range.prototype, 'getBoundingClientRect');
	});

	function typeOnPhone(caretLineBottom: number) {
		Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
			configurable: true,
			value: () => new DOMRect(0, caretLineBottom - LINE_HEIGHT, 0, LINE_HEIGHT)
		});
		const scrollBy = vi.fn();
		window.scrollBy = scrollBy;
		const viewport = phoneViewport();
		Object.assign(window.visualViewport ?? {}, { offsetTop: 0 });
		viewport.show(KEYBOARD_TOP);
		const textarea = render('one\ntwo').querySelector('textarea');
		if (!textarea) throw new Error('Expected a textarea');
		textarea.focus();
		return { textarea, scrollBy };
	}

	it('scrolls the page when the typed line sits behind the keyboard', async () => {
		const { textarea, scrollBy } = typeOnPhone(KEYBOARD_TOP + 60);
		const shell = watchTypingOnPhone(document, true);
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		await tick();
		shell();
		expect(scrollBy).toHaveBeenCalledWith(0, 60);
	});

	it('leaves the page alone when the typed line is above the keyboard', async () => {
		const { textarea, scrollBy } = typeOnPhone(KEYBOARD_TOP - 10);
		const shell = watchTypingOnPhone(document, true);
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		await tick();
		shell();
		expect(scrollBy).not.toHaveBeenCalled();
	});
});
