<script lang="ts">
	import { onMount } from 'svelte';
	import type { AlbumItem } from '$lib/api/types';
	import { createSong } from '$lib/api/client';
	import { addSongToList } from '$lib/stores/libraryData';
	import { selectSong } from '$lib/stores/navigation';
	import {
		NEW_PLACE_TEXT_MAX_LENGTH,
		NEW_SONG_CLOSE_LABEL,
		NEW_SONG_FAILED,
		NEW_SONG_HINT,
		NEW_SONG_TITLE_LABEL,
		newSongCardLabel
	} from '$lib/constants';
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
	label={newSongCardLabel(album.title)}
	closeLabel={NEW_SONG_CLOSE_LABEL}
	hint={NEW_SONG_HINT}
	failedMessage={NEW_SONG_FAILED}
	ready={title.trim() !== ''}
	create={createListedSong}
	open={openSong}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{NEW_SONG_TITLE_LABEL}</span>
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
