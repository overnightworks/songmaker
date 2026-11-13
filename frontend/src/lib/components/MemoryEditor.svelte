<script lang="ts">
	import { tick } from 'svelte';
	import type { MemoryBundle, MemoryScopeItem } from '#lib/api/types.ts';
	import { refocusIfDropped } from '#lib/utils/focus-trap.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';
	import {
		shouldReplaceMemoryDraft,
		type MemoryProposal,
		type MemoryScope
	} from '#lib/utils/memory-proposals.ts';

	interface Props {
		open: boolean;
		onClose: () => void;
		bundle: MemoryBundle | null;
		loading: boolean;
		error: string;
		savingScope: MemoryScope | null;
		proposals: MemoryProposal[];
		onSave: (scope: MemoryScope, targetId: string, body: string) => Promise<boolean>;
		onAccept: (proposal: MemoryProposal) => Promise<void>;
		onReject: (proposal: MemoryProposal) => void;
	}

	let {
		open,
		onClose,
		bundle,
		loading,
		error,
		savingScope,
		proposals,
		onSave,
		onAccept,
		onReject
	}: Props = $props();

	let closeButton: HTMLButtonElement | undefined = $state();

	$effect(() => {
		closeButton?.focus();
	});

	// Answering the last proposal removes the button that held focus; keep focus
	// inside the editor rather than on the page behind it.
	async function answerProposal(answer: () => void | Promise<void>): Promise<void> {
		await answer();
		await tick();
		refocusIfDropped(closeButton);
	}

	let userDraft = $state('');
	let songDraft = $state('');
	let albumDraft = $state('');
	let userSourceTarget: string | null = null;
	let songSourceTarget: string | null = null;
	let albumSourceTarget: string | null = null;
	let userSourceBody = '';
	let songSourceBody = '';
	let albumSourceBody = '';

	$effect(() => {
		const user = bundle?.user ?? null;
		const song = bundle?.song ?? null;
		const album = bundle?.album ?? null;
		if (
			shouldReplaceMemoryDraft(userSourceTarget, userSourceBody, userDraft, user?.target_id ?? null)
		) {
			userDraft = user?.body ?? '';
		}
		if (
			shouldReplaceMemoryDraft(songSourceTarget, songSourceBody, songDraft, song?.target_id ?? null)
		) {
			songDraft = song?.body ?? '';
		}
		if (
			shouldReplaceMemoryDraft(
				albumSourceTarget,
				albumSourceBody,
				albumDraft,
				album?.target_id ?? null
			)
		) {
			albumDraft = album?.body ?? '';
		}
		userSourceTarget = user?.target_id ?? null;
		userSourceBody = user?.body ?? '';
		songSourceTarget = song?.target_id ?? null;
		songSourceBody = song?.body ?? '';
		albumSourceTarget = album?.target_id ?? null;
		albumSourceBody = album?.body ?? '';
	});

	const userDirty = $derived(bundle !== null && userDraft !== bundle.user.body);
	const songDirty = $derived(bundle?.song != null && songDraft !== bundle.song.body);
	const albumDirty = $derived(bundle?.album != null && albumDraft !== bundle.album.body);

	function scopeLabel(scope: MemoryScope): string {
		if (scope === 'user') return pageText('memory.you');
		if (scope === 'song') return pageText('memory.thisSong');
		return pageText('memory.albumNotes');
	}

	function proposedLabel(scope: MemoryScope): string {
		if (scope === 'user') return pageText('memory.proposedUser');
		if (scope === 'song') return pageText('memory.proposedSong');
		return pageText('memory.proposedAlbum');
	}

	function hint(scope: MemoryScope): string {
		if (scope === 'user') return pageText('memory.hintUser');
		if (scope === 'song') return pageText('memory.hintSong');
		return pageText('memory.hintAlbum');
	}

	async function saveScope(
		scope: MemoryScope,
		item: MemoryScopeItem,
		draft: string
	): Promise<void> {
		await onSave(scope, item.target_id, draft);
	}
</script>

