<script lang="ts">
	import { currentUser } from '$lib/stores/auth';

	const me = $derived($currentUser);
</script>

<div class="settings-page">
	<h1>Account</h1>
	<p class="identity">
		<span class="username">{me?.username}</span>
		<span class="role">{me?.role === 'admin' ? 'Admin' : 'Member'}</span>
	</p>
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

	.identity {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.75rem;
		margin: 0;
	}

	.username {
		font-size: 1rem;
		color: var(--text);
		overflow-wrap: anywhere;
	}

	.role {
		padding: 0.1rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		font-size: 0.75rem;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
</style>
