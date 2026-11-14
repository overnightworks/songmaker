import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MemoryBundle } from '#lib/api/types.ts';
import type { MemoryProposal } from '#lib/utils/memory-proposals.ts';
import { words } from '#lib/words/en.ts';
import MemoryEditor from './MemoryEditor.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.innerHTML = '';
});

const fullBundle: MemoryBundle = {
	user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' },
	song: { scope: 'song', target_id: 's1', body: 'Chorus is locked' },
	album: { scope: 'album', target_id: 'a1', body: 'A night-city album' }
};

async function renderEditor(bundle: MemoryBundle, proposals: MemoryProposal[] = []) {
	const onSave = vi.fn(async () => true);
	const onAccept = vi.fn(async () => {});
	const onReject = vi.fn();
	const target = document.createElement('div');
	document.body.appendChild(target);
	mounted.push(
		mount(MemoryEditor, {
			target,
			props: {
				open: true,
				onClose: () => {},
				bundle,
				loading: false,
				error: '',
				savingScope: null,
				proposals,
				onSave,
				onAccept,
				onReject
			}
		})
	);
	await tick();
	return { target, onSave, onAccept, onReject };
}

function field(target: HTMLElement, label: string): HTMLTextAreaElement | null {
	return target.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`);
}

async function type(textarea: HTMLTextAreaElement | null, value: string): Promise<void> {
	if (!textarea) throw new Error('Expected the memory field');
	textarea.value = value;
	textarea.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
}

function saveButtonOf(textarea: HTMLTextAreaElement | null): HTMLButtonElement {
	const button = textarea?.closest('label')?.querySelector<HTMLButtonElement>('button.save');
	if (!button) throw new Error('Expected the field to carry a Save button');
	return button;
}

describe('MemoryEditor', () => {
	// Spec: REQ-COWRITER-15 -- each memory field shows its stored text and saves the musician's edit.
	it.each([
		[words['memory.userField'], 'user', 'u1', 'Prefers short lines'],
		[words['memory.songField'], 'song', 's1', 'Chorus is locked'],
		[words['memory.albumField'], 'album', 'a1', 'A night-city album']
	])('shows %s and saves the edit of it', async (label, scope, targetId, stored) => {
		const { target, onSave } = await renderEditor(fullBundle);
		expect(field(target, label)?.value).toBe(stored);

		await type(field(target, label), 'Edited by hand');
		saveButtonOf(field(target, label)).click();
		await tick();

		expect(onSave).toHaveBeenCalledExactlyOnceWith(scope, targetId, 'Edited by hand');
	});

	// Spec: REQ-COWRITER-15 -- album notes appear only when the bundle carries them.
	it('shows no album field when the album has no notes', async () => {
		const { target } = await renderEditor({ user: fullBundle.user, song: fullBundle.song });

		expect(field(target, words['memory.userField'])).not.toBeNull();
		expect(field(target, 'Song memory')).not.toBeNull();
		expect(field(target, words['memory.albumField'])).toBeNull();
	});

	const proposal: MemoryProposal = {
		scope: 'user',
		targetId: 'u1',
		currentBody: 'Prefers short lines',
		proposedBody: 'Prefers short lines, no rhymes'
	};

	// Spec: REQ-COWRITER-17 -- a proposal changes nothing until Accept, and Reject hands nothing to save.
	it('hands a proposal to its owner only on Accept, and saves nothing on Reject or when ignored', async () => {
		const ignored = await renderEditor(fullBundle, [proposal]);
		expect(ignored.onAccept).not.toHaveBeenCalled();
		expect(ignored.onSave).not.toHaveBeenCalled();

		ignored.target.querySelector<HTMLButtonElement>('.proposal .reject')?.click();
		await tick();
		expect(ignored.onReject).toHaveBeenCalledExactlyOnceWith(proposal);
		expect(ignored.onAccept).not.toHaveBeenCalled();
		expect(ignored.onSave).not.toHaveBeenCalled();

		const accepted = await renderEditor(fullBundle, [proposal]);
		accepted.target.querySelector<HTMLButtonElement>('.proposal .accept')?.click();
		await tick();
		expect(accepted.onAccept).toHaveBeenCalledExactlyOnceWith(proposal);
		expect(accepted.onReject).not.toHaveBeenCalled();
	});
});
