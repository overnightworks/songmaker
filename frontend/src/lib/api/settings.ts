import type {
	Capabilities,
	CowriterSettings,
	PresetItem,
	RateLimitsResponse,
	UserRateLimitsResponse,
	VersionGenerationParams
} from './types';
import { apiFetch } from './fetch';

export async function fetchCapabilities(): Promise<Capabilities> {
	return apiFetch<Capabilities>('/api/capabilities');
}

export async function fetchGenerationDefaults(): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-defaults');
}

export async function updateGenerationDefaults(
	data: Record<string, VersionGenerationParams>
): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-defaults', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export interface ModelCapabilities {
	defaults: Record<string, unknown>;
	max_inference_steps: number;
	hidden_params: string[];
}

export interface AvailableModel {
	id: string;
	is_active: boolean;
	capabilities?: ModelCapabilities | null;
}

export async function fetchActiveModels(): Promise<AvailableModel[]> {
	return apiFetch<AvailableModel[]>('/api/settings/models');
}

export async function fetchAllModels(): Promise<AvailableModel[]> {
	return apiFetch<AvailableModel[]>('/api/settings/models/all');
}

export async function toggleModel(modelId: string, active: boolean): Promise<AvailableModel> {
	return apiFetch<AvailableModel>(`/api/settings/models/${modelId}?active=${active}`, {
		method: 'PUT'
	});
}

export interface ClaudeModelsResponse {
	chat_model: string;
	scoring_model: string;
	allowed_models: string[];
}

export async function fetchClaudeModels(): Promise<ClaudeModelsResponse> {
	return apiFetch<ClaudeModelsResponse>('/api/settings/claude-models');
}

export async function updateClaudeModels(
	chat_model: string,
	scoring_model: string
): Promise<ClaudeModelsResponse> {
	return apiFetch<ClaudeModelsResponse>('/api/settings/claude-models', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ chat_model, scoring_model })
	});
}

export async function fetchCowriterSettings(): Promise<CowriterSettings> {
	return apiFetch<CowriterSettings>('/api/settings/cowriter');
}

export async function updateCowriterSettings(
	provider: string,
	model: string,
	tailTokenBudget?: number
): Promise<CowriterSettings> {
	return apiFetch<CowriterSettings>('/api/settings/cowriter', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			provider,
			model,
			tail_token_budget: tailTokenBudget
		})
	});
}

export async function fetchBuiltinDefaults(): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-builtins');
}

export async function fetchDefaultConfig(): Promise<{ config: string | null }> {
	return apiFetch<{ config: string | null }>('/api/settings/default-config');
}

export async function updateDefaultConfig(
	config: string | null
): Promise<{ config: string | null }> {
	return apiFetch<{ config: string | null }>('/api/settings/default-config', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ config })
	});
}

export async function fetchPresets(): Promise<PresetItem[]> {
	return apiFetch<PresetItem[]>('/api/settings/presets');
}

export async function createPreset(
	name: string,
	model_mode: string,
	params: VersionGenerationParams,
	is_default: boolean = false
): Promise<PresetItem> {
	return apiFetch<PresetItem>('/api/settings/presets', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, model_mode, params, is_default })
	});
}

export async function updatePreset(
	presetId: string,
	data: { name?: string; params?: VersionGenerationParams; is_default?: boolean }
): Promise<PresetItem> {
	return apiFetch<PresetItem>(`/api/settings/presets/${presetId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export async function deletePresetApi(presetId: string): Promise<void> {
	await apiFetch(`/api/settings/presets/${presetId}`, { method: 'DELETE' });
}

export async function setPresetDefault(presetId: string): Promise<PresetItem> {
	return apiFetch<PresetItem>(`/api/settings/presets/${presetId}/set-default`, {
		method: 'POST'
	});
}

export async function fetchRateLimits(): Promise<RateLimitsResponse> {
	return apiFetch<RateLimitsResponse>('/api/settings/rate-limits');
}

export async function updateRateLimits(
	settings: Record<string, number>
): Promise<RateLimitsResponse> {
	return apiFetch<RateLimitsResponse>('/api/settings/rate-limits', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings })
	});
}

export async function fetchUserRateLimits(userId: string): Promise<UserRateLimitsResponse> {
	return apiFetch<UserRateLimitsResponse>(`/api/settings/rate-limits/user/${userId}`);
}

export async function updateUserRateLimits(
	userId: string,
	settings: Record<string, number>
): Promise<UserRateLimitsResponse> {
	return apiFetch<UserRateLimitsResponse>(`/api/settings/rate-limits/user/${userId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings })
	});
}

export async function deleteUserRateLimits(userId: string): Promise<void> {
	await apiFetch(`/api/settings/rate-limits/user/${userId}`, { method: 'DELETE' });
}
