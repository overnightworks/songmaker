import type { AuthUser } from './types';
import { apiFetch } from './fetch';

export async function fetchMe(): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/me');
}
