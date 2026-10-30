import { vi, type Mock } from 'vitest';
import type { DocumentLoads } from '#lib/history/documentLoads.ts';

type DocumentLoadMocks = { [Load in keyof DocumentLoads]: Mock<DocumentLoads[Load]> };

// The stand-in for whole-document loads; install it with
// `standInForDocumentLoadsForTests`. A test passes only the loads it asserts on.
export function documentLoadsStandIn(
	overrides: Partial<DocumentLoadMocks> = {}
): DocumentLoadMocks {
	return { assign: vi.fn(), replace: vi.fn(), reload: vi.fn(), submitPost: vi.fn(), ...overrides };
}

// Each test file gets its own copy, because vitest isolates modules per file.
export const documentLoads = documentLoadsStandIn();
