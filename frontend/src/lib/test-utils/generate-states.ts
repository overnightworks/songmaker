import type { GenerateState } from '$lib/stores/generateAction';

export const running: Extract<GenerateState, { kind: 'generating' }> = {
	kind: 'generating',
	indeterminate: false,
	elapsedLabel: null,
	jobId: 'job1',
	phase: 'Rendering',
	takeCounter: 'Take 1 of 2',
	progress: 36,
	readout: '36% · ~1:40',
	ended: false,
	reconnecting: false,
	offline: false
};

export const queued: Extract<GenerateState, { kind: 'queued' }> = {
	kind: 'queued',
	jobId: 'job1',
	label: 'Queued #3',
	reason: 'Waiting for LoRA training on this GPU.',
	reconnecting: false,
	offline: false
};

export const failed: Extract<GenerateState, { kind: 'failed' }> = {
	kind: 'failed',
	cause: 'Worker error',
	unavailable: false
};
