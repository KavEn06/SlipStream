# Analysis Panel Split Layout

## Problem

The current `CornerAnalysisPanel` renders findings as a 2-column card grid with the detail view (track map + telemetry charts) appended below. Clicking a finding near the top forces the user to scroll past all cards to see the charts. This breaks the core workflow: scan findings, study the detail, compare.

## Solution

Side-by-side master/detail layout. Findings list on the left, detail panel on the right. Click a finding — the right side updates instantly, no scrolling.

## Layout

### Two modes (driven by existing session list toggle)

- **Sessions sidebar open:** `grid-cols-[340px_minmax(0,320px)_1fr]` — sessions | findings | detail
- **Sessions sidebar closed:** `grid-cols-[minmax(0,380px)_1fr]` — findings | detail (more room for both)

The findings list and detail panel live inside `CornerAnalysisPanel`. The sessions sidebar and outer grid are in `AnalysisPage`.

### Responsive

Below `lg` breakpoint (~1024px), fall back to stacked layout: findings on top, detail below (current behavior minus the 2-column card grid — use single column instead).

## Findings list (left column)

Scrollable, independent of page scroll. `overflow-y-auto` with `max-h` tied to viewport.

### Compact card design

Each card shows two lines:

```
T3 · Lap 4                    +0.142s
Early Braking              ▪ moderate
```

- Line 1: corner label + lap number (left), time lost mono (right)
- Line 2: detector label (left), severity badge (right)
- No `templated_text` on the card (moved to detail panel)
- No confidence percentage on the card
- Selected state: accent border + ring (same style as current)

### Controls

- "Run Analysis" / "Re-run Analysis" button stays above the list
- "Show all / Show top N" toggle stays below the list
- Header with "Corner Analysis" title, reference lap info stays above

## Detail panel (right column)

Sticky (`sticky top-0`) so it stays visible when the page scrolls. Has its own internal scroll if content overflows viewport height.

### Empty state

When no finding is selected: centered muted text "Select a finding to view corner detail."

Auto-select the first finding when analysis loads so the panel isn't empty by default.

### Contents (top to bottom)

1. **Finding header** — corner label, direction tag, detector name, severity badge, confidence %, time lost
2. **Templated text** — the coaching message (moved here from the card)
3. **Track map** — `CompareTrackMap` component, same props as current. Height ~300px.
4. **Chart toggle pills** — speed / throttle / brake / steering buttons
5. **Telemetry charts** — stacked `MiniChart` components, same as current

## Files to modify

| File | Change |
|------|--------|
| `CornerAnalysisPanel.tsx` | Refactor to side-by-side layout. Compact cards. Detail panel with sticky positioning. Auto-select first finding. Move templated_text to detail. |
| `AnalysisPage.tsx` | Pass `sessionListOpen` state to `CornerAnalysisPanel` so it can adjust its grid split. Or: restructure the grid so the analysis page controls all three columns. |

No new components needed — this is a layout refactor of `CornerAnalysisPanel` internals. `CornerDetailView` stays unchanged.

## What does NOT change

- `CornerDetailView` component (track map + charts) — untouched
- Data fetching, analysis run/load logic — untouched
- `AnalysisPage` session selector sidebar — untouched (only grid template changes)
- Backend — no changes
