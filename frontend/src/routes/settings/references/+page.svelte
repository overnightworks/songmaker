<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { listReferences } from '#lib/api/references.ts';
	import type { ReferenceRecordingResponse } from '#lib/api/types.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { APP_NAME } from '#lib/constants.ts';
	import { reloadWhileUnreachable } from '#lib/stores/connectivity.ts';
	import { formatTime, localDayAndMonth } from '#lib/utils/format.ts';

	const LOAD_FAILED = 'Failed to load references';
	const NO_LENGTH = '—';

	let references = $state<ReferenceRecordingResponse[] | null>(null);
	const referenceReloads = reloadWhileUnreachable(() => void load());
	const loadFailure = referenceReloads.loadFailure;

	async function load() {
		try {
			references = await listReferences();
			referenceReloads.stop();
		} catch (e) {
			referenceReloads.nameLoadFailure(e, LOAD_FAILED);
		}
	}

	function lengthLabel(durationSec: number | null): string {
		return durationSec === null ? NO_LENGTH : formatTime(durationSec);
	}

	function metaLabel(reference: ReferenceRecordingResponse, now: Date): string {
		const uploaded = localDayAndMonth(new Date(reference.created_at), now);
		return `${lengthLabel(reference.duration_sec)} · ${uploaded}`;
	}

	onMount(() => void load());
	onDestroy(() => referenceReloads.dispose());
</script>

<svelte:head>
	<title>References — {APP_NAME}</title>
</svelte:head>

<h1 class="page-title">References</h1>

{#if $loadFailure}
	<p class="error">{$loadFailure}</p>
{/if}

{#if references === null}
	{#if !$loadFailure}
		<p class="loading">Loading references...</p>
	{/if}
{:else if references.length === 0}
	<div class="empty">
		<Icon name="audio-lines" size={40} />
		<p>No references yet — upload a recording to guide a song's sound.</p>
	</div>
{:else}
	{@const now = new Date()}
	<ul class="reference-list">
		{#each references as reference (reference.id)}
			<li class="reference-row">
				<span class="reference-name" title={reference.filename}>{reference.filename}</span>
				<span class="reference-meta">{metaLabel(reference, now)}</span>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.page-title {
		margin: 0 0 1rem;
		font-family: var(--font-display);
		font-size: 1.4rem;
		font-weight: 400;
		letter-spacing: 1px;
		text-transform: uppercase;
		color: var(--text);
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
	}

	.loading {
		color: var(--text-subtle);
		font-size: 0.9rem;
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 24px;
		text-align: center;
		color: var(--text-muted);
	}

	.empty :global(svg) {
		color: var(--text-subtle);
	}

	.empty p {
		margin: 0;
		max-width: 28ch;
		font-size: 0.95rem;
	}

	.reference-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.reference-row {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		min-height: 56px;
		justify-content: center;
		padding: 6px 14px;
	}

	.reference-row + .reference-row {
		border-top: 1px solid var(--border);
	}

	.reference-name {
		font-size: 0.95rem;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.reference-meta {
		font-size: 0.8rem;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}
</style>
