<script lang="ts">
	import { page } from '$app/state';
	import { tick, untrack } from 'svelte';
	import {
		LIBRARY_TAKE_POOLS,
		LIBRARY_TAKE_POOL_LABELS,
		libraryTakePool,
		type LibraryTakePool
	} from '$lib/stores/playbackSettings';
	import { chooseLibraryTakePool, queueContext } from '$lib/stores/player';
	import { detailTab } from '$lib/stores/navigation';
	import Icon from './Icon.svelte';

	const POOL_HELP =
		'Mix: Picks und Keeps. Picks: Album-Take. Keeps: Favoriten, mehrere je Song. Alle: jeder spielbare Take.';

	const POOL_ICONS: Record<LibraryTakePool, 'star-filled' | 'heart-filled' | 'layers'> = {
		mix: 'star-filled',
		picks: 'star-filled',
		keeps: 'heart-filled',
		all: 'layers'
	};

	const pool = $derived($libraryTakePool);
	const onLibrary = $derived($queueContext.type === 'library');

	let sheetOpen = $state(false);
	let helpOpen = $state(false);
	let narrow = $state(false);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let sheet: HTMLDivElement | undefined = $state();
	let lastSurfaceKey = '';
	const surfaceKey = $derived(`${page.url.pathname}:${$detailTab}`);

	$effect(() => {
		if (typeof window === 'undefined') return;
		const media = window.matchMedia('(max-width: 640px), (any-pointer: coarse)');
		const syncNarrow = () => {
			narrow = media.matches || document.documentElement.dataset.pointer === 'coarse';
			if (!narrow) closeSheet();
		};
		syncNarrow();
		media.addEventListener('change', syncNarrow);
		const pointerObserver = new MutationObserver(syncNarrow);
		pointerObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-pointer']
		});
		return () => {
			media.removeEventListener('change', syncNarrow);
			pointerObserver.disconnect();
		};
	});

	$effect(() => {
		const nextSurfaceKey = surfaceKey;
		untrack(() => {
			if (lastSurfaceKey && lastSurfaceKey !== nextSurfaceKey) {
				closeSheet();
				helpOpen = false;
			}
			lastSurfaceKey = nextSurfaceKey;
		});
	});

	$effect(() => {
		if (!onLibrary) untrack(() => closeSheet());
	});

	async function openSheet(): Promise<void> {
		helpOpen = false;
		sheetOpen = true;
		await tick();
		const active = sheet?.querySelector<HTMLElement>('[aria-checked="true"]');
		(active ?? sheet)?.focus();
	}

	function closeSheet(restoreFocus = true): void {
		if (!sheetOpen) return;
		sheetOpen = false;
		if (restoreFocus) queueMicrotask(() => triggerButton?.focus());
	}

	function toggleSheet(): void {
		if (sheetOpen) closeSheet();
		else void openSheet();
	}

	function selectPool(next: LibraryTakePool): void {
		closeSheet();
		void chooseLibraryTakePool(next);
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!sheetOpen || !sheet) return;
		if (event.key === 'Escape') {
			event.preventDefault();
			closeSheet();
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

	function onRadiogroupKeydown(event: KeyboardEvent): void {
		const index = LIBRARY_TAKE_POOLS.indexOf(pool);
		if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
			event.preventDefault();
			selectPool(LIBRARY_TAKE_POOLS[(index + 1) % LIBRARY_TAKE_POOLS.length]);
		} else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
			event.preventDefault();
			selectPool(
				LIBRARY_TAKE_POOLS[(index - 1 + LIBRARY_TAKE_POOLS.length) % LIBRARY_TAKE_POOLS.length]
			);
		}
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#if onLibrary}
	<div class="pool-control">
		{#if narrow}
			<button
				bind:this={triggerButton}
				class="pool-current"
				class:mix={pool === 'mix'}
				class:picks={pool === 'picks'}
				class:keeps={pool === 'keeps'}
				class:all={pool === 'all'}
				onclick={toggleSheet}
				aria-haspopup="dialog"
				aria-expanded={sheetOpen}
				aria-label={`Take pool ${LIBRARY_TAKE_POOL_LABELS[pool]}`}
			>
				{#if pool === 'mix'}
					<span class="mix-icons" aria-hidden="true">
						<Icon name="star-filled" size={13} />
						<Icon name="heart-filled" size={13} />
					</span>
				{:else}
					<Icon name={POOL_ICONS[pool]} size={16} />
				{/if}
				<span>{LIBRARY_TAKE_POOL_LABELS[pool]}</span>
			</button>
		{:else}
			<div
				class="pool-strip"
				role="radiogroup"
				aria-label="Take pool"
				tabindex="-1"
				onkeydown={onRadiogroupKeydown}
			>
				{#each LIBRARY_TAKE_POOLS as option (option)}
					<button
						class="pool-btn"
						class:active={pool === option}
						class:mix={option === 'mix'}
						class:picks={option === 'picks'}
						class:keeps={option === 'keeps'}
						class:all={option === 'all'}
						role="radio"
						aria-checked={pool === option}
						tabindex={pool === option ? 0 : -1}
						onclick={() => selectPool(option)}
						aria-label={LIBRARY_TAKE_POOL_LABELS[option]}
						title={LIBRARY_TAKE_POOL_LABELS[option]}
					>
						{#if option === 'mix'}
							<span class="mix-icons" aria-hidden="true">
								<Icon name="star-filled" size={12} />
								<Icon name="heart-filled" size={12} />
							</span>
						{:else}
							<Icon name={POOL_ICONS[option]} size={15} />
						{/if}
						<span class="pool-label">{LIBRARY_TAKE_POOL_LABELS[option]}</span>
					</button>
				{/each}
			</div>
		{/if}
		{#if !narrow}
			<button
				class="pool-info"
				onclick={() => (helpOpen = !helpOpen)}
				aria-expanded={helpOpen}
				aria-label="What Mix Picks Keeps Alle mean"
				title="What Mix Picks Keeps Alle mean"
			>
				<Icon name="info" size={15} />
			</button>
		{/if}
		{#if helpOpen}
			<p class="pool-help">{POOL_HELP}</p>
		{/if}
	</div>
	{#if sheetOpen}
		<div class="pool-modal">
			<button
				class="sheet-backdrop"
				tabindex="-1"
				onclick={() => closeSheet()}
				aria-label="Close take pool"
			></button>
			<div
				bind:this={sheet}
				class="pool-sheet"
				role="dialog"
				aria-modal="true"
				aria-label="Take pool"
				tabindex="-1"
			>
				<p class="sheet-help"><Icon name="info" size={16} /><span>{POOL_HELP}</span></p>
				<div class="sheet-options" role="radiogroup" aria-label="Take pool choices">
					{#each LIBRARY_TAKE_POOLS as option (option)}
						<button
							class="sheet-btn"
							class:active={pool === option}
							role="radio"
							aria-checked={pool === option}
							onclick={() => selectPool(option)}
						>
							{#if option === 'mix'}
								<span class="mix-icons" aria-hidden="true">
									<Icon name="star-filled" size={16} />
									<Icon name="heart-filled" size={16} />
								</span>
							{:else}
								<Icon name={POOL_ICONS[option]} size={18} />
							{/if}
							{LIBRARY_TAKE_POOL_LABELS[option]}
						</button>
					{/each}
				</div>
			</div>
		</div>
	{/if}
{/if}

<style>
	.pool-control {
		display: flex;
		align-items: center;
		gap: 4px;
		position: relative;
		flex-shrink: 0;
	}
	.pool-strip {
		display: flex;
		gap: 2px;
		padding: 2px;
		border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
	}
	.pool-btn,
	.pool-current,
	.pool-info,
	.sheet-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		border: 1px solid transparent;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-body);
	}
	.pool-btn {
		height: 34px;
		padding: 0 8px;
		border-radius: 999px;
		font-size: 0.7rem;
		letter-spacing: 0.3px;
	}
	.pool-btn.active.mix,
	.pool-current.mix {
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	.pool-btn.active.picks,
	.pool-current.picks {
		color: var(--primary);
		background: color-mix(in srgb, var(--primary) 14%, var(--surface));
	}
	.pool-btn.active.keeps,
	.pool-current.keeps {
		color: var(--keep);
		background: color-mix(in srgb, var(--keep) 16%, var(--surface));
	}
	.pool-btn.active.all,
	.pool-current.all {
		color: var(--text);
		background: color-mix(in srgb, var(--text) 12%, var(--surface));
	}
	.pool-label {
		font-weight: 600;
	}
	.pool-current {
		height: 36px;
		padding: 0 10px;
		border-radius: 999px;
		border-color: color-mix(in srgb, var(--border) 80%, transparent);
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		font-size: 0.78rem;
		font-weight: 600;
	}
	.pool-info {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		color: var(--text-subtle);
	}
	.pool-info:hover,
	.pool-btn:hover,
	.pool-current:hover {
		color: var(--text);
	}
	.mix-icons {
		display: inline-flex;
		align-items: center;
		margin-right: 1px;
	}
	.mix-icons :global(svg:last-child) {
		margin-left: -6px;
		color: var(--keep);
	}
	.pool-help {
		position: absolute;
		bottom: calc(100% + 8px);
		left: 0;
		width: min(280px, 70vw);
		padding: 0.6rem 0.7rem;
		border-radius: var(--card-radius);
		border: 1px solid var(--border);
		background: var(--header-bg);
		color: var(--text);
		font-size: 0.75rem;
		line-height: 1.35;
		z-index: 20;
	}
	.pool-modal {
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
	.pool-sheet {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--player-height);
		padding: 0.7rem 0.8rem calc(0.7rem + env(safe-area-inset-bottom, 0px));
		background: var(--header-bg);
		border-top: 1px solid var(--border);
		z-index: 1;
	}
	.sheet-help {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		max-width: 420px;
		margin: 0 auto 0.65rem;
		color: var(--text-muted);
		font-size: 0.75rem;
		line-height: 1.35;
	}
	.sheet-help :global(svg) {
		flex: 0 0 auto;
		margin-top: 1px;
		color: var(--accent);
	}
	.sheet-options {
		display: flex;
		gap: 8px;
		justify-content: center;
		width: 100%;
	}
	.sheet-btn {
		flex: 1;
		max-width: 90px;
		height: 44px;
		border-radius: 10px;
		border-color: var(--border);
		font-size: 0.8rem;
		font-weight: 600;
	}
	.sheet-btn.active {
		border-color: var(--accent);
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	@media (max-width: 640px), (any-pointer: coarse) {
		.pool-current {
			position: relative;
			height: 44px;
			padding: 0 6px;
			border-color: transparent;
			background: transparent;
			isolation: isolate;
		}
		.pool-current.mix,
		.pool-current.picks,
		.pool-current.keeps,
		.pool-current.all {
			background: transparent;
		}
		.pool-current::before {
			content: '';
			position: absolute;
			z-index: -1;
			left: 0;
			right: 0;
			top: 4px;
			height: 36px;
			border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
			border-radius: 999px;
			background: color-mix(in srgb, var(--surface) 70%, transparent);
		}
		.pool-current.mix::before {
			background: color-mix(in srgb, var(--accent) 14%, var(--surface));
		}
		.pool-current.picks::before {
			background: color-mix(in srgb, var(--primary) 14%, var(--surface));
		}
		.pool-current.keeps::before {
			background: color-mix(in srgb, var(--keep) 16%, var(--surface));
		}
		.pool-current.all::before {
			background: color-mix(in srgb, var(--text) 12%, var(--surface));
		}
	}
	:global(html[data-pointer='coarse']) .pool-current {
		position: relative;
		height: 44px;
		padding: 0 6px;
		border-color: transparent;
		background: transparent;
		isolation: isolate;
	}
	:global(html[data-pointer='coarse']) .pool-current.mix,
	:global(html[data-pointer='coarse']) .pool-current.picks,
	:global(html[data-pointer='coarse']) .pool-current.keeps,
	:global(html[data-pointer='coarse']) .pool-current.all {
		background: transparent;
	}
	:global(html[data-pointer='coarse']) .pool-current::before {
		content: '';
		position: absolute;
		z-index: -1;
		left: 0;
		right: 0;
		top: 4px;
		height: 36px;
		border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
	}
	:global(html[data-pointer='coarse']) .pool-current.mix::before {
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	:global(html[data-pointer='coarse']) .pool-current.picks::before {
		background: color-mix(in srgb, var(--primary) 14%, var(--surface));
	}
	:global(html[data-pointer='coarse']) .pool-current.keeps::before {
		background: color-mix(in srgb, var(--keep) 16%, var(--surface));
	}
	:global(html[data-pointer='coarse']) .pool-current.all::before {
		background: color-mix(in srgb, var(--text) 12%, var(--surface));
	}
</style>
