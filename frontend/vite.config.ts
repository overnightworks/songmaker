import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type Plugin } from 'vite';

const API_TARGET = process.env.SONGMAKER_API_TARGET;
const FONT_FILE_PATTERN = /\.woff2?$/;

function keepFontsAsFiles(filePath: string): false | undefined {
	return FONT_FILE_PATTERN.test(filePath) ? false : undefined;
}

// Only the dev server proxies; build, preview, check and install load this file without a target.
function requireApiTargetForDevServer(): Plugin {
	return {
		name: 'require-api-target-for-dev-server',
		configureServer() {
			if (!API_TARGET) {
				throw new Error(
					'SONGMAKER_API_TARGET is not set: point it at a probe stack (frontend/e2e/README.md, "Running it locally"), never the live stack on 8080'
				);
			}
		}
	};
}

export default defineConfig({
	plugins: [requireApiTargetForDevServer(), sveltekit()],
	build: {
		assetsInlineLimit: keepFontsAsFiles
	},
	server: {
		fs: { allow: ['kit-assets'] },
		proxy: {
			'/api': {
				target: API_TARGET,
				changeOrigin: true
			},
			'/ws': {
				target: API_TARGET,
				ws: true
			},
			'/audio': {
				target: API_TARGET,
				changeOrigin: true
			},
			'/shared': {
				target: API_TARGET,
				changeOrigin: true
			},
			'/login/oidc': {
				target: API_TARGET,
				changeOrigin: true
			},
			'/auth/logout': {
				target: API_TARGET,
				changeOrigin: true
			}
		}
	}
});
