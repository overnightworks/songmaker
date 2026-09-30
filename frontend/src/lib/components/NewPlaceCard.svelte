<script lang="ts">
	import type { Snippet } from 'svelte';
	import { NetworkError } from '$lib/api/fetch';
	import { addToast } from '$lib/stores/toast';
	import { NEW_PLACE_CREATE_LABEL, NEW_PLACE_OFFLINE } from '$lib/constants';
	import Icon from './Icon.svelte';

	interface Props {
		label: string;
		closeLabel: string;
		hint: string;
		/** The readable reason a refused create names; never the server's own detail. */
		failedMessage: string;
		ready: boolean;
		/** Creates the place, lists it, and answers its id. */
		create: () => Promise<string>;
		open: (id: string) => Promise<void>;
		oncancel: () => void;
		oncreated: () => void;
		children: Snippet;
	}

	let {
		label,
		closeLabel,
		hint,
		failedMessage,
		ready,
		create,
		open,
		oncancel,
		oncreated,
		children
	}: Props = $props();

	let creating = $state(false);

	const canCreate = $derived(ready && !creating);

	function refusalReason(err: unknown): string {
		return err instanceof NetworkError ? NEW_PLACE_OFFLINE : failedMessage;
	}

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!canCreate) return;
		creating = true;
		let id: string;
		try {
			id = await create();
		} catch (err) {
			addToast(refusalReason(err), 'error');
			creating = false;
			return;
		}
		oncreated();
		await open(id);
	}
</script>

<form class="new-place" aria-label={label} onsubmit={submit}>
	<div class="card-head">
		<span class="card-title">{label}</span>
		<button type="button" class="close-btn" aria-label={closeLabel} onclick={oncancel}>
			<Icon name="x" size={18} />
		</button>
	</div>
	{@render children()}
	<div class="card-foot">
		<small>{hint}</small>
		<button type="submit" class="create-btn" disabled={!canCreate}>{NEW_PLACE_CREATE_LABEL}</button>
	</div>
</form>

<style>
	.new-place {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-bottom: 12px;
		padding: 12px;
		border: 1px solid var(--accent);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.card-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin: -6px -6px -4px 0;
	}

	.card-title {
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.85rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.close-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		padding: 0;
		border: 0;
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
	}

	.close-btn:hover {
		color: var(--text);
	}

	.new-place :global(.field) {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}

	.new-place :global(.field-label) {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.new-place :global(.field-label em) {
		color: var(--text-subtle);
		font-family: var(--font-body);
		font-style: normal;
		letter-spacing: 0;
		text-transform: none;
	}

	.new-place :global(.field input) {
		height: 40px;
		padding: 0 12px;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--bg);
		color: var(--text);
		font-family: var(--font-body);
		font-size: 15px;
	}

	.new-place :global(.field input::placeholder) {
		color: var(--text-subtle);
	}

	.new-place :global(.field input:focus) {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}

	.card-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

	.card-foot small {
		color: var(--text-subtle);
		font-size: 0.75rem;
		line-height: 1.35;
	}

	.create-btn {
		flex: none;
		height: 32px;
		padding: 0 20px;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: var(--accent);
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.78rem;
		font-weight: 500;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.create-btn:disabled {
		border-color: var(--border);
		background: none;
		color: var(--text-disabled);
		cursor: default;
	}

	@media (max-width: 768px) {
		.close-btn,
		.create-btn {
			height: 44px;
		}

		.close-btn {
			width: 44px;
		}

		.new-place :global(.field input) {
			height: 52px;
		}
	}
</style>
