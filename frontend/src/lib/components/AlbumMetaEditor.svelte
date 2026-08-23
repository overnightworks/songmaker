<script lang="ts">
	import EditableTitle from './EditableTitle.svelte';
	import {
		ALBUM_SUBTITLE_LABEL,
		ALBUM_SUBTITLE_MAX_LENGTH,
		ALBUM_SUBTITLE_PLACEHOLDER,
		ALBUM_YEAR_LABEL,
		ALBUM_YEAR_MAX_LENGTH,
		ALBUM_YEAR_PLACEHOLDER
	} from '$lib/constants';

	interface Props {
		subtitle: string;
		year: string;
		onsavesubtitle: (subtitle: string) => Promise<void>;
		onsaveyear: (year: string) => Promise<void>;
	}

	let { subtitle, year, onsavesubtitle, onsaveyear }: Props = $props();
</script>

<p class="album-meta">
	<span class="album-meta-field album-meta-subtitle">
		<EditableTitle
			value={subtitle}
			onsave={onsavesubtitle}
			ariaLabel={ALBUM_SUBTITLE_LABEL}
			allowEmpty
			placeholder={ALBUM_SUBTITLE_PLACEHOLDER}
			maxlength={ALBUM_SUBTITLE_MAX_LENGTH}
		/>
	</span>
	<span class="album-meta-sep" aria-hidden="true">·</span>
	<span class="album-meta-field album-meta-year">
		<EditableTitle
			value={year}
			onsave={onsaveyear}
			ariaLabel={ALBUM_YEAR_LABEL}
			allowEmpty
			placeholder={ALBUM_YEAR_PLACEHOLDER}
			maxlength={ALBUM_YEAR_MAX_LENGTH}
			inputmode="numeric"
		/>
	</span>
</p>

<style>
	.album-meta {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		margin: 0.15rem 0 0;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.album-meta-field {
		display: inline-block;
		flex: 0 1 auto;
		min-width: 0;
	}

	.album-meta-field :global(.editable-title-input) {
		width: auto;
	}

	.album-meta-subtitle :global(.editable-title-input) {
		min-width: 8rem;
		max-width: 22rem;
	}

	.album-meta-year :global(.editable-title-input) {
		min-width: 3.5rem;
		max-width: 5rem;
	}

	.album-meta-sep {
		color: var(--text-subtle, rgba(255, 255, 255, 0.35));
	}
</style>
