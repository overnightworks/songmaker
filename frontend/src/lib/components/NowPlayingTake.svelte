<script lang="ts">
	import type { GenerationItem, SongItem } from '$lib/api/types';

	let {
		generation,
		song,
		lyrics
	}: {
		generation: GenerationItem;
		song: SongItem;
		lyrics: string | null;
	} = $props();
</script>

<!-- Phase 4 (issue #101) fills in the judging panel: scores, sung-vs-lyrics
     deviations, pick/keep, rating, and pin seed. -->
<div
	class="np-take"
	data-generation-id={generation.id}
	data-song-id={song.id}
	data-has-lyrics={lyrics != null}
></div>
