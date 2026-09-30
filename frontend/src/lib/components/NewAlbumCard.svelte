<script lang="ts">
	import { onMount } from 'svelte';
	import { createAlbum } from '$lib/api/client';
	import { addAlbumToList } from '$lib/stores/libraryData';
	import { openAlbum } from '$lib/stores/navigation';
	import {
		NEW_ALBUM_ARTIST_LABEL,
		NEW_ALBUM_ARTIST_OPTIONAL,
		NEW_ALBUM_CARD_LABEL,
		NEW_ALBUM_CLOSE_LABEL,
		NEW_ALBUM_FAILED,
		NEW_ALBUM_HINT,
		NEW_ALBUM_TITLE_LABEL,
		NEW_PLACE_TEXT_MAX_LENGTH
	} from '$lib/constants';
	import NewPlaceCard from './NewPlaceCard.svelte';

	interface Props {
		oncancel: () => void;
		oncreated: () => void;
	}

	let { oncancel, oncreated }: Props = $props();

	let title = $state('');
	let artist = $state('');
	let titleInput: HTMLInputElement | undefined = $state();

	onMount(() => titleInput?.focus());

	async function createListedAlbum(): Promise<string> {
		const album = await createAlbum(title.trim(), artist.trim());
		addAlbumToList(album);
		return album.id;
	}
</script>

<NewPlaceCard
	label={NEW_ALBUM_CARD_LABEL}
	closeLabel={NEW_ALBUM_CLOSE_LABEL}
	hint={NEW_ALBUM_HINT}
	failedMessage={NEW_ALBUM_FAILED}
	ready={title.trim() !== ''}
	create={createListedAlbum}
	open={openAlbum}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{NEW_ALBUM_TITLE_LABEL}</span>
		<input
			bind:this={titleInput}
			bind:value={title}
			type="text"
			autocomplete="off"
			maxlength={NEW_PLACE_TEXT_MAX_LENGTH}
			required
		/>
	</label>
	<label class="field">
		<span class="field-label">{NEW_ALBUM_ARTIST_LABEL} <em>{NEW_ALBUM_ARTIST_OPTIONAL}</em></span>
		<input
			bind:value={artist}
			type="text"
			autocomplete="off"
			maxlength={NEW_PLACE_TEXT_MAX_LENGTH}
			placeholder={NEW_ALBUM_ARTIST_LABEL}
		/>
	</label>
</NewPlaceCard>
