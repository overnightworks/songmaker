<script lang="ts">
	import type { SongItem } from '#lib/api/types.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	interface Props {
		song: SongItem;
		onconfirm: () => void;
		oncancel: () => void;
	}

	let { song, onconfirm, oncancel }: Props = $props();
</script>

<ConfirmDeleteDialog
	title={pageText('songPage.deleteTitle', { title: song.title })}
	items={[
		pageText('songPage.deleteTakes', song.generation_count),
		pageText('songPage.deleteVersions', song.version_count),
		pageText('songPage.deleteHistory')
	]}
	confirmLabel={pageText('songPage.deleteConfirm')}
	{onconfirm}
	{oncancel}
/>
