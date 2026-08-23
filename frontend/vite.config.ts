import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const API_TARGET = 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit()],
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
