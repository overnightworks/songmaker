<script lang="ts">
	import {
		LIBRARY_TAKE_POOLS,
		LIBRARY_TAKE_POOL_LABELS,
		libraryTakePool,
		type LibraryTakePool
	} from '$lib/stores/playbackSettings';
	import { chooseLibraryTakePool, queueContext } from '$lib/stores/player';
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

	$effect(() => {
		if (typeof window === 'undefined') return;
		const media = window.matchMedia('(max-width: 640px)');
		narrow = media.matches;
		const onChange = () => {
			narrow = media.matches;
			if (!media.matches) sheetOpen = false;
		};
		media.addEventListener('change', onChange);
		return () => media.removeEventListener('change', onChange);
	});

	function selectPool(next: LibraryTakePool): void {
		sheetOpen = false;
		void chooseLibraryTakePool(next);
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

{#if onLibrary}
	<div class="pool-control">
		{#if narrow}
			<button
				class="pool-current"
				class:mix={pool === 'mix'}
				class:picks={pool === 'picks'}
				class:keeps={pool === 'keeps'}
				class:all={pool === 'all'}
				onclick={() => (sheetOpen = !sheetOpen)}
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
		<button
			class="pool-info"
			onclick={() => (helpOpen = !helpOpen)}
			aria-expanded={helpOpen}
			aria-label="What Mix Picks Keeps Alle mean"
			title="What Mix Picks Keeps Alle mean"
		>
			<Icon name="info" size={15} />
		</button>
		{#if helpOpen}
			<p class="pool-help">{POOL_HELP}</p>
		{/if}
	</div>
	{#if sheetOpen}
		<div class="pool-sheet" role="dialog" aria-label="Take pool" tabindex="-1">
			{#each LIBRARY_TAKE_POOLS as option (option)}
				<button class="sheet-btn" class:active={pool === option} onclick={() => selectPool(option)}>
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
	.pool-sheet {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--player-height);
		display: flex;
		gap: 8px;
		justify-content: center;
		padding: 0.7rem 0.8rem calc(0.7rem + env(safe-area-inset-bottom, 0px));
		background: var(--header-bg);
		border-top: 1px solid var(--border);
		z-index: 110;
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
</style>
