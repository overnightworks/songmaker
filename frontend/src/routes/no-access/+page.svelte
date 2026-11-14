<script lang="ts">
	import { SignInPage } from 'overnightworks-design';
	import { legalLinks } from '#lib/utils/legal-links.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { kitWords } from '#lib/utils/kit-words.ts';
	import { logout, signOutFailed } from '#lib/stores/auth.ts';
</script>

<SignInPage
	appName={pageText('app.name')}
	state={{
		page: 'no-access',
		onLogOut: () => void logout(),
		logOutFailure: $signOutFailed ? pageText('account.signOutFailed') : undefined
	}}
	legalLinks={legalLinks()}
	words={kitWords()}
/>
