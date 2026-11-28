// Props a test can change after mounting, the way a parent's state changes
// under a mounted component.
export function reactiveProps<Props extends object>(initial: Props): Props {
	const props = $state(initial);
	return props;
}
