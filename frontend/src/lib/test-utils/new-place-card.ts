import { flushSync } from 'svelte';

export function field(root: ParentNode, label: string): HTMLInputElement {
	const input = [...root.querySelectorAll('label')]
		.find((candidate) => candidate.textContent?.trim().startsWith(label))
		?.querySelector('input');
	if (!input) throw new Error(`no ${label} field`);
	return input;
}

export function type(input: HTMLInputElement, value: string): void {
	input.value = value;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	flushSync();
}

export function createButton(root: ParentNode): HTMLButtonElement {
	const button = [...root.querySelectorAll('button')].find(
		(candidate) => candidate.textContent?.trim() === 'Create'
	);
	if (!button) throw new Error('no Create button');
	return button;
}

// The submit handler's promise has no caller to reject into, so a failure it
// lets escape surfaces as an unhandled rejection; the test collects those
// instead of letting the runner report them as a crash, and calls the
// returned restore once done.
export function captureUnhandledRejections(): { escaped: unknown[]; restore: () => void } {
	const escaped: unknown[] = [];
	const runnerListeners = process.listeners('unhandledRejection');
	process.removeAllListeners('unhandledRejection');
	process.on('unhandledRejection', (reason) => escaped.push(reason));
	return {
		escaped,
		restore: () => {
			process.removeAllListeners('unhandledRejection');
			for (const listener of runnerListeners) process.on('unhandledRejection', listener);
		}
	};
}
