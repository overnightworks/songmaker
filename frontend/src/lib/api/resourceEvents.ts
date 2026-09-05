import type {
	GenerationCreatedResourceEvent,
	ResourceHelloEvent,
	ResourceResyncEvent
} from './types';

const DECIMAL_ID = /^(0|[1-9]\d*)$/;

export function compareDecimalId(left: string, right: string): number {
	if (left === right) return 0;
	if (left.length !== right.length) return left.length < right.length ? -1 : 1;
	return left < right ? -1 : 1;
}

export function parseResourceHello(data: string): ResourceHelloEvent {
	const body = parseObject(data, 'hello');
	return { high_water_mark: requireDecimal(body, 'high_water_mark') };
}

export function parseResourceResync(data: string): ResourceResyncEvent {
	const body = parseObject(data, 'resync');
	return { high_water_mark: requireDecimal(body, 'high_water_mark') };
}

export function parseGenerationCreated(data: string): GenerationCreatedResourceEvent {
	const body = parseObject(data, 'generation.created');
	const kind = body.kind;
	if (kind !== 'generation.created') {
		throw new Error('Malformed resource event field: kind');
	}
	const resourceType = body.resource_type;
	if (resourceType !== 'song') {
		throw new Error('Malformed resource event field: resource_type');
	}
	return {
		kind: 'generation.created',
		sequence: requireDecimal(body, 'sequence'),
		resource_type: 'song',
		resource_id: requireString(body, 'resource_id'),
		generation_id: requireString(body, 'generation_id'),
		created_at: requireString(body, 'created_at')
	};
}

function parseObject(data: string, event: string): Record<string, unknown> {
	let parsed: unknown;
	try {
		parsed = JSON.parse(data);
	} catch {
		throw new Error(`Malformed resource event: ${event}`);
	}
	if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
		throw new Error(`Malformed resource event: ${event}`);
	}
	return parsed as Record<string, unknown>;
}

function requireDecimal(body: Record<string, unknown>, key: string): string {
	const value = body[key];
	if (typeof value !== 'string' || !DECIMAL_ID.test(value)) {
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
