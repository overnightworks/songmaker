<script lang="ts">
	import { onMount } from 'svelte';
	import {
		HOME_WRITE_LABEL,
		HOME_WRITE_EMPTY,
		HOME_WRITE_LOADING,
		HOME_WRITE_ERROR,
		HOME_WRITE_WORK_LABELS,
		homeWriteOpenLabel,
		songEditorOpenLabel
	} from '#lib/constants.ts';
	import {
		libraryWriteItems,
		libraryWriteState,
		libraryWriteLoading,
		ensureLibraryWriteRead,
		outdateLibraryWrite
	} from '#lib/stores/libraryWrite.ts';
	import { whenBackOnline } from '#lib/stores/connectivity.ts';
	import { selectSong } from '#lib/stores/navigation.ts';
	import { activityTimeLabel } from '#lib/utils/format.ts';
	import LibraryRow from './LibraryRow.svelte';
	import HomeListSection, { homeListPhase } from './HomeListSection.svelte';

	const phase = $derived(homeListPhase($libraryWriteState, $libraryWriteItems.length));

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

<HomeListSection
	label={HOME_WRITE_LABEL}
	loadingText={HOME_WRITE_LOADING}
	errorText={HOME_WRITE_ERROR}
	emptyText={HOME_WRITE_EMPTY}
	{phase}
	busy={$libraryWriteLoading}
	onretry={() => void ensureLibraryWriteRead()}
>
	{#snippet rows()}
		{#each $libraryWriteItems as item (item.song_id)}
			<LibraryRow
				title={item.song_title}
				initialsSource={item.album_title}
				subtitle={`${item.album_title} · ${HOME_WRITE_WORK_LABELS[item.work]} · ${activityTimeLabel(item.worked_at, new Date())}`}
				coverAlt={item.song_title}
				coverUrl={item.cover?.card ?? item.album_cover?.card ?? null}
				openLabel={homeWriteOpenLabel(item.song_title)}
				onopen={() => void selectSong(item.song_id)}
				edit={{
					label: songEditorOpenLabel(item.song_title),
					onclick: () => void selectSong(item.song_id)
				}}
			/>
		{/each}
	{/snippet}
</HomeListSection>
