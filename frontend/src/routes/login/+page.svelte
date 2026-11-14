<script lang="ts">
	import { SignInPage } from 'overnightworks-design';
	import { SIGN_IN_START_PATH } from '#lib/api/fetch.ts';
	import { legalLinks } from '#lib/utils/legal-links.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { kitWords } from '#lib/utils/kit-words.ts';
</script>

<SignInPage
	appName={pageText('app.name')}
	state={{ page: 'signed-out', signInHref: SIGN_IN_START_PATH }}
	legalLinks={legalLinks()}
	words={kitWords()}
/>
