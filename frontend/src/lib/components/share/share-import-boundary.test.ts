// Grep gate (plan amendment #4, issue #119): nothing the share surface
// mounts may runtime-import stores/player, navigation, editor, takeActions,
// or auth. A share route runs entirely logged out; pulling any of these in
// would drag in app-only state (or, for stores/player, the module-level
// audioPlayer callback wiring and the auth-redirect side effect) into a
// public page. `import type` is exempt — it never executes.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

const ENTRY_FILES = [
	'routes/share/[slug]/+page.svelte',
	'routes/share/playlist/[slug]/+page.svelte',
	'routes/share/song/[slug]/+page.svelte',
	'routes/share/gen/[slug]/+page.svelte',
	'lib/components/share/SharedCollection.svelte',
	'lib/components/share/SharedFooter.svelte',
	'lib/share/sharedCollection.ts',
	'lib/share/sharePlayback.svelte.ts',
	'lib/components/CollectionHeaderFrame.svelte',
	'lib/components/TransportBarFrame.svelte',
	'lib/components/NowPlayingFrame.svelte',
	'lib/components/NowPlayingQueue.svelte'
];

const FORBIDDEN_MODULES = [
	'lib/stores/player.ts',
	'lib/stores/navigation.ts',
	'lib/stores/editor.ts',
	'lib/stores/takeActions.ts',
	'lib/stores/auth.ts'
].map((relative) => join(SRC_ROOT, relative));

const IMPORT_RE = /import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/g;

function isTypeOnlyClause(clause: string): boolean {
	const trimmed = clause.trim();
	if (trimmed.startsWith('type ')) return true;
	const braceMatch = trimmed.match(/^\{([\s\S]*)\}$/);
	if (!braceMatch) return false;
	const members = braceMatch[1]
		.split(',')
		.map((member) => member.trim())
		.filter(Boolean);
	return members.length > 0 && members.every((member) => member.startsWith('type '));
}

function resolveLocalSpecifier(specifier: string, fromFile: string): string | null {
	let base: string;
	if (specifier.startsWith('$lib/')) {
		base = join(SRC_ROOT, 'lib', specifier.slice('$lib/'.length));
	} else if (specifier.startsWith('.')) {
		base = resolve(dirname(fromFile), specifier);
	} else {
		return null;
	}
	const candidates = [
		`${base}.ts`,
		`${base}.svelte`,
		`${base}.svelte.ts`,
		base,
		join(base, 'index.ts')
	];
	return (
		candidates.find((candidate) => existsSync(candidate) && statSync(candidate).isFile()) ?? null
	);
}

function collectRuntimeImports(file: string, visited: Set<string>): void {
	if (visited.has(file)) return;
	visited.add(file);
	const content = readFileSync(file, 'utf-8');
	for (const match of content.matchAll(IMPORT_RE)) {
		const [, clause, specifier] = match;
		if (isTypeOnlyClause(clause)) continue;
		const resolved = resolveLocalSpecifier(specifier, file);
		if (resolved) collectRuntimeImports(resolved, visited);
	}
}

describe('share surface import boundary', () => {
	for (const entry of ENTRY_FILES) {
		it(`${entry} never runtime-imports stores/player|navigation|editor|takeActions|auth`, () => {
			const visited = new Set<string>();
			collectRuntimeImports(join(SRC_ROOT, entry), visited);

			const offenders = [...visited].filter((file) => FORBIDDEN_MODULES.includes(file));

			expect(offenders).toEqual([]);
		});
	}
});
