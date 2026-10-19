<script lang="ts">
	import { page } from '$app/state';
	import LegalPage from '$lib/components/LegalPage.svelte';
	import { LEGAL_SECTIONS, type LegalSection } from '$lib/components/LegalLinks.svelte';

	function sectionOfHash(hash: string): LegalSection {
		return LEGAL_SECTIONS.find(({ id }) => `#${id}` === hash)?.id ?? LEGAL_SECTIONS[0].id;
	}
</script>

<LegalPage title="Legal" section={sectionOfHash(page.url.hash)} />
