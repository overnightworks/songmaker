import { compile } from 'svelte/compiler';

const STYLE_ATTRIBUTE = 'data-component-styles';

// Svelte only stamps its scope class onto elements that at least one scoped
// selector in the component could match, so an element carrying none has no
// scoped rule that can reach it — that is a real fact about the cascade, not
// a measurement failure.
export function elementScopeClass(el: Element): string | undefined {
	return Array.from(el.classList).find((name) => name.startsWith('svelte-'));
}

// Vitest loads components with CSS extraction off, so a mounted component's
// scoped stylesheet never reaches the document and there is nothing to
// measure. Compiling the component's own source here puts it back — pinned to
// the scope class the mounted markup actually carries, so the cascade a
// computed value comes out of is the real one, global sheets included.
export function injectComponentStyles(source: string, filename: string, scoped: Element): void {
	const scopeClass = elementScopeClass(scoped);
	if (!scopeClass) {
		throw new Error(`${filename}: no Svelte scope class on the element to style`);
	}
	const compiled = compile(source, { filename, cssHash: () => scopeClass });
	if (!compiled.css) {
		throw new Error(`${filename}: component has no stylesheet`);
	}
	const sheet = document.createElement('style');
	sheet.setAttribute(STYLE_ATTRIBUTE, filename);
	sheet.textContent = compiled.css.code;
	document.head.append(sheet);
}

export function clearComponentStyles(): void {
	document.head.querySelectorAll(`[${STYLE_ATTRIBUTE}]`).forEach((element) => element.remove());
}
