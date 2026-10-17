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
// This block must stay the last one that sets no-restricted-imports or
// no-restricted-syntax for these files: a later block replaces its options.
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

export default ts.config(
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
			'no-restricted-syntax': [
				'error',
				{ selector: 'ImportExpression', message: TRANSPORT_LOADS_NOTHING_LAZILY },
				{ selector: 'TSImportType', message: TRANSPORT_TYPES_ARE_IMPORTED_BY_NAME },
				{ selector: "MetaProperty[meta.name='import']", message: TRANSPORT_READS_NO_IMPORT_META }
			]
		}
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
