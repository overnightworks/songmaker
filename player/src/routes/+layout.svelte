<script lang="ts">
	import '../app.css';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';

	let { children } = $props();

	const currentPath = $derived($page.url.pathname);
</script>

<svelte:head>
	<title>Songmaker</title>
</svelte:head>

<nav class="top-nav">
	<a href={resolve('/')} class="nav-link" class:active={currentPath === '/'}>Library</a>
	<a href={resolve('/studio')} class="nav-link" class:active={currentPath === '/studio'}>Studio</a>
</nav>

<div class="app-shell">
	{@render children()}
</div>

<PlayerBar />

<style>
	.top-nav {
		display: flex;
		gap: 0;
		background: #0a0a0a;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
		padding: 0 16px;
	}

	.nav-link {
		padding: 8px 20px;
		font-family: var(--font-display);
		font-size: 13px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 1px;
		text-decoration: none;
		border-bottom: 2px solid transparent;
		transition: all 0.2s;
	}

	.nav-link:hover {
		color: var(--text);
	}

	.nav-link.active {
		color: var(--primary);
		border-bottom-color: var(--primary);
	}

	.app-shell {
		display: flex;
		height: calc(100vh - var(--player-height) - 37px);
		overflow: hidden;
	}
</style>
