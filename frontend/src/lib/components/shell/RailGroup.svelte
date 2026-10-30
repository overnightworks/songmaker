<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { untrack, type Snippet } from 'svelte';
	import { readStorage, writeStorage } from '#lib/utils/storage.ts';
	import { getRailCollapsed } from '#lib/contexts/rail-collapsed.ts';
	import { followPlainClick } from '#lib/stores/navigation.ts';

	const isRailCollapsed = getRailCollapsed();

	interface GroupPage {
		href: string;
		current: boolean;
		open: () => void;
	}

	interface Props {
		label: string;
		groupId: string;
		storageKey: string;
		count?: number;
		// Edge-triggered, not level-triggered: RailGroup force-opens itself the
		// moment this flips from false to true (a genuine entry, e.g. landing on
		// a route the group represents), never merely because it is currently
		// true. RailSettings' own onSettingsRoute is the first caller. See the
		// effect below for why the previous value must NOT be `$state`.
		expandTrigger?: boolean;
		icon?: Snippet;
		// A group that is also a page: its word links to that page and only the
		// caret folds (#1354 rule 40). Without a page the whole header folds.
		page?: GroupPage;
		children: Snippet<[open: boolean]>;
	}

	let {
		label,
		groupId,
		storageKey,
		count,
		expandTrigger = false,
		icon,
		page,
		children
	}: Props = $props();

	let open = $state(untrack(() => readStorage(storageKey) === 'true'));

	// A plain variable, not $state: it must not itself become a dependency
	// this effect reruns for, only a value the effect reads once per actual
	// run of *its own* trigger (expandTrigger) — the same "track the previous
	// value in an untracked local" idiom syncSongAddressToRename uses in
	// stores/navigation.ts. If `open` were read here too, every click that
	// closes the panel while expandTrigger is still true would re-run this
	// effect, find `expandTrigger && !open` true again, and snap it back
	// open, so a viewer could never collapse the group while the trigger
	// stays on.
	let previousExpandTrigger = false;
	$effect(() => {
		const enteredTrigger = expandTrigger && !previousExpandTrigger;
		previousExpandTrigger = expandTrigger;
		if (enteredTrigger) {
			open = true;
			writeStorage(storageKey, String(true));
		}
	});

	function toggleOpen(): void {
		open = !open;
		writeStorage(storageKey, String(open));
	}
</script>

{#snippet caret()}
	<svg
		class="caret"
		class:open
		width="10"
		height="10"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="3"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		<polyline points="9 6 15 12 9 18" />
	</svg>
{/snippet}

{#snippet heading()}
	{#if icon}
		<span class="group-icon" aria-hidden="true">{@render icon()}</span>
	{/if}
	<span class="group-title">{label}</span>
	{#if count !== undefined}
		<span class="meta">{count}</span>
	{/if}
{/snippet}

<div class="rail-group">
	<div class="disclose-row">
		{#if page}
			<button
				type="button"
				class="disclose fold"
				aria-label={label}
				aria-expanded={open}
				aria-controls={groupId}
				title={isRailCollapsed() ? label : undefined}
				onclick={toggleOpen}
			>
				{@render caret()}
			</button>
			<a
				class="disclose page-link rail-page-link"
				href={page.href}
				title={isRailCollapsed() ? label : undefined}
				aria-current={page.current ? 'page' : undefined}
				onclick={(event) => followPlainClick(event, page.open)}
			>
				{@render heading()}
			</a>
		{:else}
			<button
				type="button"
				class="disclose"
				aria-label={label}
				aria-expanded={open}
				aria-controls={groupId}
				title={isRailCollapsed() ? label : undefined}
				onclick={toggleOpen}
			>
				{@render caret()}
				{@render heading()}
			</button>
		{/if}
	</div>
	<div class="rail-group-panel" data-open={open} id={groupId} inert={!open}>
		<div class="rail-group-content">
			{@render children(open)}
		</div>
	</div>
</div>

<style>
	.rail-group {
		flex-shrink: 0;
	}

	.disclose-row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		color: var(--text-muted);
		font-size: 0.85rem;
	}

	.disclose-row:has([aria-current='page']) {
		background: var(--surface-hover);
		color: var(--text);
	}

	.disclose {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: 1;
		min-width: 0;
		padding: 8px 16px;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		text-align: left;
		cursor: pointer;
	}

	.fold {
		flex: none;
		padding-right: 4px;
	}

	.page-link {
		text-decoration: none;
		padding-left: 4px;
	}

	.disclose:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.group-icon {
		display: inline-flex;
		flex-shrink: 0;
		color: currentColor;
	}

	.group-title {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.meta {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.caret {
		flex-shrink: 0;
		transition: transform 0.16s ease;
	}

	.caret.open {
		transform: rotate(90deg);
	}

	.rail-group-panel {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.2s ease;
	}

	.rail-group-panel[data-open='true'] {
		grid-template-rows: 1fr;
	}

	.rail-group-content {
		overflow: hidden;
	}

	/* The open album or playlist outranks a hovered row: bar, tint and a bold
	   name together. Two classes deep so a row's own :hover cannot undo it. */
	.rail-group-panel .rail-group-content :global([aria-current='page']) {
		box-shadow: inset 3px 0 0 var(--accent);
		background: color-mix(in srgb, var(--accent) 22%, transparent);
		color: color-mix(in srgb, var(--accent) 60%, var(--text));
		font-weight: 600;
	}

	@media (prefers-reduced-motion: reduce) {
		.caret,
		.rail-group-panel {
			transition: none;
		}
	}
</style>
