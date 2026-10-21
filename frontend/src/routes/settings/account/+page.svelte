<script lang="ts">
	import { currentUser } from '$lib/stores/auth';

	const me = $derived($currentUser);
</script>

<div class="settings-page">
	<h1>Account</h1>

	<p class="info">Logged in as <strong>{me?.username}</strong> ({me?.role})</p>
</div>

<style>
	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.info {
		color: var(--text-muted);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}
</style>
