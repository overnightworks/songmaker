<script lang="ts">
	import type { GenerationItem, ShareResult } from '#lib/api/types.ts';
	import { takeVersion } from '#lib/constants/now-playing.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
	import { rescoringTakeIds } from '#lib/stores/takeActions.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import AddToPicker from '../AddToPicker.svelte';
	import Icon from '../Icon.svelte';
	import MenuPopover from '../MenuPopover.svelte';
	import ShareRowContent from '../ShareRowContent.svelte';

	interface Props {
		gen: GenerationItem;
		onopenversion: (versionId: string) => void;
		ongotosong: () => void;
		onrepaint: () => void;
		oncover: () => void;
		onuseseed: () => void;
		onrescore: () => void;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		onaddto: (playlistId: string) => void;
		onrestore: () => void;
		// Only the editor deletes a take; Now Playing leaves it out.
		ondelete?: () => void;
	}

	let {
		gen,
		onopenversion,
		ongotosong,
		onrepaint,
		oncover,
		onuseseed,
		onrescore,
		onshare,
		onunshare,
		onaddto,
		onrestore,
		ondelete
	}: Props = $props();

	const takeLabel = $derived(
		gen.version_number !== null
			? pageText('takeMenu.headingWithVersion', {
					version: String(gen.version_number),
					take: String(gen.generation_number)
				})
			: pageText('takeMenu.heading', { take: String(gen.generation_number) })
	);

	const openableVersion = $derived(takeVersion(gen.version_id, gen.version_number));
	const rescoring = $derived($rescoringTakeIds.has(gen.id));

	const shareToggle = createShareToggle(() => ({
		kind: 'gen',
		isShared: gen.is_shared,
		shareSlug: gen.share_slug,
		onshare,
		onunshare
	}));

	let popover: MenuPopover | undefined = $state();
	let adding = $state(false);

	function addToAndClose(playlistId: string): void {
		popover?.close();
		onaddto(playlistId);
	}

	function runAndClose(action: () => void): void {
		popover?.close();
		action();
	}
</script>

<MenuPopover
	bind:this={popover}
	layer="take-menu"
	label={pageText('takeMenu.label')}
	closeLabel={pageText('takeMenu.close')}
	hitboxFace
	onclose={() => (adding = false)}
>
	{#snippet trigger()}<Icon name="more-horizontal" size={16} />{/snippet}
	{#if adding}
		<AddToPicker onselect={addToAndClose} onback={() => (adding = false)} />
	{:else}
		<p class="menu-heading">{takeLabel}</p>
		{#if openableVersion}
			{@const versionId = openableVersion.versionId}
			<button class="menu-item" onclick={() => runAndClose(() => onopenversion(versionId))}>
				<Icon name="file-music" size={14} />
				{pageText('takeMenu.openVersion')}
			</button>
		{:else}
			<button class="menu-item" onclick={() => runAndClose(ongotosong)}>
				<Icon name="file-music" size={14} />
				{pageText('takeMenu.goToSong')}
			</button>
		{/if}
		<button class="menu-item" onclick={() => runAndClose(onrepaint)}>
			<Icon name="paintbrush" size={14} />
			{pageText('takeMenu.repaint')}
		</button>
		<button class="menu-item" onclick={() => runAndClose(oncover)}>
			<Icon name="layers" size={14} />
			{pageText('takeMenu.cover')}
		</button>
		{#if gen.seed != null}
			<button class="menu-item" onclick={() => runAndClose(onuseseed)}>
				<Icon name="pin" size={14} />
				{pageText('takeMenu.useSeed')}
				<span class="menu-item-hint">{gen.seed}</span>
			</button>
		{/if}
		<button class="menu-item" disabled={rescoring} onclick={() => runAndClose(onrescore)}>
			<Icon name="refresh-cw" size={14} />
			{pageText('takeMenu.rescore')}
		</button>
		{#if gen.is_archived}
			<button class="menu-item" onclick={() => runAndClose(onrestore)}>
				<Icon name="archive-restore" size={14} />
				{pageText('takeMenu.restore')}
			</button>
		{:else}
			<button class="menu-item opens-list" onclick={() => (adding = true)}>
				<Icon name="list-plus" size={14} />
				{pageText('takeMenu.addTo')}
			</button>
		{/if}
		{#if !gen.is_archived || gen.is_shared}
			<button
				class="menu-item"
				aria-pressed={gen.is_shared}
				aria-busy={shareToggle.busy}
				title={shareToggle.sharedTooltip}
				onclick={shareToggle.toggle}
			>
				<ShareRowContent
					label={pageText('takeMenu.share')}
					hint={pageText(gen.is_shared ? 'takeMenu.shareOn' : 'takeMenu.shareOff')}
					iconName={shareToggle.iconName}
					isShared={gen.is_shared}
					busy={shareToggle.busy}
				/>
			</button>
		{/if}
		{#if ondelete}
			<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
				<Icon name="trash" size={14} />
				{pageText('takeMenu.delete')}
			</button>
		{/if}
	{/if}
</MenuPopover>
