<script lang="ts">
	import { tick, type Snippet } from 'svelte';
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
		EDITOR_LYRICS_LABEL,
		EDITOR_STYLE_LABEL,
		EDITOR_STYLE_PROMPT_LABEL,
		EDITOR_TAB_TAKES_LABEL,
		EDITOR_VIEW_COWRITER_LABEL
	} from '$lib/constants';
	import TakeStrip from './TakeStrip.svelte';

	interface Props {
		song: SongItem;
		coWriterOpen: boolean;
		compact: boolean;
		cowriterPanel: Snippet;
		onopencowriter: () => void;
	}

	let { song, coWriterOpen, compact, cowriterPanel, onopencowriter }: Props = $props();

	const dirty = $derived($isDirty);
	const latestVersion = $derived<VersionItem | null>($versions[0] ?? null);
	const draftStamp = $derived(
		latestVersion
			? `v${latestVersion.version_number}${dirty ? ' · draft · differs from v' + latestVersion.version_number : ''}`
			: dirty
				? 'draft'
				: ''
	);

	// At compact width the page itself is the one scroll surface (L9): a
	// fixed-height field whose content overflows becomes its own nested
	// scroll box, which is what this replaces. Desktop keeps its own
	// resizable, min-height-floored box untouched — this action only ever
	// touches the node when `active` is true. `value` is watched too so a
	// draft loaded from the store (switching songs, a co-writer write, a
	// version restore) resizes the same as one typed in — but `update` runs
	// as a render effect before the template effect that lands the new
	// `value` on the textarea, so it must wait a tick before measuring, or it
	// reads the old DOM value and leaves the field short. `scrollHeight` sits
	// inside the border box while the set height is the border-box height
	// (`box-sizing: border-box`), so the border itself has to be added back
	// on top. A window resize (rotation) re-wraps the same text to a
	// different height, so the listener stays live for as long as the field
	// does.
	function autogrowTextarea(node: HTMLTextAreaElement, params: { active: boolean; value: string }) {
		let autogrowing = false;
		function resize() {
			node.style.height = 'auto';
			node.style.height = `${node.scrollHeight + node.offsetHeight - node.clientHeight}px`;
		}
		// Desktop's `active: false` must leave the node fully alone so its own
		// manual resize handle keeps working (#993): no listener, and the height
		// is only cleared on the way out of compact — clearing it on every
		// keystroke threw away a height the musician had dragged (#999).
		function apply(next: { active: boolean; value: string }) {
			if (next.active) {
				tick().then(resize);
				node.addEventListener('input', resize);
				window.addEventListener('resize', resize);
			} else if (autogrowing) {
				node.style.height = '';
				node.removeEventListener('input', resize);
				window.removeEventListener('resize', resize);
			}
			autogrowing = next.active;
		}
		apply(params);
		return {
			update: apply,
			destroy() {
				node.removeEventListener('input', resize);
				window.removeEventListener('resize', resize);
			}
		};
	}
</script>

{#if coWriterOpen}
	<div class="cowriter-mode">
		<div class="cowriter-columns">
			<div class="cowriter-chat">
				{@render cowriterPanel()}
			</div>
			<div class="cowriter-lyrics">
				<span class="lyrics-label"
					>{EDITOR_LYRICS_LABEL} <span class="field-stamp">{draftStamp}</span></span
				>
				<textarea
					class="lyrics-area"
					value={$editLyrics}
					oninput={(e) => setDraftLyrics(e.currentTarget.value)}></textarea>
				<label class="style-field">
					<span>{EDITOR_STYLE_LABEL}</span>
					<textarea
						rows="2"
						value={$editPrompt}
						oninput={(e) => setDraftPrompt(e.currentTarget.value)}></textarea>
				</label>
			</div>
			<div class="cowriter-takes">
				<span class="takes-heading">{EDITOR_TAB_TAKES_LABEL}</span>
				<TakeStrip {song} />
			</div>
		</div>
	</div>
{:else}
	<div class="write-mode">
		<label class="edit-field">
			<span>{EDITOR_STYLE_PROMPT_LABEL}</span>
			<textarea
				rows="4"
				class:auto-grow={compact}
				use:autogrowTextarea={{ active: compact, value: $editPrompt }}
				value={$editPrompt}
				oninput={(e) => setDraftPrompt(e.currentTarget.value)}></textarea>
		</label>
		<label class="edit-field">
			<span>{EDITOR_LYRICS_LABEL} <span class="field-stamp">{draftStamp}</span></span>
			<textarea
				class="lyrics-area"
				class:auto-grow={compact}
				use:autogrowTextarea={{ active: compact, value: $editLyrics }}
				rows="15"
				value={$editLyrics}
				oninput={(e) => setDraftLyrics(e.currentTarget.value)}></textarea>
		</label>
		{#if compact}
			<button type="button" class="cowriter-row" data-hitbox="text" onclick={onopencowriter}>
				<span class="cowriter-row-label">{EDITOR_VIEW_COWRITER_LABEL}</span>
				<span class="chevron" aria-hidden="true">›</span>
			</button>
		{/if}
	</div>
{/if}

<style>
	.write-mode {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.cowriter-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		color: var(--text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.cowriter-row-label {
		flex: 1;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.cowriter-row .chevron {
		flex-shrink: 0;
		color: var(--text-subtle);
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

	/* Compact write mode is one scrolling column (L9): a fixed-height field
	   whose content overflows becomes its own nested scroll box, which is
	   what a phone must not have. The JS action sets an explicit height that
	   tracks content, so a manual resize handle (and its own internal
	   scrollbar underneath) would fight it — `resize: none` leaves growth to
	   that height alone. Desktop keeps `resize: vertical` and its own
	   min-height floor untouched. */
	.auto-grow {
		resize: none;
		overflow: hidden;
	}

	/* Filling a fixed height only works where every part has a column of its
	   own to scroll in — the editor above its two-up floor. Stacked, they run
	   on and the workspace scrolls — sharing one height squeezed the lyrics
	   column below its content, which then spilled over the take strip
	   (#185). Co-Writer mode itself is desktop-only now: the phone screen
	   that replaces the page (#990) instantiates CoWriterPanel directly, so
	   this block never renders compact. */
	.cowriter-mode {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-height: 0;
		flex-shrink: 0;
	}

	/* Chat, lyrics and the take strip stand side by side only where the editor
	   has the room for them (the `editor` container SongDetailView owns, #185).
	   Below that they stack, and the strip goes back to scrolling sideways. */
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
	.cowriter-chat {
		height: min(60dvh, calc(100dvh - 441px));
	}

	@container editor (min-width: 680px) {
		.cowriter-mode {
			flex: 1;
			min-height: 0;
		}

		.cowriter-chat {
			height: auto;
		}

		.cowriter-columns {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
			flex: 1;
		}

		/* A grid item's default min-height is `auto`, not `0` — without
		   overriding it, `.cowriter-takes` refuses to shrink below its own
		   content and never actually stretches to the row's height, so
		   `overflow-y: auto` below never gets anything to clip: the column just
		   keeps growing with every take instead of scrolling internally (found
		   only against a real render with enough takes to expose it, issue
		   #358 — jsdom cannot compute this). `.cowriter-chat` and
		   `.cowriter-lyrics` already carry the same declaration for the same
		   reason. */
		.cowriter-takes {
			width: 7rem;
			align-items: center;
			min-height: 0;
		}

		.cowriter-takes :global(.take-strip) {
			flex-direction: column;
			overflow-x: visible;
			overflow-y: auto;
			touch-action: pan-y;
			min-height: 0;
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
