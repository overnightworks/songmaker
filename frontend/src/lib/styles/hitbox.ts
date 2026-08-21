import { HITBOX_COMPACT_PX, HITBOX_FREQUENT_PX } from '$lib/constants';

export const HITBOX_STYLE = `:root {
	--hitbox-frequent: ${HITBOX_FREQUENT_PX}px;
	--hitbox-compact: ${HITBOX_COMPACT_PX}px;
}

[data-hitbox='frequent'] {
	box-sizing: border-box;
	position: relative;
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: var(--hitbox-compact);
	min-height: var(--hitbox-compact);
	margin: 0;
	padding: 0;
	flex-shrink: 0;
	isolation: isolate;
	cursor: pointer;
}

[data-hitbox='frequent']:disabled {
	cursor: default;
}

[data-hitbox='frequent']:focus-visible {
	outline-offset: -2px;
}

[data-hitbox='frequent']:active:not(:disabled)::before {
	transform: translate(-50%, -50%) scale(0.97);
}

@media (any-pointer: coarse) {
	[data-hitbox='frequent'] {
		min-width: var(--hitbox-frequent);
		min-height: var(--hitbox-frequent);
	}
}

html[data-pointer='coarse'] [data-hitbox='frequent'] {
	min-width: var(--hitbox-frequent);
	min-height: var(--hitbox-frequent);
}

html[data-pointer='fine'] [data-hitbox='frequent'] {
	min-width: var(--hitbox-compact);
	min-height: var(--hitbox-compact);
}

[data-hitbox='frequent'][data-hitbox-face] {
	background: transparent;
	border-style: none;
}

[data-hitbox='frequent'][data-hitbox-face]::before {
	content: '';
	position: absolute;
	top: 50%;
	left: 50%;
	width: var(--hitbox-compact);
	height: var(--hitbox-compact);
	transform: translate(-50%, -50%);
	border: 1px solid var(--border);
	border-radius: var(--btn-radius-sm);
	background: color-mix(in srgb, var(--surface) 80%, transparent);
	pointer-events: none;
	z-index: -1;
	box-sizing: border-box;
}

[data-hitbox='frequent'][data-hitbox-face]:hover:not(:disabled)::before {
	border-color: currentColor;
}
`;
