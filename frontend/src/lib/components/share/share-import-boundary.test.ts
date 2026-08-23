// Grep gate (plan amendment #4, issue #119): nothing the share surface
// mounts may runtime-import stores/player, navigation, editor, takeActions,
// or auth. A share route runs entirely logged out; pulling any of these in
// would drag in app-only state (or, for stores/player, the module-level
// audioPlayer callback wiring and the auth-redirect side effect) into a
// public page. `import type` (including a type-only re-export) is exempt —
// it never executes.
import { describe, expect, it } from 'vitest';

const SOURCE_FILES = import.meta.glob('/src/**/*.{ts,svelte}', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

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
].map((relative) => `/src/${relative}`);

const FORBIDDEN_MODULES = [
	'lib/stores/player.ts',
	'lib/stores/navigation.ts',
	'lib/stores/editor.ts',
	'lib/stores/takeActions.ts',
	'lib/stores/auth.ts'
].map((relative) => `/src/${relative}`);

// share's stream fetchers (lib/api/queue-streams.ts) call the public
// /shared/* endpoints with a bare fetch() and never through apiFetch() — see
// their implementation. apiFetch()'s 401 branch (the only thing in this file
// that reaches stores/auth) is therefore unreachable from the share surface,
// even though the module-level `import { apiFetch } from './fetch'` puts the
// whole file in the static graph. A per-export reachability walk would prove
// this properly; a two-line exemption is cheaper for one known false
// positive.
const DYNAMIC_IMPORT_EXEMPTIONS = new Set(['/src/lib/api/fetch.ts::$lib/stores/auth']);

const STATIC_IMPORT_RE = /import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/g;
const BARE_IMPORT_RE = /import\s+['"]([^'"]+)['"]/g;
const EXPORT_FROM_RE = /export\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/g;
const DYNAMIC_IMPORT_RE = /import\(\s*['"]([^'"]+)['"]\s*\)/g;

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
		base = `/src/lib/${specifier.slice('$lib/'.length)}`;
	} else if (specifier.startsWith('.')) {
		const dirParts = fromFile.split('/').slice(0, -1);
		for (const segment of specifier.split('/')) {
			if (segment === '' || segment === '.') continue;
			if (segment === '..') dirParts.pop();
			else dirParts.push(segment);
		}
		base = dirParts.join('/');
	} else {
		return null;
	}
	const candidates = [
		`${base}.ts`,
		`${base}.svelte`,
		`${base}.svelte.ts`,
		base,
		`${base}/index.ts`
	];
	return candidates.find((candidate) => candidate in SOURCE_FILES) ?? null;
}

function collectRuntimeImports(file: string, visited: Set<string>): void {
	if (visited.has(file)) return;
	visited.add(file);
	const content = SOURCE_FILES[file];
	if (content === undefined) return;

	for (const match of content.matchAll(STATIC_IMPORT_RE)) {
		const [, clause, specifier] = match;
		if (isTypeOnlyClause(clause)) continue;
		const resolved = resolveLocalSpecifier(specifier, file);
		if (resolved) collectRuntimeImports(resolved, visited);
	}
	for (const match of content.matchAll(EXPORT_FROM_RE)) {
		const [, clause, specifier] = match;
		if (isTypeOnlyClause(clause)) continue;
		const resolved = resolveLocalSpecifier(specifier, file);
		if (resolved) collectRuntimeImports(resolved, visited);
	}
	for (const match of content.matchAll(BARE_IMPORT_RE)) {
		const [, specifier] = match;
		const resolved = resolveLocalSpecifier(specifier, file);
		if (resolved) collectRuntimeImports(resolved, visited);
	}
	for (const match of content.matchAll(DYNAMIC_IMPORT_RE)) {
		const [, specifier] = match;
		if (DYNAMIC_IMPORT_EXEMPTIONS.has(`${file}::${specifier}`)) continue;
		const resolved = resolveLocalSpecifier(specifier, file);
		if (resolved) collectRuntimeImports(resolved, visited);
	}
}

describe('share surface import boundary', () => {
	for (const entry of ENTRY_FILES) {
		it(`${entry} never runtime-imports stores/player|navigation|editor|takeActions|auth`, () => {
			const visited = new Set<string>();
			collectRuntimeImports(entry, visited);

			const offenders = [...visited].filter((file) => FORBIDDEN_MODULES.includes(file));

			expect(offenders).toEqual([]);
		});
	}
});