{#if open}
	<section class="memory" aria-label={pageText('cowriter.memory')}>
		<header class="memory-head">
			<span class="memory-title">{pageText('cowriter.memory')}</span>
			<button
				bind:this={closeButton}
				type="button"
				class="memory-close"
				aria-label={pageText('memory.close')}
				title={pageText('memory.close')}
				onclick={onClose}
			>
				<Icon name="x" size={16} />
			</button>
		</header>
		<div class="memory-body">
			{#if proposals.length > 0}
				<div class="proposals">
					{#each proposals as proposal, i (i)}
						<div class="proposal">
							<p class="proposal-title">
								{proposedLabel(proposal.scope)}
							</p>
							<pre class="proposal-body">{proposal.proposedBody}</pre>
							<div class="proposal-actions">
								<button class="accept" onclick={() => answerProposal(() => onAccept(proposal))}
									>{pageText('memory.accept')}</button
								>
								<button class="reject" onclick={() => answerProposal(() => onReject(proposal))}
									>{pageText('memory.reject')}</button
								>
							</div>
						</div>
					{/each}
				</div>
			{/if}
			{#if loading}
				<p class="hint">{pageText('memory.loading')}</p>
			{:else if error}
				<p class="memory-error" role="alert">{error}</p>
			{:else if bundle}
				<label class="scope">
					<span class="scope-title">{scopeLabel('user')}</span>
					<span class="scope-hint">{hint('user')}</span>
					<textarea aria-label={pageText('memory.userField')} bind:value={userDraft} rows="3"
					></textarea>
					<button
						class="save"
						disabled={!userDirty || savingScope === 'user'}
						onclick={() => saveScope('user', bundle.user, userDraft)}
					>
						{savingScope === 'user' ? pageText('memory.saving') : pageText('memory.save')}
					</button>
				</label>
				{#if bundle.song}
					{@const songMem = bundle.song}
					<label class="scope">
						<span class="scope-title">{scopeLabel('song')}</span>
						<span class="scope-hint">{hint('song')}</span>
						<textarea aria-label={pageText('memory.songField')} bind:value={songDraft} rows="3"
						></textarea>
						<button
							class="save"
							disabled={!songDirty || savingScope === 'song'}
							onclick={() => saveScope('song', songMem, songDraft)}
						>
							{savingScope === 'song' ? pageText('memory.saving') : pageText('memory.save')}
						</button>
					</label>
				{/if}
				{#if bundle.album}
					{@const albumMem = bundle.album}
					<label class="scope">
						<span class="scope-title">{scopeLabel('album')}</span>
						<span class="scope-hint">{hint('album')}</span>
						<textarea aria-label={pageText('memory.albumField')} bind:value={albumDraft} rows="3"
						></textarea>
						<button
							class="save"
							disabled={!albumDirty || savingScope === 'album'}
							onclick={() => saveScope('album', albumMem, albumDraft)}
						>
							{savingScope === 'album' ? pageText('memory.saving') : pageText('memory.save')}
						</button>
					</label>
				{/if}
			{/if}
		</div>
	</section>
{/if}

<style>
	.memory {
		border-bottom: 1px solid var(--border);
	}

	.memory-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 4px 0 12px;
	}

	.memory-title {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text);
	}

	.memory-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: var(--hitbox-frequent);
		min-height: var(--hitbox-frequent);
		background: none;
		border: none;
		color: var(--text-subtle);
		cursor: pointer;
	}

	.memory-close:hover {
		color: var(--text);
	}

	.memory-body {
		padding: 0 12px 10px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.scope {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.scope-title {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text);
	}

	.scope-hint,
	.hint {
		font-size: 0.7rem;
		color: var(--text-subtle);
	}

	.memory-error {
		margin: 0;
		color: var(--fail);
		font-size: 0.8rem;
	}

	textarea {
		width: 100%;
		resize: vertical;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.85rem;
		padding: 6px 8px;
		box-sizing: border-box;
	}

	.save,
	.accept,
	.reject {
		align-self: flex-end;
		background: none;
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: 4px;
		padding: 2px 10px;
		font-size: 0.75rem;
		cursor: pointer;
	}

	.save:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.accept {
		border-color: var(--accent);
	}

	.reject {
		border-color: var(--border);
		color: var(--text-subtle);
	}

	.proposals {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.proposal {
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 8px;
		background: var(--surface);
	}

	.proposal-title {
		margin: 0 0 4px;
		font-size: 0.75rem;
		font-weight: 600;
	}

	.proposal-body {
		margin: 0 0 6px;
		white-space: pre-wrap;
		font-family: var(--font-body);
		font-size: 0.8rem;
	}

	.proposal-actions {
		display: flex;
		gap: 6px;
		justify-content: flex-end;
	}

	@media (max-width: 768px) {
		.memory-body {
			max-height: min(300px, 38dvh);
			overflow-y: auto;
			overscroll-behavior-y: contain;
		}
	}
</style>
