<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import type { SharedCollectionKind } from '#lib/api/shared.ts';
	import type { Key } from '#lib/words/en.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';

	const SHARE_STATUS_HEADINGS = {
		loading: {
			album: 'shareStatus.loadingAlbum',
			playlist: 'shareStatus.loadingPlaylist',
			song: 'shareStatus.loadingSong',
			take: 'shareStatus.loadingTake'
		},
		missing: {
			album: 'shareStatus.notFoundAlbum',
			playlist: 'shareStatus.notFoundPlaylist',
			song: 'shareStatus.notFoundSong',
			take: 'shareStatus.notFoundTake'
		},
		error: {
			album: 'shareStatus.errorAlbum',
			playlist: 'shareStatus.errorPlaylist',
			song: 'shareStatus.errorSong',
			take: 'shareStatus.errorTake'
		}
	} as const satisfies Record<string, Record<SharedCollectionKind, Key>>;

	const SHARE_STATUS_ERROR_BODIES = {
		album: 'shareStatus.errorBodyAlbum',
		playlist: 'shareStatus.errorBodyPlaylist',
		song: 'shareStatus.errorBodySong',
		take: 'shareStatus.errorBodyTake'
	} as const satisfies Record<SharedCollectionKind, Key>;

	interface Props {
		kind: 'loading' | 'missing' | 'error';
		resource: SharedCollectionKind;
		onretry?: () => void;
	}

	let { kind, resource, onretry }: Props = $props();
	let headingElement: HTMLHeadingElement | undefined = $state();

	const heading = $derived(pageText(SHARE_STATUS_HEADINGS[kind][resource]));
	const icon = $derived(
		kind === 'loading' ? 'refresh-cw' : kind === 'missing' ? 'link-off' : 'triangle-alert'
	);

	$effect(() => {
		if (heading) headingElement?.focus();
	});
</script>

<section
	class="share-status"
	class:loading={kind === 'loading'}
	aria-live="polite"
	aria-busy={kind === 'loading'}
>
	<div class="status-mark {kind}" aria-hidden="true">
		<Icon name={icon} size={34} />
	</div>
	<h1 bind:this={headingElement} tabindex="-1">{heading}</h1>
	{#if kind === 'missing'}
		<p>{pageText('shareStatus.invalidLink')}</p>
		<a class="primary" href="/login"
			>{pageText('shareStatus.openApp', { app: pageText('app.name') })}</a
		>
	{:else if kind === 'error'}
		<p>{pageText(SHARE_STATUS_ERROR_BODIES[resource])}</p>
		{#if onretry}
			<button type="button" class="primary" onclick={onretry}
				>{pageText('shareStatus.retry')}</button
			>
		{/if}
		<a href="/login">{pageText('shareStatus.openApp', { app: pageText('app.name') })}</a>
	{/if}
</section>

<style>
	.share-status {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		min-height: 40vh;
		padding: 2rem 1.25rem;
		text-align: center;
	}

	.status-mark {
		display: grid;
		place-items: center;
		width: 4.5rem;
		height: 4.5rem;
		margin-bottom: 0.25rem;
		border: 1px solid currentColor;
		background: color-mix(in srgb, currentColor 8%, transparent);
	}

	.status-mark.loading {
		border-radius: 50%;
		color: var(--accent);
		animation: spin 1.8s linear infinite;
	}

	.status-mark.missing {
		border-radius: 1.1rem;
		color: var(--text-muted);
	}

	.status-mark.error {
		border-radius: 50% 50% 0.8rem 0.8rem;
		color: var(--score-ok);
	}

	h1 {
		margin: 0;
		font-size: 1.4rem;
	}

	p {
		margin: 0;
		color: var(--text-muted);
		max-width: 28rem;
	}

	.primary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		margin-top: 0.5rem;
		padding: 0.55rem 1.1rem;
		border-radius: 8px;
		background: var(--accent);
		color: var(--on-accent);
		text-decoration: none;
		border: none;
		font: inherit;
		cursor: pointer;
	}

	a:not(.primary) {
		color: var(--text-muted);
		text-decoration: underline;
		text-underline-offset: 0.2rem;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.status-mark.loading {
			animation: none;
		}
	}
</style>
