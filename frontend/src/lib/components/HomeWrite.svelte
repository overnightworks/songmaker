<script lang="ts">
	import { onMount } from 'svelte';
	import {
		HOME_WRITE_LABEL,
		HOME_WRITE_EMPTY,
		HOME_WRITE_LOADING,
		HOME_WRITE_ERROR,
		HOME_WRITE_WORK_LABELS,
		LIBRARY_RETRY_LABEL,
		songEditorOpenLabel
	} from '$lib/constants';
	import {
		libraryWriteItems,
		libraryWriteState,
		libraryWriteLoading,
		ensureLibraryWriteRead,
		outdateLibraryWrite
	} from '$lib/stores/libraryWrite';
	import { whenBackOnline } from '$lib/stores/connectivity';
	import { selectSong } from '$lib/stores/navigation';
	import { activityTimeLabel } from '$lib/utils/format';
	import LibraryRow from './LibraryRow.svelte';

	function refresh(): void {
		outdateLibraryWrite();
		void ensureLibraryWriteRead();
	}

	onMount(() => {
		void ensureLibraryWriteRead();
		return whenBackOnline(refresh);
	});

	function foreground(): void {
		if (document.visibilityState === 'visible') refresh();
	}
</script>

<svelte:document onvisibilitychange={foreground} />

<section class="home-write" aria-label={HOME_WRITE_LABEL} aria-busy={$libraryWriteLoading}>
	<h2>{HOME_WRITE_LABEL}</h2>
	{#if $libraryWriteState === 'unread'}
		<p role="status">{HOME_WRITE_LOADING}</p>
	{:else if $libraryWriteState === 'failed'}
		<div class="write-error" role="alert">
			<p>{HOME_WRITE_ERROR}</p>
			<button
				type="button"
				disabled={$libraryWriteLoading}
				onclick={() => void ensureLibraryWriteRead()}>{LIBRARY_RETRY_LABEL}</button
			>
		</div>
	{:else if $libraryWriteItems.length === 0}
		<p>{HOME_WRITE_EMPTY}</p>
	{:else}
		{#each $libraryWriteItems as item (item.song_id)}
			<LibraryRow
				title={item.song_title}
				subtitle={`${item.album_title} · ${HOME_WRITE_WORK_LABELS[item.work]} · ${activityTimeLabel(item.worked_at, new Date())}`}
				coverAlt={item.song_title}
				coverUrl={item.cover?.card ?? item.album_cover?.card ?? null}
				openLabel={songEditorOpenLabel(item.song_title)}
				onopen={() => void selectSong(item.song_id)}
				onedit={() => void selectSong(item.song_id)}
			/>
		{/each}
	{/if}
</section>

<style>
	.home-write {
		padding: 12px 20px;
	}
	h2 {
		margin: 0 0 8px;
		font-size: 13px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
	}
	p {
		margin: 0;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
	}
	.write-error {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	button {
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		padding: 4px 8px;
		cursor: pointer;
	}
	@media (max-width: 768px) {
		.home-write {
			padding: 12px;
		}
	}
</style>
