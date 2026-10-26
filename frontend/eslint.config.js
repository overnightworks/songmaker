import eslint from '@eslint/js';
import prettier from 'eslint-config-prettier';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

// #925 G2. lib/api is the transport: it reports what the server answered and
// never reaches into stores, components, services, history or the router.
// After a leading `./`, a `.` or `..` path segment is refused wherever it
// stands, so no path can step out and back in; dots inside a name are fine.
// A module in a lib/api subfolder imports upwards as `$lib/api/…`. Forms whose
// target cannot be read from the source -- import(), an import() type,
// import.meta.glob -- are refused outright rather than checked.
// The wire shapes come from the generator: a hand-written interface or object
// type in lib/api is a twin of an api_models model that drifts unseen; a
// frontend-only call shape carries a reasoned line marker. types.ts is the
// generator's own output, so its block keeps only the transport selectors.
// The transport block must stay the last one that sets no-restricted-imports
// for these files; the later no-restricted-syntax block re-states the
// transport selectors, because a later block replaces its options.
const PATH_SEGMENT = String.raw`(?!\.\.?(?:/|$))[\w.+-]+`;
const PATH = `${PATH_SEGMENT}(?:/${PATH_SEGMENT})*`;
const TRANSPORT_MAY_IMPORT = [
	String.raw`\./${PATH}`,
	String.raw`\$lib/(?:api|constants)(?:/${PATH})?`,
	String.raw`\$lib/routes/${PATH}`,
	String.raw`\$lib/utils/recency`,
	String.raw`(?:@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*(?:/${PATH})?`
];
const OUTSIDE_THE_TRANSPORT = `^(?!(?:${TRANSPORT_MAY_IMPORT.join('|')})$)`;
const TRANSPORT_LAYER_MESSAGE =
	'lib/api is the transport (#925 G2): import only from ./, $lib/api, $lib/constants, ' +
	'$lib/routes/, $lib/utils/recency or a package, with no "." or ".." path segment ' +
	'after a leading "./". Hand the app what it needs through a reaction it installs.';
const TRANSPORT_LOADS_NOTHING_LAZILY =
	'lib/api is the transport (#925 G2): import() hides its target from lint. ' +
	'Write a static `import` from an allowed module instead.';
const TRANSPORT_TYPES_ARE_IMPORTED_BY_NAME =
	'lib/api is the transport (#925 G2): an import() type hides its target from lint. ' +
	"Write `import type { X } from '…'` beside the other imports instead.";
const TRANSPORT_READS_NO_IMPORT_META =
	'lib/api is the transport (#925 G2): import.meta (import.meta.glob included) ' +
	'reaches modules lint cannot read. Keep it out of lib/api.';
const TRANSPORT_SYNTAX = [
	{ selector: 'ImportExpression', message: TRANSPORT_LOADS_NOTHING_LAZILY },
	{ selector: 'TSImportType', message: TRANSPORT_TYPES_ARE_IMPORTED_BY_NAME },
	{ selector: "MetaProperty[meta.name='import']", message: TRANSPORT_READS_NO_IMPORT_META }
];
const NO_HAND_WRITTEN_WIRE_SHAPE =
	'lib/api declares no wire shape: import the generated type from ./types, ' +
	'or add the model to api_models.';
const WIRE_SHAPE_SYNTAX = ['TSInterfaceDeclaration', 'TSTypeLiteral'].map((selector) => ({
	selector,
	message: NO_HAND_WRITTEN_WIRE_SHAPE
}));

// #925 G3. Only the transport calls fetch; the named media owners and service worker
// retain their direct reads. Tests stub the boundary.
// checkGlobalObject also refuses window.fetch, globalThis.fetch and self.fetch.
// #1006 H6d. Only lib/history/historyController.ts writes or traverses history; tests
// drive and fake the browser's history. checkGlobalObject also refuses window.history.
// goto(..., { replaceState }) stays allowed. The import rule below sits before the
// lib/api block, which stays the last to set no-restricted-imports.
// Keep these the last blocks setting no-restricted-globals for these files: a later
// block replaces its options, so each file set lists every global it refuses.
const RAW_FETCH_MESSAGE =
	'Only lib/api/fetch.ts calls fetch (#925 G3): call a lib/api function, or add one there.';
const RAW_HISTORY_MESSAGE =
	'Only lib/history/historyController.ts writes or traverses history (#1006): ' +
	'call a controller function, or add one there.';
const RAW_FETCH = { name: 'fetch', message: RAW_FETCH_MESSAGE };
const RAW_HISTORY = { name: 'history', message: RAW_HISTORY_MESSAGE };
const refusedGlobals = (...globals) => ['error', { globals, checkGlobalObject: true }];

export default ts.config(
	{ linterOptions: { reportUnusedDisableDirectives: 'error' } },
	eslint.configs.recommended,
	...ts.configs.strict,
	...svelte.configs.recommended,
	prettier,
	...svelte.configs.prettier,
	{
		languageOptions: {
			globals: {
				...globals.browser,
				...globals.node
			}
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts'],
		languageOptions: {
			parserOptions: {
				parser: ts.parser
			}
		}
	},
	{
		rules: {
			'@typescript-eslint/no-unused-vars': [
				'error',
				{ argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
			]
		}
	},
	{
		files: ['src/**'],
		ignores: ['src/lib/history/historyController.ts', 'src/**/*.test.ts', 'src/lib/test-utils/**'],
		rules: {
			'no-restricted-imports': [
				'error',
				{
					paths: [
						{
							name: '$app/navigation',
							importNames: ['pushState', 'replaceState'],
							message: RAW_HISTORY_MESSAGE
						}
					]
				}
			]
		}
	},
	{
		files: ['src/lib/api/**'],
		ignores: ['src/lib/api/**/*.test.ts'],
		rules: {
			'no-restricted-imports': [
				'error',
				{
					patterns: [
						{ regex: OUTSIDE_THE_TRANSPORT, caseSensitive: true, message: TRANSPORT_LAYER_MESSAGE }
					]
				}
			],
			'no-restricted-syntax': ['error', ...TRANSPORT_SYNTAX, ...WIRE_SHAPE_SYNTAX]
		}
	},
	{
		// The wire shapes are declared here by definition: generated by scripts/generate_types.py.
		files: ['src/lib/api/types.ts'],
		rules: { 'no-restricted-syntax': ['error', ...TRANSPORT_SYNTAX] }
	},
	{
		files: ['src/**'],
		ignores: [
			'src/lib/api/fetch.ts',
			'src/lib/services/audioPlayer.svelte.ts',
			'src/service-worker.ts',
			'src/lib/history/historyController.ts',
			'src/**/*.test.ts',
			'src/lib/test-utils/**'
		],
		rules: { 'no-restricted-globals': refusedGlobals(RAW_FETCH, RAW_HISTORY) }
	},
	{
		files: [
			'src/lib/api/fetch.ts',
			'src/lib/services/audioPlayer.svelte.ts',
			'src/service-worker.ts'
		],
		ignores: ['src/**/*.test.ts'],
		rules: { 'no-restricted-globals': refusedGlobals(RAW_HISTORY) }
	},
	{
		files: ['src/lib/history/historyController.ts', 'src/lib/test-utils/**'],
		ignores: ['src/**/*.test.ts'],
		rules: { 'no-restricted-globals': refusedGlobals(RAW_FETCH) }
	},
	{
		ignores: [
			'build/',
			'.svelte-kit/',
			'dist/',
			'playwright-report/',
			'test-results/',
			'blob-report/',
			'e2e/.artifacts/'
		]
	}
);
