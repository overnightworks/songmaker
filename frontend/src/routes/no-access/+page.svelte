<script lang="ts">
	import { SignInPage } from 'overnightworks-design';
	import { APP_NAME } from '#lib/constants/app.ts';
	import { legalLinks } from '#lib/utils/legal-links.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { kitWords } from '#lib/utils/kit-words.ts';
	import { logout, signOutFailed } from '#lib/stores/auth.ts';
</script>

<SignInPage
	appName={APP_NAME}
	state={{
		page: 'no-access',
		onLogOut: () => void logout(),
		logOutFailure: $signOutFailed ? pageText('account.signOutFailed') : undefined
	}}
	legalLinks={legalLinks()}
	words={kitWords()}
/>
