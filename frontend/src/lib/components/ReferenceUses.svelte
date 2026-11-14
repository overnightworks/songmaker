<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path, and the URLs are resolved library addresses built by songRoutePath/takeRoutePath */
	import { onMount } from 'svelte';
	import { getReferenceUses } from '#lib/api/references.ts';
	import type {
		ReferenceTakeUseResponse,
		ReferenceUsesResponse,
		ReferenceVersionUseResponse
	} from '#lib/api/types.ts';
	import { songRoutePath, takeRoutePath } from '#lib/routes/addresses.ts';
	import { formatTime } from '#lib/utils/format.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';

	type SongUses = {
		songId: string;
		title: string;
		trashed: boolean;
		takes: ReferenceTakeUseResponse[];
		versions: ReferenceVersionUseResponse[];
	};

	let { id, referenceId }: { id: string; referenceId: string } = $props();

	let uses = $state<ReferenceUsesResponse | null>(null);
	let failed = $state(false);

	onMount(() => {
		let open = true;
		getReferenceUses(referenceId).then(
			(answer) => {
				if (open) uses = answer;
			},
			() => {
				if (open) failed = true;
			}
		);
		return () => (open = false);
	});

	function bySong(answer: ReferenceUsesResponse): SongUses[] {
		const songs: SongUses[] = [];
		const songOf = (use: ReferenceTakeUseResponse | ReferenceVersionUseResponse): SongUses => {
			const known = songs.find((song) => song.songId === use.song_id);
			if (known) return known;
			const created: SongUses = {
				songId: use.song_id,
				title: use.song_title,
				trashed: use.is_trashed,
				takes: [],
				versions: []
			};
			songs.push(created);
			return created;
		};
		for (const take of answer.takes) songOf(take).takes.push(take);
		for (const version of answer.versions) songOf(version).versions.push(version);
		return songs;
	}

	function versionLabel(version: ReferenceVersionUseResponse): string {
		return pageText('referenceUses.version', { version: String(version.version_number) });
	}

	function takeLabel(take: ReferenceTakeUseResponse): string {
		const number = String(take.generation_number);
		const version = take.version_number === null ? null : String(take.version_number);
		const length = take.audio_duration_sec === null ? null : formatTime(take.audio_duration_sec);
		if (version !== null && length !== null) {
			return pageText('referenceUses.takeVersionLength', { number, version, length });
		}
		if (version !== null) return pageText('referenceUses.takeVersion', { number, version });
		if (length !== null) return pageText('referenceUses.takeLength', { number, length });
		return pageText('referenceUses.take', { number });
	}
</script>

<div {id} class="uses">
	{#if failed}
		<p class="uses-note uses-fault" role="alert">{pageText('referenceUses.loadFailed')}</p>
	{:else if uses === null}
		<p class="uses-note" role="status">{pageText('referenceUses.loading')}</p>
	{:else}
		{#each bySong(uses) as song (song.songId)}
			<section class="uses-song">
				<h3 class="uses-song-title">
					{song.title}
					{#if song.trashed}<span class="uses-tag">{pageText('referenceUses.deletedTag')}</span
						>{/if}
				</h3>
				<ul>
					{#each song.takes as take (take.generation_number)}
						<li>
							{#if song.trashed}
								<span class="uses-row">
									{takeLabel(take)}
									{#if take.is_archived}<span class="uses-tag"
											>{pageText('referenceUses.archivedTag')}</span
										>{/if}
								</span>
							{:else}
								<a
									class="uses-row"
									href={takeRoutePath(take.album_id, take.song_slug, take.generation_number)}
								>
									{takeLabel(take)}
									{#if take.is_archived}<span class="uses-tag"
											>{pageText('referenceUses.archivedTag')}</span
										>{/if}
									<Icon name="chevron-right" size={16} />
								</a>
							{/if}
						</li>
					{/each}
					{#each song.versions as version (version.version_number)}
						<li>
							{#if song.trashed}
								<span class="uses-row">{versionLabel(version)}</span>
							{:else}
								<a class="uses-row" href={songRoutePath(version.album_id, version.song_slug)}>
									{versionLabel(version)}
									<Icon name="chevron-right" size={16} />
								</a>
							{/if}
						</li>
					{/each}
				</ul>
			</section>
		{/each}
		<p class="uses-note">{pageText('referenceUses.staysNote')}</p>
	{/if}
</div>

<style>
	.uses {
		padding: 4px 0 6px;
		background: var(--bg);
		border-top: 1px solid var(--border);
	}

	.uses-song-title {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0;
		padding: 4px 14px 2px 58px;
		font-family: var(--font-display);
		font-size: 11px;
		font-weight: normal;
		letter-spacing: 0.8px;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.uses-row {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: var(--hitbox-frequent);
		padding: 0 14px 0 58px;
		font-size: 13px;
		color: var(--text);
		text-decoration: none;
	}

	a.uses-row:hover {
		background: var(--surface-hover);
	}

	a.uses-row :global(svg) {
		margin-left: auto;
		color: var(--text-disabled);
	}

	.uses-tag {
		padding: 0 6px;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		font-size: 11px;
		color: var(--text-subtle);
	}

	.uses-note {
		margin: 0;
		padding: 4px 14px 2px 58px;
		font-size: 12px;
		color: var(--text-muted);
	}

	.uses-fault {
		color: var(--fail);
	}
</style>
