<script lang="ts">
	import { SignInPage } from 'overnightworks-design';
	import { SIGN_IN_START_PATH } from '#lib/api/fetch.ts';
	import { APP_NAME } from '#lib/constants/app.ts';
	import { legalLinks } from '#lib/utils/legal-links.ts';
	import { kitWords } from '#lib/utils/kit-words.ts';
</script>

<SignInPage
	appName={APP_NAME}
	state={{ page: 'signed-out', signInHref: SIGN_IN_START_PATH }}
	legalLinks={legalLinks()}
	words={kitWords()}
/>
