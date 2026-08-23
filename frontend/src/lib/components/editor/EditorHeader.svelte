<script lang="ts">
	import type { ShareResult, SongItem } from '$lib/api/types';
	import {
		ALBUM_COVER_ACCEPT,
		EDITOR_VIEW_COWRITER_LABEL,
		EDITOR_VIEW_RECIPE_LABEL,
		EDITOR_VIEWS_LABEL,
		SONG_COVER_REMOVE_LABEL,
		SONG_NEXT_LABEL,
		SONG_PREVIOUS_LABEL
	} from '$lib/constants';
	import Breadcrumb from '../Breadcrumb.svelte';
	import EditableTitle from '../EditableTitle.svelte';
	import Icon from '../Icon.svelte';
	import SongMenu from './SongMenu.svelte';

	interface BreadcrumbItem {
		label: string;
		onclick?: () => void;
	}

	interface Props {
		song: SongItem;
		coverUrl: string | null;
		coverFailed: boolean;
		coverAlt: string;
		artFill: string | null;
		initials: string;
		hasOwnCover: boolean;
		coverBusy: boolean;
		coverActionLabel: string;
		onrenamesong: (title: string) => Promise<void>;
		onsaveversion: () => void;
		oncoverfile: (event: Event) => void;
		oncoverremove: () => void;
		oncovererror: () => void;
		breadcrumbItems: BreadcrumbItem[];
		songRail: boolean;
		previousDisabled: boolean;
		nextDisabled: boolean;
		onselectprevious: () => void;
		onselectnext: () => void;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		onaddtoplaylist: () => void;
		ondeletesong: () => void;
		recipeOpen: boolean;
		coWriterOpen: boolean;
		ontogglerecipe: () => void;
		ontogglecowriter: () => void;
		ongenerate: () => void;
		generateLabel: string;
		generateDisabled: boolean;
		generateTitle: string;
		generating: boolean;
		compact: boolean;
	}

	let {
		song,
		coverUrl,
		coverFailed,
		coverAlt,
		artFill,
		initials,
		hasOwnCover,
		coverBusy,
		coverActionLabel,
		onrenamesong,
		onsaveversion,
		oncoverfile,
		oncoverremove,
		oncovererror,
		breadcrumbItems,
		songRail,
		previousDisabled,
		nextDisabled,
		onselectprevious,
		onselectnext,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		onaddtoplaylist,
		ondeletesong,
		recipeOpen,
		coWriterOpen,
		ontogglerecipe,
		ontogglecowriter,
		ongenerate,
		generateLabel,
		generateDisabled,
		generateTitle,
		generating,
		compact
	}: Props = $props();

	let coverInput: HTMLInputElement | null = $state(null);
	let titleEditor: { startEdit: () => void } | undefined = $state();
</script>

