<script lang="ts">
	import {
		draftLoadedFrom,
		editLyrics,
		editPrompt,
		setDraftLyrics,
		setDraftPrompt
	} from '$lib/stores/editor';
	import { getGenerationActions } from '$lib/contexts/generation-actions';
	import type { SongItem } from '$lib/api/types';
	import {
		EDITOR_LYRICS_LABEL,
		EDITOR_STYLE_PROMPT_LABEL,
		versionLoadedFromLabel
	} from '$lib/constants';
	import Icon from '../Icon.svelte';
	import GrowingTextarea from './GrowingTextarea.svelte';
	import VersionsSheet from './VersionsSheet.svelte';

	interface Props {
		song: SongItem;
	}

	let { song }: Props = $props();

	const lyricsFieldId = $props.id();
	const generationActions = getGenerationActions();

	function loadVersion(versionId: string): Promise<boolean> {
		return generationActions.clickVersion(versionId);
	}
</script>

<div class="write-mode">
	<label class="edit-field">
		<span>{EDITOR_STYLE_PROMPT_LABEL}</span>
		<GrowingTextarea value={$editPrompt} oninput={setDraftPrompt} minimumLines={4} />
	</label>
	<div class="edit-field">
		<span>
			<label for={lyricsFieldId}>{EDITOR_LYRICS_LABEL}</label>
			<VersionsSheet {song} onload={loadVersion} />
		</span>
		{@render loadedFromHint()}
		<GrowingTextarea
			id={lyricsFieldId}
			class="lyrics-area"
			value={$editLyrics}
			oninput={setDraftLyrics}
			minimumLines={15}
			monospace
		/>
	</div>
</div>

{#snippet loadedFromHint()}
	{#if $draftLoadedFrom !== null}
		<span class="loaded-hint">
			<Icon name="refresh-cw" size={13} />
			{versionLoadedFromLabel($draftLoadedFrom)}
		</span>
	{/if}
{/snippet}

<style>
	.write-mode {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.edit-field {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.edit-field > span:first-child {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.loaded-hint {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		margin-top: -0.1rem;
		font-size: 0.74rem;
		color: var(--text-subtle);
	}
</style>
