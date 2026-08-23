<script lang="ts">
	import {
		editLyrics,
		editPrompt,
		isDirty,
		setDraftLyrics,
		setDraftPrompt,
		versions
	} from '$lib/stores/editor';
	import type { SongItem, VersionItem } from '$lib/api/types';
	import {
		EDITOR_CHAT_LABEL,
		EDITOR_LYRICS_LABEL,
		EDITOR_STYLE_LABEL,
		EDITOR_STYLE_PROMPT_LABEL,
		EDITOR_TAB_TAKES_LABEL
	} from '$lib/constants';
	import CoWriterPanel from '../CoWriterPanel.svelte';
	import TakeStrip from './TakeStrip.svelte';

	interface Props {
		song: SongItem;
		allSongs: SongItem[];
		coWriterOpen: boolean;
		compact: boolean;
		onturncompleted: () => void;
	}

	let { song, allSongs, coWriterOpen, compact, onturncompleted }: Props = $props();

	let mobileSubTab = $state<'chat' | 'lyrics'>('chat');

	const dirty = $derived($isDirty);
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
					{EDITOR_CHAT_LABEL}
				</button>
				<button
					type="button"
					role="tab"
					class:active={mobileSubTab === 'lyrics'}
					aria-selected={mobileSubTab === 'lyrics'}
					onclick={() => (mobileSubTab = 'lyrics')}
				>
					{EDITOR_LYRICS_LABEL}
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
					<span class="lyrics-label"
						>{EDITOR_LYRICS_LABEL} <span class="field-stamp">{draftStamp}</span></span
					>
					<textarea
						class="lyrics-area"
						value={$editLyrics}
						oninput={(e) => setDraftLyrics(e.currentTarget.value)}
					></textarea>
					<label class="style-field">
						<span>{EDITOR_STYLE_LABEL}</span>
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
					<span class="takes-heading">{EDITOR_TAB_TAKES_LABEL}</span>
					<TakeStrip {song} />
				</div>
			{/if}
		</div>
	</div>
{:else}
	<div class="write-mode">
		<label class="edit-field">
			<span>{EDITOR_STYLE_PROMPT_LABEL}</span>
			<textarea rows="4" value={$editPrompt} oninput={(e) => setDraftPrompt(e.currentTarget.value)}
			></textarea>
		</label>
		<label class="edit-field">
			<span>{EDITOR_LYRICS_LABEL} <span class="field-stamp">{draftStamp}</span></span>
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

	/* Filling a fixed height only works where every part has a column of its
	   own to scroll in: the compact sheet, which shows one at a time, and the
	   editor above its two-up floor. Stacked, they run on and the workspace
	   scrolls — sharing one height squeezed the lyrics column below its
	   content, which then spilled over the take strip (#185). */
	.cowriter-mode {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-height: 0;
		flex-shrink: 0;
	}

	.cowriter-mode.compact {
		height: 100%;
		flex-shrink: 1;
	}

	.cowriter-mode.compact .cowriter-columns {
		flex: 1;
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

	/* Chat, lyrics and the take strip stand side by side only where the editor
	   has the room for them (the `editor` container SongDetailView owns, #185).
	   Below that — and in the compact sheet, which is outside that container —
	   they stack, and the strip goes back to scrolling sideways. */
	.cowriter-columns {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 1rem;
		min-height: 0;
	}

	/* Stacked, the chat column would be as tall as the whole conversation: its
	   message list would never reach a bound to scroll in and the composer
	   would sit below the fold, out of reach. A share of the viewport gives it
	   that bound — but the viewport isn't `.editor-body`'s own box: docking Now
	   Playing narrows the editor below the two-up floor exactly where the
	   header wraps to three lines, and 60dvh of the full window ran past
	   `.editor-body`'s own visible height there, leaving the composer behind a
	   scroll of the wrong container (#185). `.editor-body` reports no size of
	   its own to style against — it isn't a container, WriteColumn is one of
	   its children, sharing it with the Recipe chip row above `.cowriter-mode`
	   — so the second bound is the same chrome sum measured directly at
	   1100×800 and 1280×800 with the dock open, the width band this rule
	   actually governs: two-up crosses the 680px container threshold below and
	   overrides this back to `auto`. From the viewport's top: the wrapped
	   header (147.75px) + the panel's own padding and the gaps around
	   `.editor-body` (~56px) + the Recipe chip row this song's params render
	   above the chat column (~69px) + the player bar's reserved height
	   (`--player-height`, 88px) ≈ 441px. 100dvh minus that is the room `.cowriter-chat`
	   actually has below its own top before the fold, and 60dvh remains the
	   cap on a window tall enough to make it the smaller side. A song whose
	   params render a taller (wrapped) chip row eats into this margin — the
	   same approximation the wrapped-header estimate already carries. */
	.cowriter-mode:not(.compact) .cowriter-chat {
		height: min(60dvh, calc(100dvh - 441px));
	}

	@container editor (min-width: 680px) {
		.cowriter-mode {
			flex: 1;
			min-height: 0;
		}

		.cowriter-mode:not(.compact) .cowriter-chat {
			height: auto;
		}

		.cowriter-columns {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
			flex: 1;
		}

		.cowriter-takes {
			width: 7rem;
			align-items: center;
		}

		.cowriter-takes :global(.take-strip) {
			flex-direction: column;
			overflow-x: visible;
			overflow-y: auto;
		}
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

	.cowriter-lyrics .lyrics-area {
		flex: 1;
	}

	/* Stacked, the strip is a row that scrolls sideways, so it has to fill the
	   width it is given: centred, it sized to its 14 chips instead and the
	   editor body clipped the ones past the fold away — scrollable only in
	   name, since nothing overflowed the strip itself (#185). Centring is the
	   two-up column's rule, where the chips sit above one another. */
	.cowriter-takes {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 0.4rem;
		min-width: 0;
	}

	.takes-heading {
		font-size: 0.62rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}
</style>
