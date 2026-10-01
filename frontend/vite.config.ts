import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const API_TARGET = 'http://localhost:8080';
const FONT_FILE_PATTERN = /\.woff2?$/;

function keepFontsAsFiles(filePath: string): false | undefined {
	return FONT_FILE_PATTERN.test(filePath) ? false : undefined;
}

export default defineConfig({
	plugins: [sveltekit()],
	build: {
		assetsInlineLimit: keepFontsAsFiles
	},
	server: {
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
			}
		}
	}
});
