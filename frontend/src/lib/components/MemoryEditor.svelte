<script lang="ts">
	import type { MemoryBundle, MemoryScopeItem } from '$lib/api/types';
	import {
		shouldReplaceMemoryDraft,
		type MemoryProposal,
		type MemoryScope
	} from '$lib/utils/memory-proposals';

	interface Props {
		bundle: MemoryBundle | null;
		loading: boolean;
		error: string;
		savingScope: MemoryScope | null;
		proposals: MemoryProposal[];
		onSave: (scope: MemoryScope, targetId: string, body: string) => Promise<boolean>;
		onAccept: (proposal: MemoryProposal) => Promise<void>;
		onReject: (proposal: MemoryProposal) => void;
	}

	let { bundle, loading, error, savingScope, proposals, onSave, onAccept, onReject }: Props =
		$props();

	let userDraft = $state('');
	let songDraft = $state('');
	let albumDraft = $state('');
	let open = $state(false);
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
		if (scope === 'user') return 'You';
		if (scope === 'song') return 'This song';
		return 'Album notes';
	}

	function hint(scope: MemoryScope): string {
		if (scope === 'user') return 'Taste, language, standing rules';
		if (scope === 'song') return 'Concept, locked vs open decisions, names, open questions';
		return 'Album-level notes — not lyrics';
	}

	async function saveScope(
		scope: MemoryScope,
		item: MemoryScopeItem,
		draft: string
	): Promise<void> {
		await onSave(scope, item.target_id, draft);
	}
</script>

<div class="memory">
	<button class="memory-toggle" onclick={() => (open = !open)} aria-expanded={open}>
		Memory
		<span class="caret">{open ? '▴' : '▾'}</span>
	</button>
	{#if open}
		<div class="memory-body">
			{#if loading}
				<p class="hint">Loading memory…</p>
			{:else if error}
				<p class="memory-error" role="alert">{error}</p>
			{:else if bundle}
				<label class="scope">
					<span class="scope-title">{scopeLabel('user')}</span>
					<span class="scope-hint">{hint('user')}</span>
					<textarea aria-label="User memory" bind:value={userDraft} rows="3"></textarea>
					<button
						class="save"
						disabled={!userDirty || savingScope === 'user'}
						onclick={() => saveScope('user', bundle.user, userDraft)}
					>
						{savingScope === 'user' ? 'Saving...' : 'Save'}
					</button>
				</label>
				{#if bundle.song}
					{@const songMem = bundle.song}
					<label class="scope">
						<span class="scope-title">{scopeLabel('song')}</span>
						<span class="scope-hint">{hint('song')}</span>
						<textarea aria-label="Song memory" bind:value={songDraft} rows="3"></textarea>
						<button
							class="save"
							disabled={!songDirty || savingScope === 'song'}
							onclick={() => saveScope('song', songMem, songDraft)}
						>
							{savingScope === 'song' ? 'Saving...' : 'Save'}
						</button>
					</label>
				{/if}
				{#if bundle.album}
					{@const albumMem = bundle.album}
					<label class="scope">
						<span class="scope-title">{scopeLabel('album')}</span>
						<span class="scope-hint">{hint('album')}</span>
						<textarea aria-label="Album notes" bind:value={albumDraft} rows="3"></textarea>
						<button
							class="save"
							disabled={!albumDirty || savingScope === 'album'}
							onclick={() => saveScope('album', albumMem, albumDraft)}
						>
							{savingScope === 'album' ? 'Saving...' : 'Save'}
						</button>
					</label>
				{/if}
			{/if}
			{#if proposals.length > 0}
				<div class="proposals">
					{#each proposals as proposal, i (i)}
						<div class="proposal">
							<p class="proposal-title">
								Proposed {scopeLabel(proposal.scope)}
							</p>
							<pre class="proposal-body">{proposal.proposedBody}</pre>
							<div class="proposal-actions">
								<button class="accept" onclick={() => onAccept(proposal)}>Accept</button>
								<button class="reject" onclick={() => onReject(proposal)}>Reject</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.memory {
		border-bottom: 1px solid var(--border);
	}

	.memory-toggle {
		width: 100%;
		background: none;
		border: none;
		color: var(--text-subtle);
		font-size: 0.8rem;
		padding: 6px 12px;
		display: flex;
		justify-content: space-between;
		cursor: pointer;
	}

	.memory-toggle:hover {
		color: var(--text);
	}

	.caret {
		opacity: 0.7;
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
		color: var(--score-bad);
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
		border: 1px solid var(--primary);
		color: var(--primary);
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
		border-color: var(--primary);
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
