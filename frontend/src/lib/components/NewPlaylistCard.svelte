<script lang="ts">
	import { onMount } from 'svelte';
	import { openPlaylist } from '$lib/stores/navigation';
	import { createNewPlaylist } from '$lib/stores/playlists';
	import {
		NEW_PLACE_TEXT_MAX_LENGTH,
		NEW_PLAYLIST_CARD_LABEL,
		NEW_PLAYLIST_CLOSE_LABEL,
		NEW_PLAYLIST_FAILED,
		NEW_PLAYLIST_HINT,
		NEW_PLAYLIST_NAME_LABEL
	} from '$lib/constants';
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
	label={NEW_PLAYLIST_CARD_LABEL}
	closeLabel={NEW_PLAYLIST_CLOSE_LABEL}
	hint={NEW_PLAYLIST_HINT}
	failedMessage={NEW_PLAYLIST_FAILED}
	ready={name.trim() !== ''}
	create={createListedPlaylist}
	open={openPlaylist}
	{oncancel}
	{oncreated}
>
	<label class="field">
		<span class="field-label">{NEW_PLAYLIST_NAME_LABEL}</span>
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
