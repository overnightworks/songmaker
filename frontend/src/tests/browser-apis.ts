// jsdom implements neither scrolling into view, pointer capture, animation listing nor
// media queries, which every supported browser has; components call them directly,
// so they exist here as no-ops and a test that needs the arguments installs
// its own spy.
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.getAnimations ??= () => [];
window.matchMedia ??= (query: string) =>
	({
		matches: false,
		media: query,
		addEventListener: () => {},
		removeEventListener: () => {}
	}) as unknown as MediaQueryList;
