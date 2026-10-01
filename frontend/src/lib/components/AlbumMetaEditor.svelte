<script module lang="ts">
	export interface AlbumDetails {
		title: string;
		subtitle: string;
		year: string;
	}
</script>

<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import {
		ALBUM_DETAILS_CLOSE_LABEL,
		ALBUM_DETAILS_SAVE_LABEL,
		ALBUM_SUBTITLE_LABEL,
		ALBUM_SUBTITLE_MAX_LENGTH,
		ALBUM_TITLE_LABEL,
		ALBUM_TITLE_MAX_LENGTH,
		ALBUM_YEAR_LABEL,
		ALBUM_YEAR_MAX_LENGTH,
		COLLECTION_MENU_EDIT_DETAILS_LABEL
	} from '$lib/constants';
	import Icon from './Icon.svelte';

	interface Props {
		details: AlbumDetails;
		/** Saves the edited details; rejects, having named the reason, when the save is refused. */
		onsave: (details: AlbumDetails) => Promise<void>;
		onclose: () => void;
	}

	let { details, onsave, onclose }: Props = $props();

	// A draft of the details the form opened on: nothing reaches the album
	// before Save, so closing the form is all it takes to discard it.
	const draft: AlbumDetails = $state(untrack(() => ({ ...details })));
	let saving = $state(false);
	let titleInput: HTMLInputElement | undefined = $state();

	const canSave = $derived(draft.title.trim() !== '' && !saving);

	onMount(() => titleInput?.focus());

	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!canSave) return;
		saving = true;
		try {
			await onsave({
				title: draft.title.trim(),
				subtitle: draft.subtitle.trim(),
				year: draft.year.trim()
			});
		} catch {
			// The refusal is already named to the musician; the draft stays to fix.
			saving = false;
			return;
		}
		onclose();
	}
</script>

<form class="album-details" aria-label={COLLECTION_MENU_EDIT_DETAILS_LABEL} onsubmit={save}>
	<div class="details-head">
		<span class="details-title">{COLLECTION_MENU_EDIT_DETAILS_LABEL}</span>
		<button type="button" class="close-btn" aria-label={ALBUM_DETAILS_CLOSE_LABEL} onclick={onclose}>
			<Icon name="x" size={18} />
		</button>
	</div>
	<label class="field">
		<span class="field-label">{ALBUM_TITLE_LABEL}</span>
		<input
			bind:this={titleInput}
			bind:value={draft.title}
			type="text"
			autocomplete="off"
			maxlength={ALBUM_TITLE_MAX_LENGTH}
			required
		/>
	</label>
	<label class="field">
		<span class="field-label">{ALBUM_SUBTITLE_LABEL}</span>
		<input bind:value={draft.subtitle} type="text" autocomplete="off" maxlength={ALBUM_SUBTITLE_MAX_LENGTH} />
	</label>
	<label class="field field-year">
		<span class="field-label">{ALBUM_YEAR_LABEL}</span>
		<input
			bind:value={draft.year}
			type="text"
			inputmode="numeric"
			autocomplete="off"
			maxlength={ALBUM_YEAR_MAX_LENGTH}
		/>
	</label>
	<div class="details-foot">
		<button type="submit" class="save-btn" disabled={!canSave}>{ALBUM_DETAILS_SAVE_LABEL}</button>
	</div>
</form>

<style>
	.album-details {
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
		padding: 12px;
		border: 1px solid var(--accent);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.details-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin: -6px -6px -4px 0;
	}

	.details-title {
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
		min-width: 0;
	}

	.field-label {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.field input {
		min-width: 0;
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

	.field-year input {
		max-width: 6rem;
	}

	.details-foot {
		display: flex;
		justify-content: flex-end;
	}

	.save-btn {
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

	.save-btn:disabled {
		border-color: var(--border);
		background: none;
		color: var(--text-disabled);
		cursor: default;
	}

	@media (max-width: 768px) {
		.close-btn,
		.save-btn {
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
