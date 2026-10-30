<script lang="ts">
	import { SignInPage } from 'overnightworks-appkit';
	import { SIGN_IN_START_PATH } from '#lib/api/fetch.ts';
	import { APP_NAME } from '#lib/constants.ts';
	import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
</script>

<SignInPage
	appName={APP_NAME}
	state={{ page: 'login-failed', signInHref: SIGN_IN_START_PATH }}
	legalLinks={LEGAL_SECTIONS}
/>
