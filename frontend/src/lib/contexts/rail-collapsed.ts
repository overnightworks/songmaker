import { getContext, setContext } from 'svelte';

const RAIL_COLLAPSED_KEY = Symbol('rail-collapsed');
type RailCollapsed = () => boolean;

export function setRailCollapsed(isCollapsed: RailCollapsed): void {
	setContext(RAIL_COLLAPSED_KEY, isCollapsed);
}

export function getRailCollapsed(): RailCollapsed {
	return getContext<RailCollapsed | undefined>(RAIL_COLLAPSED_KEY) ?? (() => false);
}
