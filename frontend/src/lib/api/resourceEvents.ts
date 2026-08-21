import { ApiError } from './fetch';
import { RESOURCE_EVENTS_PATH } from '$lib/constants';

export interface SseFrame {
	id: string | null;
	event: string;
	data: string;
}

export interface ResourceHelloEvent {
	type: 'hello';
	high_water_mark: number;
}

export interface ResourceResyncEvent {
	type: 'resync';
	high_water_mark: number;
}

export interface ResourceHeartbeatEvent {
	type: 'heartbeat';
}

export interface GenerationCreatedEvent {
	type: 'generation.created';
	kind: 'generation.created';
	sequence: number;
	user_id: string;
	resource_type: 'song';
	resource_id: string;
	song_id: string;
	generation_id: string;
	created_at: string;
}

export type ResourceStreamEvent =
	| ResourceHelloEvent
	| ResourceResyncEvent
	| ResourceHeartbeatEvent
	| GenerationCreatedEvent;

const AUTH_ENDPOINTS = ['/api/auth/login', '/api/auth/setup'];

export function consumeSseFrames(buffer: string): { frames: SseFrame[]; rest: string } {
	const frames: SseFrame[] = [];
	let rest = buffer;
	let boundary = rest.indexOf('\n\n');
	while (boundary !== -1) {
		const raw = rest.slice(0, boundary);
		rest = rest.slice(boundary + 2);
		const frame = parseSseFrame(raw.replace(/\r/g, ''));
		if (frame) frames.push(frame);
		boundary = rest.indexOf('\n\n');
	}
	return { frames, rest };
}

export function parseSseFrame(raw: string): SseFrame | null {
	let id: string | null = null;
	let event = 'message';
	let data = '';
	for (const line of raw.split('\n')) {
		if (!line || line.startsWith(':')) continue;
		if (line.startsWith('id:')) id = line.slice(3).trim();
		else if (line.startsWith('event:')) event = line.slice(6).trim();
		else if (line.startsWith('data:')) data = line.slice(5).trimStart();
	}
	if (!data) return null;
	return { id, event, data };
}

export function parseResourceStreamEvent(frame: SseFrame): ResourceStreamEvent {
	let parsed: unknown;
	try {
		parsed = JSON.parse(frame.data);
	} catch {
		throw new Error(`Malformed resource event: ${frame.event}`);
	}
	if (typeof parsed !== 'object' || parsed === null) {
		throw new Error(`Malformed resource event: ${frame.event}`);
	}
	const body = parsed as Record<string, unknown>;
	const type = typeof body.type === 'string' ? body.type : frame.event;
	if (type === 'hello') {
		return { type: 'hello', high_water_mark: requireInt(body, 'high_water_mark') };
	}
	if (type === 'resync') {
		return { type: 'resync', high_water_mark: requireInt(body, 'high_water_mark') };
	}
	if (type === 'heartbeat') {
		return { type: 'heartbeat' };
	}
	if (type === 'generation.created') {
		return {
			type: 'generation.created',
			kind: 'generation.created',
			sequence: requireInt(body, 'sequence'),
			user_id: requireString(body, 'user_id'),
			resource_type: 'song',
			resource_id: requireString(body, 'resource_id'),
			song_id: requireString(body, 'song_id'),
			generation_id: requireString(body, 'generation_id'),
			created_at: requireString(body, 'created_at')
		};
	}
	throw new Error(`Unknown resource event: ${type}`);
}

export async function* openResourceEventStream(
	lastEventId: number | null,
	signal: AbortSignal
): AsyncGenerator<ResourceStreamEvent> {
	const headers: Record<string, string> = { Accept: 'text/event-stream' };
	if (lastEventId !== null) {
		headers['Last-Event-ID'] = String(lastEventId);
	}
	const resp = await fetch(RESOURCE_EVENTS_PATH, {
		credentials: 'include',
		headers,
		signal
	});
	if (!resp.ok) {
		let detail = '';
		try {
			const body = await resp.json();
			detail = body.detail ?? '';
		} catch {
			detail = '';
		}
		if (resp.status === 401 && !AUTH_ENDPOINTS.includes(RESOURCE_EVENTS_PATH)) {
			const { clearAuth } = await import('$lib/stores/auth');
			const { goto } = await import('$app/navigation');
			clearAuth();
			await goto('/login');
		}
		throw new ApiError(resp.status, detail, RESOURCE_EVENTS_PATH);
	}
	if (!resp.body) {
		throw new Error('Resource event stream had no body');
	}
	const reader = resp.body.getReader();
	const decoder = new TextDecoder('utf-8');
	let buffer = '';
	while (true) {
		const { value, done } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		const consumed = consumeSseFrames(buffer);
		buffer = consumed.rest;
		for (const frame of consumed.frames) {
			yield parseResourceStreamEvent(frame);
		}
	}
}

function requireInt(body: Record<string, unknown>, key: string): number {
	const value = body[key];
	if (typeof value !== 'number' || !Number.isFinite(value)) {
		throw new Error(`Malformed resource event field: ${key}`);
	}
	return value;
}

function requireString(body: Record<string, unknown>, key: string): string {
	const value = body[key];
	if (typeof value !== 'string' || value.length === 0) {
		throw new Error(`Malformed resource event field: ${key}`);
	}
	return value;
}
