import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