<div class="detail-header">
	<div class="detail-identity">
		<div class="cover-hero">
			{#if coverUrl && !coverFailed}
				<img src={coverUrl} alt={coverAlt} onerror={oncovererror} />
			{:else if artFill}
				<span class="cover-fallback" style:background={artFill} aria-hidden="true"></span>
			{:else}
				<span class="cover-fallback cover-initials" aria-hidden="true">{initials}</span>
			{/if}
			<input
				bind:this={coverInput}
				class="cover-file-input"
				type="file"
				accept={ALBUM_COVER_ACCEPT}
				onchange={oncoverfile}
			/>
			<button
				type="button"
				class="cover-hit"
				onclick={() => coverInput?.click()}
				disabled={coverBusy}
				aria-label={coverActionLabel}
			></button>
			{#if hasOwnCover}
				<button
					type="button"
					class="cover-remove"
					onclick={oncoverremove}
					disabled={coverBusy}
					aria-label={SONG_COVER_REMOVE_LABEL}
				>
					×
				</button>
			{/if}
		</div>
		<div class="song-heading">
			<div class="title-row">
				<h2 class="song-title" aria-label={song.title}>
					<EditableTitle
						bind:this={titleEditor}
						value={song.title}
						onsave={onrenamesong}
						ariaLabel="Song title"
					/>
				</h2>
				<SongMenu
					title={song.title}
					{isShared}
					{shareSlug}
					{onshare}
					{onunshare}
					onrename={() => titleEditor?.startEdit()}
					{onsaveversion}
					{onaddtoplaylist}
					ondelete={ondeletesong}
				/>
			</div>
			{#if songRail}
				<div class="song-rail">
					<Breadcrumb items={breadcrumbItems} />
					<div class="song-neighbors">
						<button
							type="button"
							class="song-neighbor"
							data-hitbox="frequent"
							data-hitbox-face
							aria-label={SONG_PREVIOUS_LABEL}
							disabled={previousDisabled}
							onclick={onselectprevious}
						>
							<Icon name="skip-back" size={14} />
						</button>
						<button
							type="button"
							class="song-neighbor"
							data-hitbox="frequent"
							data-hitbox-face
							aria-label={SONG_NEXT_LABEL}
							disabled={nextDisabled}
							onclick={onselectnext}
						>
							<Icon name="skip-forward" size={14} />
						</button>
					</div>
				</div>
			{:else}
				<Breadcrumb items={breadcrumbItems} />
			{/if}
		</div>
	</div>

	<div class="editor-header-actions">
		<div class="editor-views" role="group" aria-label={EDITOR_VIEWS_LABEL}>
			<button
				type="button"
				class="view-toggle"
				data-hitbox="frequent"
				data-hitbox-face
				aria-pressed={coWriterOpen}
				onclick={ontogglecowriter}
			>
				{EDITOR_VIEW_COWRITER_LABEL}
			</button>
			<button
				type="button"
				class="view-toggle"
				data-hitbox="frequent"
				data-hitbox-face
				aria-pressed={recipeOpen}
				onclick={ontogglerecipe}
			>
				{EDITOR_VIEW_RECIPE_LABEL}
			</button>
		</div>
		{#if !compact}
			<span class="editor-header-divider" aria-hidden="true"></span>
			<button
				type="button"
				class="generate-btn"
				class:generating
				onclick={ongenerate}
				disabled={generateDisabled}
				title={generateTitle}
			>
				{generateLabel}
			</button>
		{/if}
	</div>
</div>

{#if compact}
	<div class="editor-generate-bar">
		<button
			type="button"
			class="generate-btn"
			class:generating
			onclick={ongenerate}
			disabled={generateDisabled}
			title={generateTitle}
		>
			{generateLabel}
		</button>
	</div>
{/if}

<style>
	.detail-header {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.55rem;
		min-width: 0;
	}

	.detail-identity {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		min-width: 0;
		flex: 1;
	}

	.cover-hero {
		position: relative;
		width: 4.5rem;
		height: 4.5rem;
		flex-shrink: 0;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.cover-hero img,
	.cover-fallback {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.cover-fallback {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.cover-initials {
		font-family: var(--font-display);
		font-size: 1.1rem;
		letter-spacing: 0.06em;
		user-select: none;
	}

	.cover-file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.cover-hit {
		position: absolute;
		inset: 0;
		padding: 0;
		border: none;
		background: transparent;
		cursor: pointer;
	}

	.cover-hit:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.cover-remove {
		position: absolute;
		top: 0;
		right: 0;
		z-index: 1;
		width: 1.5rem;
		height: 1.5rem;
		padding: 0;
		border: none;
		background: color-mix(in srgb, var(--bg) 75%, transparent);
		color: var(--text);
		font-size: 1rem;
		line-height: 1;
		cursor: pointer;
	}

	.song-heading {
		min-width: 0;
		flex: 1 1 12rem;
	}

	.title-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.song-title {
		font-family: var(--font-display);
		font-size: 1.73rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.13rem;
	}

	.song-rail {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.35rem;
		min-width: 0;
		max-width: 100%;
	}

	.song-rail :global(.breadcrumb) {
		min-width: 0;
		max-width: 100%;
	}

	.song-neighbors {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
	}

	.song-neighbor {
		color: var(--text-muted);
		background: none;
		border: none;
	}

	.song-neighbor:disabled {
		opacity: 0.4;
	}

	.editor-header-actions {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex-shrink: 0;
	}

	.editor-views {
		display: flex;
		gap: 0.4rem;
	}

	.view-toggle {
		padding: 0.4rem 0.8rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.view-toggle:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.view-toggle[aria-pressed='true'] {
		border-color: var(--primary);
		color: var(--primary);
		background: rgba(160, 32, 240, 0.08);
	}

	.editor-header-divider {
		width: 1px;
		align-self: stretch;
		background: var(--border);
	}

	.generate-btn {
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
		transition: box-shadow 0.2s;
	}

	.generate-btn:hover:not(:disabled) {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

	.generate-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	@media (prefers-reduced-motion: no-preference) {
		.generate-btn.generating {
			animation: gen-pulse 1.5s ease-in-out infinite;
		}
	}

	@keyframes gen-pulse {
		0%,
		100% {
			box-shadow: 0 0 6px rgba(160, 32, 240, 0.2);
		}
		50% {
			box-shadow: 0 0 20px rgba(160, 32, 240, 0.4);
		}
	}

	.editor-generate-bar {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--player-height);
		z-index: 30;
		display: flex;
		padding: 0.6rem 0.8rem;
		background: var(--bg);
		border-top: 1px solid var(--border);
	}

	.editor-generate-bar .generate-btn {
		flex: 1;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 6px;
		}

		.cover-hero {
			width: 2.6rem;
			height: 2.6rem;
		}

		.song-title {
			font-size: 1.1rem;
		}

		.song-rail {
			flex-direction: row;
			align-items: center;
			justify-content: space-between;
			gap: 0.5rem;
		}

		.editor-header-actions {
			width: 100%;
			justify-content: flex-end;
		}
	}
</style>
