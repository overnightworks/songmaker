<script lang="ts">
	import { onMount } from 'svelte';
	import type { AlbumItem } from '#lib/api/types.ts';
	import { createSong } from '#lib/api/client.ts';
	import { addSongToList } from '#lib/stores/libraryData.ts';
	import { selectSong } from '#lib/stores/navigation.ts';
	import { NEW_PLACE_TEXT_MAX_LENGTH } from '#lib/constants/new-collection.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import NewPlaceCard from './NewPlaceCard.svelte';

	interface Props {
		album: AlbumItem;
		oncancel: () => void;
		oncreated: () => void;
	}

	let { album, oncancel, oncreated }: Props = $props();

	let title = $state('');
	let titleInput: HTMLInputElement | undefined = $state();

	onMount(() => titleInput?.focus());

	async function createListedSong(): Promise<string> {
		const song = await createSong({ title: title.trim(), album_id: album.id });
		addSongToList(song);
		return song.id;
	}

	function openSong(id: string): Promise<void> {
		return selectSong(id);
	}
</script>

<NewPlaceCard
	label={pageText('newSong.cardLabel', { album: album.title })}
	closeLabel={pageText('newSong.close')}
	hint={pageText('newSong.hint')}
	failedMessage={pageText('newSong.failed')}
	refusedMessage={pageText('newSong.refused')}
	draftKey={`song:${album.id}`}
	bind:title
	ready={title.trim() !== ''}
	create={createListedSong}
	open={openSong}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{pageText('newSong.titleLabel')}</span>
		<input
			bind:this={titleInput}
			bind:value={title}
			type="text"
			autocomplete="off"
			maxlength={NEW_PLACE_TEXT_MAX_LENGTH}
			required
		/>
	</label>
</NewPlaceCard>
