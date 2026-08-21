export const COMPACT_SELECT_CLASS = 'compact-select';
export const COMPACT_STACK_CLASS = 'compact-stack';

export const COMPACT_UI_STYLE = `.${COMPACT_SELECT_CLASS} {
	width: 100%;
	max-width: 100%;
	min-width: 0;
	box-sizing: border-box;
}

.${COMPACT_STACK_CLASS} {
	display: block;
	width: 100%;
	max-width: 100%;
}

.${COMPACT_STACK_CLASS} thead {
	display: none;
}

.${COMPACT_STACK_CLASS} tbody {
	display: flex;
	flex-direction: column;
	gap: 0.75rem;
}

.${COMPACT_STACK_CLASS} tr {
	display: flex;
	flex-direction: column;
	gap: 0.25rem;
	padding: 0.75rem;
	border: 1px solid var(--border);
	border-radius: 6px;
	background: var(--surface);
}

.${COMPACT_STACK_CLASS} td {
	display: grid;
	grid-template-columns: minmax(4.5rem, 32%) minmax(0, 1fr);
	gap: 0.5rem;
	padding: 0.2rem 0;
	border-bottom: none;
	min-width: 0;
	overflow-wrap: anywhere;
	text-align: left;
}

.${COMPACT_STACK_CLASS} td::before {
	content: attr(data-label);
	color: var(--text-muted);
	font-size: 0.7rem;
	text-transform: uppercase;
	letter-spacing: 0.4px;
	padding-top: 0.15rem;
}

.${COMPACT_STACK_CLASS} td.actions,
.${COMPACT_STACK_CLASS} td.actions-col,
.${COMPACT_STACK_CLASS} td[colspan] {
	display: flex;
	flex-wrap: wrap;
	grid-template-columns: none;
	margin-top: 0.35rem;
}

.${COMPACT_STACK_CLASS} td.actions::before,
.${COMPACT_STACK_CLASS} td.actions-col::before,
.${COMPACT_STACK_CLASS} td[colspan]::before {
	content: none;
}

.${COMPACT_STACK_CLASS} tr.inline-form-row,
.${COMPACT_STACK_CLASS} tr.override-row {
	margin-top: -0.75rem;
	border-top-left-radius: 0;
	border-top-right-radius: 0;
	border-top: none;
}

.${COMPACT_STACK_CLASS} tr:has(+ .inline-form-row),
.${COMPACT_STACK_CLASS} tr:has(+ .override-row) {
	margin-bottom: 0;
	border-bottom-left-radius: 0;
	border-bottom-right-radius: 0;
}
`;

export function ensureCompactUiStyles(): void {
	if (typeof document === 'undefined') return;
	if (document.head.querySelector('[data-compact-ui]')) return;
	const sheet = document.createElement('style');
	sheet.dataset.compactUi = 'true';
	sheet.textContent = COMPACT_UI_STYLE;
	document.head.append(sheet);
}
