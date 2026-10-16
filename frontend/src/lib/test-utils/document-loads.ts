import { vi } from 'vitest';

// The stand-in for whole-document loads (`location.assign`, `replace`, `reload`);
// install it with `standInForDocumentLoadsForTests`. Each test file gets its own
// copy, because vitest isolates modules per file.
export const documentLoads = { assign: vi.fn(), replace: vi.fn(), reload: vi.fn() };
