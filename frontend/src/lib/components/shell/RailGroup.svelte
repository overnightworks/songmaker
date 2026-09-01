<script lang="ts">
	import type { Snippet } from 'svelte';

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
		// The seam issue #305 opened for a group whose title itself navigates,
		// now used by LIBRARY and PLAYLISTS (issue #323, ruled sentence 5 of
		// #302): when set, the title renders as a button next to — not nested
		// inside — the disclosure toggle, so the chevron/icon still just
		// expand or collapse the group. A click handler rather than a plain
		// href because the destination is a tab held in `history.state` (see
		// selectLibraryFilter in stores/navigation.ts), not an address a link
		// could point at.
		onTitleClick?: () => void;
		icon?: Snippet;
		children: Snippet;
	}

	let {
		label,
		groupId,
		storageKey,
		count,
		expandTrigger = false,
		onTitleClick,
		icon,
		children
	}: Props = $props();

	function readPersistedOpen(): boolean {
		try {
			return localStorage.getItem(storageKey) === 'true';
		} catch {
			return false;
		}
	}

	function persistOpen(value: boolean): void {
		try {
			localStorage.setItem(storageKey, String(value));
		} catch {
			// Best-effort convenience only — the disclosure still works without it.
		}
	}

	let open = $state(readPersistedOpen());

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
			persistOpen(true);
		}
	});

	function toggleOpen(): void {
		open = !open;
		persistOpen(open);
	}
</script>

<div class="rail-group">
	<div class="disclose-row">
		<button
			type="button"
			class="disclose"
			aria-expanded={open}
			aria-controls={groupId}
			onclick={toggleOpen}
		>
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
			{#if icon}
				<span class="group-icon" aria-hidden="true">{@render icon()}</span>
			{/if}
			{#if !onTitleClick}
				<span class="group-title">{label}</span>
			{/if}
		</button>
		{#if onTitleClick}
			<button type="button" class="group-title group-title-action" onclick={onTitleClick}>
				{label}
			</button>
		{/if}
		{#if count !== undefined}
			<span class="meta">{count}</span>
		{/if}
	</div>
	<div class="rail-group-panel" data-open={open} id={groupId} inert={!open}>
		<div class="rail-group-content">
			{@render children()}
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

	.group-title-action {
		flex-shrink: 0;
		padding: 8px 16px 8px 0;
		background: none;
		border: none;
		font: inherit;
		color: var(--text-muted);
		cursor: pointer;
	}

	.group-title-action:hover {
		color: var(--text);
	}

	.meta {
		margin-left: auto;
		padding-right: 16px;
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

	@media (prefers-reduced-motion: reduce) {
		.caret,
		.rail-group-panel {
			transition: none;
		}
	}
</style>
