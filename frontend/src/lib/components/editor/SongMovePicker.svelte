<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_RETRY_LABEL,
		SONG_MOVE_BACK_LABEL,
		SONG_MOVE_FILTER_LABEL,
		SONG_MOVE_FILTER_PLACEHOLDER,
		SONG_MOVE_HEADING,
		SONG_MOVE_LOADING_LABEL,
		SONG_MOVE_NO_MATCH,
		SONG_MOVE_NO_OTHER_ALBUM
	} from '#lib/constants.ts';
	import type { AlbumItem } from '#lib/api/types.ts';
	import {
		closeSongMovePicker,
		askToMoveOpenSongTo,
		openSongMovePicker,
		songMoveFilter,
		songMovePicker
	} from '#lib/stores/songMove.ts';
	import { titleInitials } from '#lib/utils/format.ts';
	import Icon from '../Icon.svelte';

	interface Props {
		/** Closes the whole popover once a move has been asked for. */
		onmoved: () => void;
	}

	let { onmoved }: Props = $props();

	let backButton: HTMLButtonElement | undefined = $state();
	let filterInput: HTMLInputElement | undefined = $state();
	let filterFocused = false;

	onMount(() => backButton?.focus());
	onDestroy(closeSongMovePicker);

	// The filter appears with the list, after the focus already stands on Back.
	$effect(() => {
		if (filterInput && !filterFocused) {
			filterFocused = true;
			filterInput.focus();
		}
	});

	function choose(album: AlbumItem): void {
		onmoved();
		void askToMoveOpenSongTo(album);
	}
</script>

{#snippet albumFace(album: AlbumItem)}
	<span class="pk-art">
		{#if album.cover?.card}
			<img src={album.cover.card} alt={`${ALBUM_COVER_ALT_TYPE} ${album.title}`} />
		{:else}
			<span aria-hidden="true">{titleInitials(album.title)}</span>
		{/if}
	</span>
	<span class="pk-title">{album.title}</span>
	{#if album.is_shared}<Icon name="share" size={14} class="pk-shared" />{/if}
{/snippet}

<div class="pk-head">
	<button
		bind:this={backButton}
		type="button"
		class="pk-back"
		aria-label={SONG_MOVE_BACK_LABEL}
		onclick={closeSongMovePicker}
	>
		<Icon name="chevron-right" size={16} class="pk-back-icon" />
	</button>
	{SONG_MOVE_HEADING}
</div>

{#if $songMovePicker.status === 'ready'}
	{@const picker = $songMovePicker}
	{#if picker.hasOthers}
		<input
			bind:this={filterInput}
			bind:value={$songMoveFilter}
			class="pk-filter"
			type="search"
			aria-label={SONG_MOVE_FILTER_LABEL}
			placeholder={SONG_MOVE_FILTER_PLACEHOLDER}
		/>
	{/if}
	{#if picker.current}
		<div class="pk-row here" aria-current="true">
			{@render albumFace(picker.current)}
			<Icon name="check" size={16} class="pk-check" />
		</div>
	{/if}
	{#if picker.hasOthers}
		<ul class="pk-list">
			{#each picker.others as album (album.id)}
				<li>
					<button type="button" class="pk-row" onclick={() => choose(album)}>
						{@render albumFace(album)}
						<span class="pk-count">{album.song_count}</span>
					</button>
				</li>
			{/each}
		</ul>
		{#if picker.others.length === 0}
			<p class="pk-empty">{SONG_MOVE_NO_MATCH}</p>
		{/if}
	{:else}
		<p class="pk-empty">{SONG_MOVE_NO_OTHER_ALBUM}</p>
	{/if}
{:else if $songMovePicker.status === 'failed'}
	<div class="pk-error" role="alert">
		<Icon name="circle-alert" size={16} />
		<span>{$songMovePicker.message}</span>
		<button type="button" class="pk-retry" onclick={() => void openSongMovePicker()}>
			{LIBRARY_RETRY_LABEL}
		</button>
	</div>
{:else}
	<p class="pk-status" role="status">{SONG_MOVE_LOADING_LABEL}</p>
{/if}

<style>
	.pk-head {
		display: flex;
		align-items: center;
		gap: 2px;
		margin-bottom: 0.25rem;
		padding: 0 0.6rem 0.3rem 0;
		border-bottom: 1px solid var(--border);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
	}

	.pk-back {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		background: none;
		border: none;
		border-radius: var(--btn-radius-sm);
		color: var(--text);
		cursor: pointer;
	}

	.pk-back:hover {
		background: var(--surface-hover);
	}

	.pk-back :global(.pk-back-icon) {
		transform: rotate(180deg);
	}

	.pk-filter {
		min-height: var(--hitbox-frequent);
		margin: 2px 0 4px;
		padding: 0 0.6rem;
		font: inherit;
		font-size: var(--label-font-size);
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
	}

	.pk-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
		max-height: 268px;
		overflow-y: auto;
	}

	.pk-row {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: var(--hitbox-frequent);
		padding: 0 0.6rem;
		border: none;
		border-radius: var(--btn-radius-sm);
		background: none;
		font: inherit;
		font-size: var(--label-font-size);
		color: var(--text);
		text-align: left;
	}

	button.pk-row {
		cursor: pointer;
	}

	button.pk-row:hover {
		background: var(--surface-hover);
	}

	.pk-row.here {
		background: color-mix(in srgb, var(--accent) 8%, transparent);
		border-left: 3px solid var(--accent);
		margin-bottom: 4px;
	}

	.pk-art {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		flex: 0 0 28px;
		overflow: hidden;
		border-radius: var(--btn-radius-sm);
		background: var(--surface-hover);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.04em;
	}

	.pk-art img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.pk-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pk-row :global(.pk-shared),
	.pk-row :global(.pk-check) {
		flex: none;
		color: var(--accent);
	}

	.pk-count {
		flex: none;
		min-width: 16px;
		font-size: 0.75rem;
		color: var(--text-subtle);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.pk-status,
	.pk-empty {
		margin: 0;
		padding: 0.6rem;
		font-size: var(--label-font-size);
		color: var(--text-subtle);
	}

	.pk-empty {
		font-style: italic;
	}

	.pk-error {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 0.4rem 2px 0.6rem;
		font-size: var(--label-font-size);
		color: var(--score-bad);
	}

	.pk-error span {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.pk-retry {
		flex: none;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
		font: inherit;
		font-size: 0.75rem;
		cursor: pointer;
	}
</style>
