<script lang="ts">
	import { onMount } from 'svelte';
	import { songEditorOpenLabel } from '#lib/constants/song.ts';
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
	import { pageText } from '#lib/utils/page-words.ts';
	import type { LibraryWriteItem } from '#lib/api/types.ts';
	import type { Key } from '#lib/words/en.ts';
	import LibraryRow from './LibraryRow.svelte';
	import HomeListSection, { homeListPhase } from './HomeListSection.svelte';

	const WORK_KEYS = {
		created: 'homeWrite.workCreated',
		lyrics: 'homeWrite.workLyrics',
		style: 'homeWrite.workStyle',
		renamed: 'homeWrite.workRenamed',
		take: 'homeWrite.workTake',
		cowriter: 'homeWrite.workCowriter',
		edited: 'homeWrite.workEdited'
	} as const satisfies Record<LibraryWriteItem['work'], Key>;

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
	label={pageText('homeWrite.label')}
	loadingText={pageText('homeWrite.loading')}
	errorText={pageText('homeWrite.error')}
	emptyText={pageText('homeWrite.empty')}
	{phase}
	busy={$libraryWriteLoading}
	onretry={() => void ensureLibraryWriteRead()}
>
	{#snippet rows()}
		{#each $libraryWriteItems as item (item.song_id)}
			<LibraryRow
				title={item.song_title}
				initialsSource={item.album_title}
				subtitleYielding={item.album_title}
				subtitle={pageText(WORK_KEYS[item.work], {
					time: activityTimeLabel(item.worked_at, new Date())
				})}
				coverAlt={item.song_title}
				coverUrl={item.cover?.card ?? item.album_cover?.card ?? null}
				// The row body and its pencil both open the editor; distinct names keep them apart for a screen reader.
				openLabel={pageText('homeWrite.openSong', { title: item.song_title })}
				onopen={() => void selectSong(item.song_id)}
				edit={{
					label: songEditorOpenLabel(item.song_title),
					onclick: () => void selectSong(item.song_id)
				}}
			/>
		{/each}
	{/snippet}
</HomeListSection>
