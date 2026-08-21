<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { PlaybackInfo } from '$lib/services/playbackTypes';
	import {
		HITBOX_FREQUENT_PX,
		NOW_PLAYING_CLOSE,
		NOW_PLAYING_GO_TO_SONG,
		NOW_PLAYING_LABEL,
		NOW_PLAYING_NO_LYRICS,
		NOW_PLAYING_TAKE_PREFIX
	} from '$lib/constants';
	import Icon from './Icon.svelte';

	let {
		info,
		onclose,
		onGoToSong
	}: {
		info: PlaybackInfo;
		onclose: () => void;
		onGoToSong: () => void;
	} = $props();

	let sheet: HTMLDivElement | undefined = $state();
	const lyrics = $derived(info.lyrics);
	const hasLyrics = $derived(lyrics != null && lyrics.length > 0);
	const albumLine = $derived(
		[info.albumTitle, info.artist].filter((part) => part.length > 0).join(' · ')
	);
	const takeLabel = $derived(`${NOW_PLAYING_TAKE_PREFIX} ${info.generation.generation_number}`);

	onMount(() => {
		void tick().then(() => sheet?.focus());
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!sheet) return;
		if (event.key === 'Escape') {
			event.preventDefault();
			onclose();
			return;
		}
		if (event.key !== 'Tab') return;
		const focusable = Array.from(sheet.querySelectorAll<HTMLElement>('button:not(:disabled)'));
		if (focusable.length === 0) {
			event.preventDefault();
			sheet.focus();
			return;
		}
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		const active = document.activeElement;
		if (event.shiftKey && (active === first || !sheet.contains(active))) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && (active === last || !sheet.contains(active))) {
			event.preventDefault();
			first.focus();
		}
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="now-playing-modal">
	<button class="sheet-backdrop" tabindex="-1" onclick={onclose} aria-label={NOW_PLAYING_CLOSE}
	></button>
	<div
		bind:this={sheet}
		class="now-playing-sheet"
		role="dialog"
		aria-modal="true"
		aria-labelledby="now-playing-title"
		tabindex="-1"
	>
		{#key `${info.songId}:${info.generation.id}`}
			<header class="sheet-header">
				<div class="sheet-heading">
					<p class="sheet-kicker">{NOW_PLAYING_LABEL}</p>
					<h2 id="now-playing-title" class="sheet-title">{info.songTitle}</h2>
					{#if albumLine}
						<p class="sheet-meta">{albumLine}</p>
					{/if}
					<p class="sheet-take">{takeLabel}</p>
				</div>
				<button
					class="icon-btn"
					style:min-width="{HITBOX_FREQUENT_PX}px"
					style:min-height="{HITBOX_FREQUENT_PX}px"
					onclick={onclose}
					aria-label={NOW_PLAYING_CLOSE}
				>
					<Icon name="x" size={18} />
				</button>
			</header>
			{#if hasLyrics}
				<div class="lyrics">{lyrics}</div>
			{:else}
				<p class="lyrics-empty">{NOW_PLAYING_NO_LYRICS}</p>
			{/if}
			<button
				class="go-song"
				style:min-width="{HITBOX_FREQUENT_PX}px"
				style:min-height="{HITBOX_FREQUENT_PX}px"
				onclick={onGoToSong}>{NOW_PLAYING_GO_TO_SONG}</button
			>
		{/key}
	</div>
</div>

<style>
	.now-playing-modal {
		position: fixed;
		inset: 0;
		z-index: 109;
	}
	.sheet-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}
	.now-playing-sheet {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--player-height);
		max-height: min(70vh, 28rem);
		padding: 0.75rem 0.8rem calc(0.75rem + env(safe-area-inset-bottom, 0px));
		background: var(--header-bg);
		border-top: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		min-width: 0;
		z-index: 1;
	}
	.sheet-header {
		display: flex;
		align-items: flex-start;
		gap: 0.6rem;
		min-width: 0;
	}
	.sheet-heading {
		min-width: 0;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.sheet-kicker {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.68rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.sheet-title {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.05rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		overflow-wrap: anywhere;
	}
	.sheet-meta,
	.sheet-take {
		margin: 0;
		font-size: 0.78rem;
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}
	.icon-btn,
	.go-song {
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
	.icon-btn {
		flex-shrink: 0;
		width: 44px;
		height: 44px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid transparent;
		border-radius: 50%;
		background: transparent;
		color: var(--text-muted);
	}
	.icon-btn:hover {
		color: var(--text);
		border-color: var(--border);
		background: var(--surface-hover);
	}
	.lyrics,
	.lyrics-empty {
		margin: 0;
		min-height: 4.5rem;
		max-height: min(38vh, 16rem);
		overflow: auto;
		overflow-wrap: anywhere;
	}
	.lyrics {
		white-space: pre-wrap;
		font-family: var(--font-body);
		font-size: 0.92rem;
		line-height: 1.45;
		color: var(--text);
	}
	.lyrics-empty {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.go-song {
		align-self: stretch;
		padding: 0.55rem 0.8rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface) 80%, transparent);
		color: var(--text);
		font-size: var(--label-font-size);
	}
	.go-song:hover {
		border-color: var(--primary);
		background: color-mix(in srgb, var(--primary) 12%, var(--surface));
	}
</style>
