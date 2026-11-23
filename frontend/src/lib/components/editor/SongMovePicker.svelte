<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { AlbumItem, SongItem } from '#lib/api/types.ts';
	import {
		closeSongMovePicker,
		askToMoveSongTo,
		openSongMovePicker,
		retrySongMove,
		songMoveFilter,
		songMovePicker,
		songMoveRun,
		songMoveRunHere
	} from '#lib/stores/songMove.ts';
	import { titleInitials } from '#lib/utils/format.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from '../Icon.svelte';
	import MenuPickerHead from '../MenuPickerHead.svelte';

	interface Props {
		/** The song the picker moves. */
		song: SongItem;
		/** Closes the whole popover, as a move lands or before a shared album asks. */
		onclose: () => void;
	}

	let { song, onclose }: Props = $props();

	let filterInput: HTMLInputElement | undefined = $state();
	let filterFocused = false;

	onDestroy(closeSongMovePicker);

	// The filter appears with the list, after the focus already stands on Back.
	$effect(() => {
		if (filterInput && !filterFocused) {
			filterFocused = true;
			filterInput.focus();
		}
	});

	async function choose(album: AlbumItem): Promise<void> {
		// The ask is a dialog over the page: it opens only after the popover's history layer left.
		if (album.is_shared) onclose();
		await askToMoveSongTo(song, album, onclose);
	}

	async function retry(): Promise<void> {
		await retrySongMove(onclose);
	}
</script>

{#snippet albumFace(album: AlbumItem)}
	<span class="pk-art">
		{#if album.cover?.card}
			<img src={album.cover.card} alt={pageText('songMove.albumCover', { title: album.title })} />
		{:else}
			<span aria-hidden="true">{titleInitials(album.title)}</span>
		{/if}
	</span>
	<span class="pk-title">{album.title}</span>
	{#if album.is_shared}<Icon name="share" size={14} class="pk-shared" />{/if}
{/snippet}

<MenuPickerHead
	label={pageText('songMove.back')}
	heading={pageText('songMove.heading')}
	onback={closeSongMovePicker}
	disabled={$songMoveRun.status === 'busy'}
/>

{#if $songMovePicker.status === 'ready'}
	{@const picker = $songMovePicker}
	{#if picker.hasOthers}
		<input
			bind:this={filterInput}
			bind:value={$songMoveFilter}
			disabled={$songMoveRun.status === 'busy'}
			class="pk-filter"
			type="search"
			aria-label={pageText('songMove.filterLabel')}
			placeholder={pageText('songMove.filterPlaceholder')}
		/>
	{/if}
	{#if picker.current}
		<div class="menu-picker-row pk-row here" aria-current="true">
			{@render albumFace(picker.current)}
			<Icon name="check" size={16} class="pk-check" />
		</div>
	{/if}
	{#if picker.hasOthers}
		<ul class="menu-picker-list pk-list">
			{#each picker.others as album (album.id)}
				{@const run = $songMoveRunHere}
				{@const busy = run.status === 'busy' && run.albumId === album.id}
				{@const failed = run.status === 'failed' && run.albumId === album.id}
				<li>
					<button
						type="button"
						class="menu-picker-row pk-row"
						class:busy
						class:failed
						aria-busy={busy ? 'true' : undefined}
						disabled={$songMoveRun.status === 'busy' && !busy}
						onclick={() => void choose(album)}
					>
						{@render albumFace(album)}
						{#if busy}
							<span class="pk-spin ring-turn" aria-hidden="true"></span>
							<span class="pk-run" aria-hidden="true"></span>
						{:else if failed}
							<Icon name="circle-alert" size={16} class="pk-warn" />
						{:else}
							<span class="pk-count">{album.song_count}</span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
		{#if picker.others.length === 0}
			<p class="pk-empty">{pageText('songMove.noMatch')}</p>
		{/if}
	{:else}
		<p class="pk-empty">{pageText('songMove.noOtherAlbum')}</p>
	{/if}
	{#if $songMoveRunHere.status === 'failed'}
		<div class="pk-error pk-move-error" role="alert">
			<Icon name="circle-alert" size={16} />
			<span>{$songMoveRunHere.line}</span>
			{#if $songMoveRunHere.retryable}
				<button type="button" class="pk-retry" onclick={() => void retry()}>
					{pageText('songMove.retry')}
				</button>
			{/if}
		</div>
	{/if}
{:else if $songMovePicker.status === 'failed'}
	<div class="pk-error" role="alert">
		<Icon name="circle-alert" size={16} />
		<span>{$songMovePicker.message}</span>
		<button type="button" class="pk-retry" onclick={() => void openSongMovePicker(song)}>
			{pageText('songMove.retry')}
		</button>
	</div>
{:else}
	<p class="pk-status" role="status">{pageText('songMove.loading')}</p>
{/if}

<style>
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
		position: relative;
	}

	button.pk-row:disabled {
		cursor: default;
		opacity: 0.45;
	}

	button.pk-row.busy {
		position: relative;
		opacity: 1;
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}

	button.pk-row.failed {
		border-left: 3px solid var(--fail);
	}

	.pk-row :global(.pk-warn) {
		flex: none;
		color: var(--fail);
	}

	.pk-spin {
		flex: none;
		width: 16px;
		height: 16px;
		border: 2px solid color-mix(in srgb, var(--accent) 25%, transparent);
		border-top-color: var(--accent);
		border-radius: 50%;
		--ring-turn: 0.9s;
	}

	.pk-run {
		position: absolute;
		left: 0;
		bottom: 0;
		width: 40%;
		height: 2px;
		background: var(--accent);
		animation: pk-run 1.2s ease-in-out infinite;
	}

	@keyframes pk-run {
		from {
			left: -40%;
		}
		to {
			left: 100%;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.pk-run {
			animation: none;
			left: 0;
			width: 100%;
			opacity: 0.5;
		}
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

	.pk-move-error {
		margin-top: 4px;
		border-top: 1px solid var(--border);
	}

	.pk-error {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 0.4rem 2px 0.6rem;
		font-size: var(--label-font-size);
		color: var(--fail);
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
		border: 1px solid var(--accent);
		color: var(--accent);
		font: inherit;
		font-size: 0.75rem;
		cursor: pointer;
	}
</style>
