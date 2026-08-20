export function cowriterThinkingLabel(provider: string): string {
	return `${provider} is thinking...`;
}

export function cowriterUnavailableLabel(provider: string): string {
	return `${provider} is currently unavailable`;
}

export function cowriterHeaderLabel(provider: string, model: string): string {
	if (!model) return 'Co-Writer';
	return `${provider} · ${model}`;
}
