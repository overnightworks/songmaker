import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

const mockListLoras = vi.fn();
const mockGetLora = vi.fn();
const mockCreateLora = vi.fn();
const mockSoftDelete = vi.fn();
const mockTrainLora = vi.fn();

vi.mock('$lib/api/loras', () => ({
	listLoras: (...a: unknown[]) => mockListLoras(...a),
	getLora: (...a: unknown[]) => mockGetLora(...a),
	createLora: (...a: unknown[]) => mockCreateLora(...a),
	softDeleteLora: (...a: unknown[]) => mockSoftDelete(...a),
	trainLora: (...a: unknown[]) => mockTrainLora(...a)
}));

import {
	loras,
	lorasError,
	readyLoras,
	anyLoraActive,
	isLoraActive,
	loadLoras,
	createLora,
	softDeleteLora,
	trainLora,
	refreshLora,
	applyLoraUpdate,
	getLoraById
} from './loras';

function makeLora(over: Record<string, unknown> = {}) {
	return {
		id: 'l1',
		user_id: 'u1',
		name: 'Voice',
		slug: 'voice',
		status: 'draft',
		created_at: '2026-01-01',
		deleted_at: null,
		samples: [],
		...over
	};
}

beforeEach(() => {
	mockListLoras.mockReset();
	mockGetLora.mockReset();
	mockCreateLora.mockReset();
	mockSoftDelete.mockReset();
	mockTrainLora.mockReset();
	loras.set([]);
	lorasError.set(null);
});

describe('LoRA store', () => {
	it('isLoraActive matches every active status', () => {
		expect(isLoraActive('draft')).toBe(false);
		expect(isLoraActive('ready')).toBe(false);
		expect(isLoraActive('failed')).toBe(false);
		expect(isLoraActive('queued')).toBe(true);
		expect(isLoraActive('preprocessing')).toBe(true);
		expect(isLoraActive('training')).toBe(true);
		expect(isLoraActive('exporting')).toBe(true);
	});

	it('loadLoras populates the store', async () => {
		mockListLoras.mockResolvedValueOnce([makeLora(), makeLora({ id: 'l2' })]);
		await loadLoras();
		expect(get(loras)).toHaveLength(2);
		expect(get(lorasError)).toBeNull();
	});

	it('loadLoras captures error message and rethrows', async () => {
		mockListLoras.mockRejectedValueOnce(new Error('boom'));
		await expect(loadLoras()).rejects.toThrow('boom');
		expect(get(lorasError)).toBe('boom');
	});

	it('loadLoras passes includeDeleted flag through', async () => {
		mockListLoras.mockResolvedValueOnce([]);
		await loadLoras(true);
		expect(mockListLoras).toHaveBeenCalledWith(true);
	});

	it('readyLoras derives only ready non-deleted entries', () => {
		loras.set([
			makeLora({ id: 'a', status: 'ready' }),
			makeLora({ id: 'b', status: 'training' }),
			makeLora({ id: 'c', status: 'ready', deleted_at: '2026-01-02' }),
			makeLora({ id: 'd', status: 'failed' })
		]);
		const ready = get(readyLoras);
		expect(ready.map((l) => l.id)).toEqual(['a']);
	});

	it('anyLoraActive is true when any is active', () => {
		loras.set([makeLora({ status: 'draft' })]);
		expect(get(anyLoraActive)).toBe(false);
		loras.set([makeLora({ status: 'training' })]);
		expect(get(anyLoraActive)).toBe(true);
	});

	it('createLora appends to the list', async () => {
		const created = makeLora({ id: 'new' });
		mockCreateLora.mockResolvedValueOnce(created);
		await createLora('Voice');
		expect(get(loras)).toHaveLength(1);
		expect(get(loras)[0].id).toBe('new');
	});

	it('softDeleteLora marks deleted_at locally', async () => {
		loras.set([makeLora({ id: 'x' })]);
		mockSoftDelete.mockResolvedValueOnce(undefined);
		await softDeleteLora('x');
		expect(get(loras)[0].deleted_at).not.toBeNull();
	});

	it('trainLora updates entry with new status', async () => {
		loras.set([makeLora({ id: 'x', status: 'draft' })]);
		mockTrainLora.mockResolvedValueOnce(makeLora({ id: 'x', status: 'queued' }));
		await trainLora('x');
		expect(get(loras)[0].status).toBe('queued');
	});

	it('refreshLora updates an existing entry in place', async () => {
		loras.set([makeLora({ id: 'x', name: 'Old' })]);
		mockGetLora.mockResolvedValueOnce(makeLora({ id: 'x', name: 'New' }));
		await refreshLora('x');
		expect(get(loras)[0].name).toBe('New');
	});

	it('refreshLora appends when id is unknown', async () => {
		loras.set([]);
		mockGetLora.mockResolvedValueOnce(makeLora({ id: 'x' }));
		await refreshLora('x');
		expect(get(loras)).toHaveLength(1);
	});

	it('applyLoraUpdate inserts or updates', () => {
		loras.set([makeLora({ id: 'a', name: 'A' })]);
		applyLoraUpdate(makeLora({ id: 'a', name: 'A2' }));
		expect(get(loras)[0].name).toBe('A2');
		applyLoraUpdate(makeLora({ id: 'b', name: 'B' }));
		expect(get(loras)).toHaveLength(2);
	});

	it('getLoraById returns the matching entry', () => {
		loras.set([makeLora({ id: 'a' }), makeLora({ id: 'b' })]);
		expect(getLoraById('b')?.id).toBe('b');
		expect(getLoraById('c')).toBeUndefined();
	});
});
