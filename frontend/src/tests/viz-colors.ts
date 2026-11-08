import { beforeEach } from 'vitest';

// jsdom loads no stylesheet, so the visualizer's accent channels are unset and
// reading them raises. Every test starts with scenario channels; a test that
// needs other values or none sets or removes them itself.
beforeEach(() => {
	const root = document.documentElement.style;
	root.setProperty('--viz-accent-r', '1');
	root.setProperty('--viz-accent-g', '2');
	root.setProperty('--viz-accent-b', '3');
});
