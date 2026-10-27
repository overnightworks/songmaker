// The whole-document loads a page leaves by. The history controller owns when
// each one runs; `browserDocumentLoads` is how the browser performs them.
export interface DocumentLoads {
	assign(url: string): void;
	replace(url: string): void;
	reload(): void;
	// A top-level form POST with no fields: the one load that carries a method.
	submitPost(action: string): void;
}

export const browserDocumentLoads: DocumentLoads = {
	assign: (url) => window.location.assign(url),
	replace: (url) => window.location.replace(url),
	reload: () => window.location.reload(),
	submitPost(action) {
		const form = document.createElement('form');
		form.method = 'post';
		form.action = action;
		form.hidden = true;
		document.body.append(form);
		form.submit();
	}
};

// Loading an address with a `#` part over an address that differs from it in
// nothing else only scrolls to that anchor and loads no document: the page
// would stay, signed in, while it counts as gone (#1340). The standing address
// can carry one -- a take's provenance link, a bookmark -- so a fresh document
// is loaded at the address without it.
export function documentAddress(url: string): string {
	const address = new URL(url, location.href);
	address.hash = '';
	return address.href;
}
