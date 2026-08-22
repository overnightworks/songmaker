<script lang="ts">
	import {
		activeDiff,
		appliedDiffMode,
		editLyrics,
		editPrompt,
		isDirty,
		setDraftLyrics,
		setDraftPrompt,
		versions
	} from '$lib/stores/editor';
	import type { SongItem, VersionItem } from '$lib/api/types';
	import CoWriterPanel from '../CoWriterPanel.svelte';
	import TakeStrip from './TakeStrip.svelte';

	interface Props {
		song: SongItem;
		allSongs: SongItem[];
		coWriterOpen: boolean;
		compact: boolean;
		onselecttake: (generationId: string) => void;
		onturncompleted: () => void;
	}

	let { song, allSongs, coWriterOpen, compact, onselecttake, onturncompleted }: Props = $props();

	let mobileSubTab = $state<'chat' | 'lyrics'>('chat');

	const dirty = $derived($isDirty);
	const isAppliedDiff = $derived($appliedDiffMode);
	const diff = $derived($activeDiff);
	const latestVersion = $derived<VersionItem | null>($versions[0] ?? null);
	const draftStamp = $derived(
		latestVersion
			? `v${latestVersion.version_number}${dirty ? ' · draft · differs from v' + latestVersion.version_number : ''}`
			: dirty
				? 'draft'
				: ''
	);
</script>

{#if coWriterOpen}
	<div class="cowriter-mode" class:compact>
		{#if compact}
			<div class="mobile-subtabs" role="tablist" aria-label="Write">
				<button
					type="button"
					role="tab"
					class:active={mobileSubTab === 'chat'}
					aria-selected={mobileSubTab === 'chat'}
					onclick={() => (mobileSubTab = 'chat')}
				>
					Chat
				</button>
				<button
					type="button"
					role="tab"
					class:active={mobileSubTab === 'lyrics'}
					aria-selected={mobileSubTab === 'lyrics'}
					onclick={() => (mobileSubTab = 'lyrics')}
				>
					Lyrics
				</button>
			</div>
		{/if}

		<div class="cowriter-columns">
			{#if !compact || mobileSubTab === 'chat'}
				<div class="cowriter-chat">
					<CoWriterPanel
						currentSongId={song.id}
						currentAlbumId={song.album_id}
						currentAlbumTitle={song.album_title}
						{allSongs}
						versions={$versions}
						{onturncompleted}
					/>
				</div>
			{/if}
			{#if !compact || mobileSubTab === 'lyrics'}
				<div class="cowriter-lyrics">
					<span class="lyrics-label">Lyrics <span class="field-stamp">{draftStamp}</span></span>
					<textarea
						class="lyrics-area"
						value={$editLyrics}
						oninput={(e) => setDraftLyrics(e.currentTarget.value)}
					></textarea>
					<label class="style-field">
						<span>Style</span>
						<textarea
							rows="2"
							value={$editPrompt}
							oninput={(e) => setDraftPrompt(e.currentTarget.value)}
						></textarea>
					</label>
				</div>
			{/if}
			{#if !compact}
				<div class="cowriter-takes">
					<span class="takes-heading">Takes</span>
					<TakeStrip generations={song.generations} onselect={(gen) => onselecttake(gen.id)} />
				</div>
			{/if}
		</div>
	</div>
{:else}
	<div class="write-mode">
		{#if isAppliedDiff && diff}
			<div class="diff-banner">Claude applied changes</div>
		{/if}
		<label class="edit-field">
			<span>Style Prompt</span>
			<textarea rows="4" value={$editPrompt} oninput={(e) => setDraftPrompt(e.currentTarget.value)}
			></textarea>
		</label>
		<label class="edit-field">
			<span>Lyrics <span class="field-stamp">{draftStamp}</span></span>
			<textarea
				class="lyrics-area"
				rows="15"
				value={$editLyrics}
				oninput={(e) => setDraftLyrics(e.currentTarget.value)}
			></textarea>
		</label>
	</div>
{/if}

<style>
	.write-mode {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.diff-banner {
		padding: 0.4rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.75rem;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.edit-field {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.edit-field span {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.field-stamp {
		font-size: 0.65rem;
		color: var(--text-subtle);
		text-transform: none;
		letter-spacing: 0;
	}

	.edit-field textarea,
	.style-field textarea,
	.lyrics-area {
		padding: 0.6rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 1rem;
		width: 100%;
		min-width: 0;
	}

	.edit-field textarea:focus,
	.style-field textarea:focus,
	.lyrics-area:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.lyrics-area {
		font-family: 'Courier New', monospace;
		font-size: 1rem;
		line-height: 1.6;
		min-height: 200px;
		resize: vertical;
	}

	.cowriter-mode {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		height: 100%;
		min-height: 0;
	}

	.mobile-subtabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--border);
	}

	.mobile-subtabs button {
		padding: 0.5rem 1rem;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.mobile-subtabs button.active {
		color: var(--primary);
		border-color: var(--primary);
	}

	.cowriter-columns {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		gap: 1rem;
		flex: 1;
		min-height: 0;
	}

	.cowriter-mode.compact .cowriter-columns {
		grid-template-columns: 1fr;
	}

	.cowriter-chat,
	.cowriter-lyrics {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		min-height: 0;
		min-width: 0;
	}

	.cowriter-chat :global(.cowriter) {
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.style-field {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.style-field span,
	.lyrics-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.cowriter-takes {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.4rem;
		width: 3.4rem;
	}

	.cowriter-takes :global(.take-strip) {
		flex-direction: column;
		overflow-x: visible;
		overflow-y: auto;
	}

	.takes-heading {
		font-size: 0.62rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}
</style>
