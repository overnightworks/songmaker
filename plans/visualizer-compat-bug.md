# Bug: Audio Visualizer Not Showing on Some Clients

> **Status: NOT STARTED**

## Problem

The real-time audio visualizer (frequency bars, waveform, rings, particles) doesn't appear on some client PCs while working fine on others (Chrome, Firefox, mobile all confirmed working on other machines).

## Symptoms

- Player bar shows controls and track info but no animation
- Audio plays fine
- No console errors reported (need to check)

## Possible Causes

1. **AudioContext creation fails silently** — the `try/catch` in `connectAnalyser()` swallows all errors. If `createMediaElementSource` fails (e.g., CORS, browser policy, already-connected element), the visualizer never starts but no error is visible.

2. **CORS on audio files** — `createMediaElementSource` with cross-origin audio silently zeroes the analyser data in some browsers. The `/audio/*` endpoint may need explicit CORS headers for the audio files.

3. **Canvas sizing** — if `getBoundingClientRect()` returns 0 on first frame (element not yet laid out), the canvas never initializes properly.

4. **Browser autoplay policy** — some browsers block `AudioContext` creation until a user gesture. The context is created on `play` event which should count as a gesture, but some browsers are stricter.

5. **GPU/WebGL disabled** — though this is Canvas2D, some browsers with disabled hardware acceleration may behave differently.

## Debugging Steps

1. Ask the affected user to open DevTools console and check for errors
2. Check if `navigator.mediaDevices` and `AudioContext` are available
3. Add a visible fallback — if analyser has no data after N frames, show a CSS-only animation instead
4. Add logging to `connectAnalyser()` catch block (at least `console.warn`)

## Fix

- Don't silently swallow `connectAnalyser()` errors — log them
- Add a fallback visualization (CSS-only pulse/glow) when AudioContext is unavailable
- Ensure audio files have proper CORS headers if served cross-origin
- Test on Edge, Safari, older Chrome versions

## Files to Touch

| File | Change |
|------|--------|
| `PlayerBar.svelte` | Log analyser errors, add fallback visualization |
| `server.py` or audio endpoint | Add CORS headers to `/audio/*` responses if needed |
