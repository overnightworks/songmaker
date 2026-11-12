<script lang="ts">
	import { onMount } from 'svelte';
	import { openPlaylist } from '#lib/stores/navigation.ts';
	import { createNewPlaylist } from '#lib/stores/playlists.ts';
	import { NEW_PLACE_TEXT_MAX_LENGTH } from '#lib/constants/new-collection.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import NewPlaceCard from './NewPlaceCard.svelte';

	interface Props {
		oncancel: () => void;
		oncreated: () => void;
	}

	let { oncancel, oncreated }: Props = $props();

	let name = $state('');
	let nameInput: HTMLInputElement | undefined = $state();

	onMount(() => nameInput?.focus());

	async function createListedPlaylist(): Promise<string> {
		const playlist = await createNewPlaylist(name.trim());
		return playlist.id;
	}
</script>

<NewPlaceCard
	label={pageText('newPlaylist.cardLabel')}
	closeLabel={pageText('newPlaylist.close')}
	hint={pageText('newPlaylist.hint')}
	failedMessage={pageText('newPlaylist.failed')}
	refusedMessage={pageText('newPlaylist.refused')}
	draftKey="playlist"
	bind:title={name}
	ready={name.trim() !== ''}
	create={createListedPlaylist}
	open={openPlaylist}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{pageText('newPlaylist.nameLabel')}</span>
		<input
			bind:this={nameInput}
			bind:value={name}
			type="text"
			autocomplete="off"
			maxlength={NEW_PLACE_TEXT_MAX_LENGTH}
			required
		/>
	</label>
</NewPlaceCard>
