import { writable, derived } from 'svelte/store';
import type { AuthUser } from '$lib/api/types';
import { fetchMe, login as apiLogin, logout as apiLogout } from '$lib/api/client';

export const currentUser = writable<AuthUser | null>(null);
export const authLoading = writable(true);
export const authError = writable('');
export const isAdmin = derived(currentUser, (u) => u?.role === 'admin');

export async function checkAuth(): Promise<AuthUser | null> {
	authLoading.set(true);
	try {
		const user = await fetchMe();
		currentUser.set(user);
		return user;
	} catch {
		currentUser.set(null);
		return null;
	} finally {
		authLoading.set(false);
	}
}

export async function login(username: string, password: string): Promise<AuthUser> {
	authError.set('');
	try {
		const user = await apiLogin(username, password);
		currentUser.set(user);
		return user;
	} catch (err) {
		const msg = err instanceof Error ? err.message : 'Login failed';
		if (msg.includes('429')) {
			authError.set('Too many attempts. Try again later.');
		} else if (msg.includes('401')) {
			authError.set('Invalid username or password.');
		} else {
			authError.set(msg);
		}
		throw err;
	}
}

export async function logout(): Promise<void> {
	try {
		await apiLogout();
	} catch {
		// swallow — always clear local state
	} finally {
		currentUser.set(null);
	}
}
