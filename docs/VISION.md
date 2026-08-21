# Songmaker vision

Audience: the musician shaping generated ideas into songs and coherent albums,
and the people deciding what Songmaker should become.

**Status: non-normative overview.** Approved product truth lives only in the
active tips of the [requirement registry](requirements/revisions.toml). This
page explains direction; it does not approve or replace a requirement.

## Why Songmaker exists

Generating another audio take is easy. Keeping the creative work understandable
across lyrics, prompts, settings, versions, and many results is harder.
Songmaker gives a musician one workspace for developing that material into an
album without losing the relationship between an idea, the audio it produced,
and the choices made while curating it.

## Desired outcomes

- Organize songs as coherent albums while still listening across the library.
- Iterate on lyrics, style, and generation settings without losing the creative
  context of earlier audio takes.
- Compare many takes, choose one album take, and preserve any number of other
  favourites.
- Use generation, co-writing, transcription, and scoring as assistance while
  the musician remains the author and curator.

## Guardrails

- The product keeps creative input, generated audio, and curation choices
  traceable instead of flattening them into one mutable result.
- A Pick and a Keep answer different questions and never silently replace one
  another.
- Missing, unavailable, or unproven states are shown honestly; the product does
  not invent a successful result or substitute a different take without saying
  so.

## Deliberate non-goals

- Scores do not automatically choose the album take.
- Keeping a favourite does not silently make it the album take.
- This vision is not a feature backlog, technical architecture, API contract,
  or implementation-status report.

The current product description in [CLAUDE.md](../CLAUDE.md), the running code,
and GitHub issues are source material for requirement candidates. Only the
[requirement revision lifecycle](requirements/README.md#revision-lifecycle)
turns reviewed candidate bytes into normative intent.
