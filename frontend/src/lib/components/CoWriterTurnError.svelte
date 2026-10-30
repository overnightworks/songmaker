<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path; the server answers the sign-in address with a redirect */
	import { signInAddress } from '#lib/api/fetch.ts';
	import {
		COWRITER_PROBLEM_LOOKS,
		cowriterWaitClock,
		type CowriterProblem
	} from '#lib/utils/cowriter-ui.ts';
	import Icon from './Icon.svelte';

	interface Props {
		text: string;
		problem: CowriterProblem | null;
		waitSeconds: number;
		onretry: () => void;
	}

	let { text, problem, waitSeconds, onretry }: Props = $props();

	const signInHref = $derived(signInAddress(location.pathname + location.search));
	const look = $derived(problem ? COWRITER_PROBLEM_LOOKS[problem] : null);
	let remaining = $state(0);

	$effect(() => {
		remaining = waitSeconds;
		if (waitSeconds === 0) return;
		const timer = setInterval(() => {
			remaining -= 1;
			if (remaining <= 0) clearInterval(timer);
		}, 1000);
		return () => clearInterval(timer);
	});
</script>

<div class="turn-error {look?.tone ?? ''}" role="alert">
	{#if look}<Icon name={look.icon} size={18} />{/if}
	<span class="text">{text}</span>
	{#if problem === 'sign_in_again'}
		<a class="signin" href={signInHref} data-sveltekit-reload>Sign in</a>
	{:else if problem !== 'not_enabled'}
		<button type="button" class="retry-turn" disabled={remaining > 0} onclick={onretry}>
			Try again{#if remaining > 0}
				<span class="wait-time">&nbsp;{cowriterWaitClock(remaining)}</span>{/if}
		</button>
	{/if}
</div>

<style>
	.turn-error {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.2rem 0.55rem;
		align-self: stretch;
		padding: 0.35rem 0.3rem 0.35rem 0.65rem;
		border-left: 3px solid var(--border);
		border-radius: 0 4px 4px 0;
		background: var(--surface);
		font-size: 0.86rem;
		line-height: 1.4;
	}

	.turn-error :global(svg) {
		flex: none;
	}

	.turn-error .text {
		flex: 1 1 12rem;
		min-width: 0;
	}

	.turn-error.bad {
		border-left-color: var(--score-bad);
		color: var(--score-bad);
	}

	.turn-error.wait {
		border-left-color: var(--score-ok);
		color: var(--score-ok);
	}

	.turn-error.off {
		border-left-style: dashed;
		color: var(--text-muted);
	}

	.turn-error .text {
		color: var(--text);
	}

	.turn-error.off .text {
		color: var(--text-muted);
	}

	.signin {
		display: inline-flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		padding: 0 0.6rem;
		color: var(--primary);
		font-weight: 600;
		text-decoration: underline;
		text-underline-offset: 3px;
	}

	.retry-turn {
		display: inline-flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		padding: 0 0.8rem;
		border: 1px solid var(--primary);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--primary);
		cursor: pointer;
		font-family: var(--font-display);
		font-size: var(--btn-font-size-sm);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		white-space: nowrap;
	}

	.retry-turn:disabled {
		border-color: var(--border);
		color: var(--text-disabled);
		cursor: default;
	}

	.retry-turn .wait-time {
		font-family: var(--font-body);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0;
		text-transform: none;
	}
</style>
