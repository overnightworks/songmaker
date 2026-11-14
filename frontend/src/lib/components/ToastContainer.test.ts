import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { addToast, toasts } from '#lib/stores/toast.ts';

import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';

import ToastContainer from './ToastContainer.svelte';
import toastContainerSource from './ToastContainer.svelte?raw';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => toasts.set([]));

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	clearComponentStyles();
	document.body.replaceChildren();
});

describe('an error toast over the page', () => {
	it('lets pointer events through its stack and text but keeps its dismiss button clickable', () => {
		mounted = mount(ToastContainer, { target: document.body });
		addToast('Unsupported format. Accepted: wav', 'error');
		flushSync();

		const stack = document.querySelector('.toast-container');
		const message = document.querySelector('.toast-message');
		const dismiss = document.querySelector('.toast-dismiss');
		if (!stack || !message || !dismiss) throw new Error('Expected the toast to be rendered');

		injectComponentStyles(toastContainerSource, 'ToastContainer.svelte', stack);

		expect(getComputedStyle(stack).pointerEvents).toBe('none');
		expect(getComputedStyle(message).pointerEvents).toBe('none');
		expect(getComputedStyle(dismiss).pointerEvents).toBe('auto');
	});
});
