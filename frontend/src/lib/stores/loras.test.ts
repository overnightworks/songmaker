import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { NetworkError } from '$lib/api/fetch';

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
	anyLoraActive,
	isLoraActive,
	loadLoras,
	createLora,
	softDeleteLora,
	trainLora,
	refreshLora
} from './loras';

function makeLora(over: Record<string, unknown> = {}) {
	return {
		id: 'l1',
		user_id: 'u1',
		name: 'Voice',
		slug: 'voice',
		status: 'draft',
		model_mode: 'sft',
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
	});

	it('loadLoras hands a failure to its caller and keeps the voices it listed', async () => {
		loras.set([makeLora()]);
		const err = new NetworkError('/api/loras', new TypeError('Failed to fetch'));
		mockListLoras.mockRejectedValueOnce(err);

		await expect(loadLoras()).rejects.toBe(err);
		expect(get(loras)).toHaveLength(1);
	});

	it('loadLoras passes includeDeleted flag through', async () => {
		mockListLoras.mockResolvedValueOnce([]);
		await loadLoras(true);
		expect(mockListLoras).toHaveBeenCalledWith(true);
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
});
