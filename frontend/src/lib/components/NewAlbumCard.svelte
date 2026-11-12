<script lang="ts">
	import { onMount } from 'svelte';
	import { createAlbum } from '#lib/api/client.ts';
	import { addAlbumToList } from '#lib/stores/libraryData.ts';
	import { openAlbum } from '#lib/stores/navigation.ts';
	import { NEW_PLACE_TEXT_MAX_LENGTH } from '#lib/constants/new-collection.ts';
	import { pageText } from '#lib/utils/page-words.ts';
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
	label={pageText('newAlbum.cardLabel')}
	closeLabel={pageText('newAlbum.close')}
	hint={pageText('newAlbum.hint')}
	failedMessage={pageText('newAlbum.failed')}
	refusedMessage={pageText('newAlbum.refused')}
	draftKey="album"
	bind:title
	ready={title.trim() !== ''}
	create={createListedAlbum}
	open={openAlbum}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{pageText('newAlbum.titleLabel')}</span>
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
		<span class="field-label"
			>{pageText('newAlbum.artistLabel')} <em>{pageText('newAlbum.artistOptional')}</em></span
		>
		<input
			bind:value={artist}
			type="text"
			autocomplete="off"
			maxlength={NEW_PLACE_TEXT_MAX_LENGTH}
			placeholder={pageText('newAlbum.artistLabel')}
		/>
	</label>
</NewPlaceCard>
