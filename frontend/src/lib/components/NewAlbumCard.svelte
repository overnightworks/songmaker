<script lang="ts">
	import { onMount } from 'svelte';
	import { createAlbum } from '$lib/api/client';
	import type { AlbumItem } from '$lib/api/types';
	import { describeFailure } from '$lib/api/fetch';
	import { addAlbumToList } from '$lib/stores/libraryData';
	import { openAlbum } from '$lib/stores/navigation';
	import { addToast } from '$lib/stores/toast';
	import {
		NEW_ALBUM_ARTIST_LABEL,
		NEW_ALBUM_ARTIST_OPTIONAL,
		NEW_ALBUM_CARD_LABEL,
		NEW_ALBUM_CLOSE_LABEL,
		NEW_ALBUM_CREATE_LABEL,
		NEW_ALBUM_FAILED,
		NEW_ALBUM_HINT,
		NEW_ALBUM_TITLE_LABEL
	} from '$lib/constants';
	import Icon from './Icon.svelte';

	interface Props {
		oncancel: () => void;
		oncreated: () => void;
	}

	let { oncancel, oncreated }: Props = $props();

	let title = $state('');
	let artist = $state('');
	let creating = $state(false);
	let titleInput: HTMLInputElement | undefined = $state();

	const canCreate = $derived(title.trim() !== '' && !creating);

	onMount(() => titleInput?.focus());

	async function create(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!canCreate) return;
		creating = true;
		let album: AlbumItem;
		try {
			album = await createAlbum(title.trim(), artist.trim());
		} catch (err) {
			addToast(describeFailure(err, NEW_ALBUM_FAILED), 'error');
			creating = false;
			return;
		}
		addAlbumToList(album);
		oncreated();
		await openAlbum(album.id);
	}
</script>

<form class="new-album" aria-label={NEW_ALBUM_CARD_LABEL} onsubmit={create}>
	<div class="card-head">
		<span class="card-title">{NEW_ALBUM_CARD_LABEL}</span>
		<button type="button" class="close-btn" aria-label={NEW_ALBUM_CLOSE_LABEL} onclick={oncancel}>
			<Icon name="x" size={18} />
		</button>
	</div>
	<label class="field">
		<span class="field-label">{NEW_ALBUM_TITLE_LABEL}</span>
		<input bind:this={titleInput} bind:value={title} type="text" autocomplete="off" required />
	</label>
	<label class="field">
		<span class="field-label">{NEW_ALBUM_ARTIST_LABEL} <em>{NEW_ALBUM_ARTIST_OPTIONAL}</em></span>
		<input bind:value={artist} type="text" autocomplete="off" />
	</label>
	<div class="card-foot">
		<small>{NEW_ALBUM_HINT}</small>
		<button type="submit" class="create-btn" disabled={!canCreate}>{NEW_ALBUM_CREATE_LABEL}</button>
	</div>
</form>

<style>
	.new-album {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-bottom: 12px;
		padding: 12px;
		border: 1px solid var(--accent);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.card-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin: -6px -6px -4px 0;
	}

	.card-title {
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.85rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.close-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		padding: 0;
		border: 0;
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
	}

	.close-btn:hover {
		color: var(--text);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}

	.field-label {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.field-label em {
		color: var(--text-subtle);
		font-family: var(--font-body);
		font-style: normal;
		letter-spacing: 0;
		text-transform: none;
	}

	.field input {
		height: 40px;
		padding: 0 12px;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--bg);
		color: var(--text);
		font-family: var(--font-body);
		font-size: 15px;
	}

	.field input:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}

	.card-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

	.card-foot small {
		color: var(--text-subtle);
		font-size: 0.75rem;
		line-height: 1.35;
	}

	.create-btn {
		flex: none;
		height: 32px;
		padding: 0 20px;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: var(--accent);
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.78rem;
		font-weight: 500;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.create-btn:disabled {
		border-color: var(--border);
		background: none;
		color: var(--text-disabled);
		cursor: default;
	}

	@media (max-width: 768px) {
		.close-btn,
		.create-btn {
			height: 44px;
		}

		.close-btn {
			width: 44px;
		}

		.field input {
			height: 52px;
		}
	}
</style>
