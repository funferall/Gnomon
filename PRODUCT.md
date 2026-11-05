# Product

## Register

product

## Users

A small trained team of GIS and public-works staff reviewing machine-detected roadside assets (signs, hydrants, signals, covers) for a Massachusetts town. They work long sessions, often hundreds of detections at a time, on desktop monitors. Each reviewer enters their initials; every decision is audited and reversible. They know the town's streets and GIS conventions. They need speed and confidence more than guidance.

## Product Purpose

Gnomon turns street-level imagery into a reviewed asset inventory. The workbench lets a reviewer see a detection in its photo and on the map at the same time, decide whether it is real, give it the right class and routing role, and put it at its true location. Starting points are the machine's estimated position, a click on aerial imagery, or a linked existing asset. Success means many accurate, well-placed assets per hour, with a clear record of who decided what and why.

## Brand Personality

Precise, quiet, trustworthy. A surveying instrument, not a dashboard: dense where it helps, calm everywhere else. Imagery and the map carry the color; the chrome stays out of the way. Copy is plain and specific ("Estimated 12 m away, ±4 m from 6 views"), never cheerful or vague.

## Anti-references

- SaaS dashboards with hero metrics, card grids and gradient accents.
- Wasted whitespace and letterboxed imagery: the photo and the map are the work surface and should fill the screen.
- Consumer map apps that hide data behind taps. Reviewers need coordinates, uncertainty and provenance visible.
- Modal-heavy flows that interrupt the decide → save → next rhythm.

## Design Principles

1. **The keyboard is the primary input.** Every review action has a single-key binding, every binding is visible and remappable, and the mouse is for spatial work (placing, dragging, picking).
2. **Photo and map are one evidence.** Selecting something in one highlights it in the other: box ↔ ray ↔ estimate ↔ placed asset.
3. **Show uncertainty, never fake precision.** Machine estimates show their error radius and method. Human placements require one. Camera positions are never presented as asset positions.
4. **Fast, reversible, attributable.** Save-and-advance in one key, undo in one key, and every change carries reviewer and revision.
5. **Density without noise.** Compact controls, tabular numbers and restrained color. Saturated color is reserved for state (selected, accepted, rejected) and for asset classes.

## Accessibility & Inclusion

WCAG AA defaults: 4.5:1 text contrast in both themes, visible focus rings, full keyboard operation, and respect for `prefers-reduced-motion` and `prefers-color-scheme`, with a manual theme override in Settings.
