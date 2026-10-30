<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- links leave the app for GitHub */
	import { onDestroy, onMount } from 'svelte';
	import { fetchRelease } from '#lib/api/settings.ts';
	import type { ReleaseInfo } from '#lib/api/types.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { APP_NAME, APP_REPOSITORY_URL } from '#lib/constants.ts';
	import { reloadWhileUnreachable } from '#lib/stores/connectivity.ts';
	import { releaseDayLabel } from '#lib/utils/format.ts';

	const LICENCE_NAME = 'MIT';
	const LOAD_FAILED = 'Failed to load the release';
	const COMMIT_PREFIX_LENGTH = 8;
	// What the backend reports for an image built without the release build arguments.
	const RELEASE_TAG_UNRELEASED = 'unreleased';
	const RELEASE_COMMIT_UNKNOWN = 'unknown';

	let release = $state<ReleaseInfo | null>(null);
	const releaseReloads = reloadWhileUnreachable(() => void load());
	const loadFailure = releaseReloads.loadFailure;

	const tag = $derived(
		release !== null && release.tag !== RELEASE_TAG_UNRELEASED ? release.tag : null
	);
	const commit = $derived(
		release !== null && release.commit !== RELEASE_COMMIT_UNKNOWN ? release.commit : null
	);
	const releasedOn = $derived(tag === null ? null : releaseDayLabel(tag));

	async function load() {
		try {
			release = await fetchRelease();
			releaseReloads.stop();
		} catch (e) {
			releaseReloads.nameLoadFailure(e, LOAD_FAILED);
		}
	}

	onMount(() => void load());
	onDestroy(() => releaseReloads.dispose());
</script>

<svelte:head>
	<title>About — {APP_NAME}</title>
</svelte:head>

<h1 class="about-title">About</h1>

{#if $loadFailure}
	<p class="error">{$loadFailure}</p>
{:else if release === null}
	<p class="loading">Loading...</p>
{:else}
	<div class="about-list">
		<div class="about-row">
			<span class="about-label">App</span>
			<span class="about-value">{APP_NAME}</span>
		</div>
		<div class="about-row">
			<span class="about-label">Version</span>
			{#if tag === null}
				<span class="about-value about-dim">No release</span>
			{:else}
				<span class="about-value">{tag}</span>
			{/if}
		</div>
		{#if releasedOn !== null}
			<div class="about-row">
				<span class="about-label">Released</span>
				<span class="about-value">{releasedOn}</span>
			</div>
		{/if}
		{#if commit === null}
			<div class="about-row">
				<span class="about-label">Commit</span>
				<span class="about-value about-dim">Unknown</span>
			</div>
		{:else}
			<a
				class="about-row about-link"
				href="{APP_REPOSITORY_URL}/commit/{commit}"
				target="_blank"
				rel="noopener"
			>
				<span class="about-label">Commit</span>
				<span class="about-value about-mono">{commit.slice(0, COMMIT_PREFIX_LENGTH)}</span>
				<Icon name="external-link" size={16} class="about-icon" />
			</a>
		{/if}
		{#if tag !== null}
			<a
				class="about-row about-link"
				href="{APP_REPOSITORY_URL}/releases/tag/{tag}"
				target="_blank"
				rel="noopener"
			>
				<span class="about-label">What’s new</span>
				<Icon name="external-link" size={16} class="about-icon" />
			</a>
		{/if}
		<a
			class="about-row about-link"
			href="{APP_REPOSITORY_URL}/blob/main/LICENSE"
			target="_blank"
			rel="noopener"
		>
			<span class="about-label">Licence</span>
			<span class="about-value">{LICENCE_NAME}</span>
			<Icon name="external-link" size={16} class="about-icon" />
		</a>
	</div>
{/if}

<style>
	.about-title {
		margin: 0 0 0.5rem;
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

	.about-list {
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.about-row {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 52px;
		padding: 0 12px 0 14px;
		color: var(--text);
		font-size: 0.93rem;
		text-decoration: none;
	}

	.about-row + .about-row {
		border-top: 1px solid var(--border);
	}

	a.about-row:hover {
		background: var(--surface-hover);
	}

	a.about-row:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.about-label {
		flex: 1;
		min-width: 0;
	}

	.about-value {
		font-size: 0.85rem;
		color: var(--text-muted);
		text-align: right;
	}

	.about-dim {
		color: var(--text-subtle);
	}

	.about-mono {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		letter-spacing: 0.02em;
		color: var(--text);
	}

	.about-row :global(.about-icon) {
		flex: none;
		color: var(--text-muted);
	}
</style>
