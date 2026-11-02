# IDM UI Design System

Version 3.6.1 ships one design system shared by the classic and modern IDM
surfaces. The system has two layers:

1. **Design tokens** — framework-light values in `idm/ui/design.py`, consumed
   by Qt style sheets and custom-painted widgets.
2. **Theme palettes** — semantic colour sets in `idm/ui/theme.py`, compiled
   into the global QSS with the tokens above.

Components read these values instead of hard-coded pixels or colours, so the
classic, light, dark and Follow-Windows themes, high-DPI screens and
reduced-motion settings stay consistent without per-widget special cases.

## Identity

The 3.6.1 identity is deep navy and azure in the modern themes and crisp blue
on light gray in Classic. The mark is an original squircle
with an azure gradient, a light ring and a white download glyph; it is used at
every size from 16 px window icons to the installer wizard. Toolbar and
navigation actions use monochrome line glyphs from the same SVG vocabulary,
reserving filled accent treatment for primary actions. Video posters are
cinematic navy surfaces in both themes so media cards keep a strong visual
anchor against light and dark chrome.

## Themes

| Mode | Behaviour |
| --- | --- |
| `light` | Cool blue-white surfaces, deep ink text and azure accents. |
| `dark` | Deep navy surfaces, layered borders and brighter azure accents. |
| `system` | Follows the Windows app theme and refreshes when it changes. |
| `classic` | Light gray workspace with crisp white surfaces, near-black text and an IDM-style blue accent. |

Switching a theme rebuilds the QSS, recolours toolbar icons, updates custom
painters and repaints every page immediately. No restart is required.

### Core colour roles

| Role | Classic | Light | Dark |
| --- | --- | --- | --- |
| Background | `#F2F2F2` | `#F1F4FA` | `#080D18` |
| Surface | `#FFFFFF` | `#FFFFFF` | `#0E1626` |
| Card | `#FFFFFF` | `#FFFFFF` | `#101A2B` |
| Border | `#D5DDE5` | `#DDE4F0` | `#22314B` |
| Text | `#202020` | `#0E1726` | `#E9F0FC` |
| Muted text | `#586571` | `#526079` | `#9DAEC8` |
| Faint text | `#8A96A2` | `#7E8AA0` | `#66788F` |
| Accent | `#1683D8` | `#1D5BEA` | `#4D8DFF` |
| Accent soft | `#E7F2FB` | `#EDF2FF` | `#14284B` |
| Accent gradient | `#1A8FE3 → #0E64AA` | `#3F7DFF → #1D5BEA → #1743C2` | `#3F7BFF → #1D5BEA → #123A9E` |
| Success | `#1C8F5A` | `#0E9F6E` | `#3DD6A0` |
| Warning | `#B9791A` | `#B26B00` | `#F2B45E` |
| Danger | `#C94343` | `#D64545` | `#FF7B7B` |
| Sidebar | `#FFFFFF` | `#F8FAFE` | `#0A1220` |
| Selection | `#D8EBF9` | `#E7EEFF` | `#15294A` |
| Track | `#E8EEF3` | `#E4EAF5` | `#1E2B42` |
| Focus ring | `#9CC8EC` | `#B9CDFF` | `#2C4E88` |

Every status colour is paired with a soft background and a text label, so
colour is never the only signal.

## Spacing

| Token | px | Typical use |
| --- | ---: | --- |
| `none` | 0 | Reset |
| `xxs` | 2 | Hairline gaps |
| `xs` | 4 | Icon/text gap |
| `sm` | 8 | Inline control gap |
| `md` | 12 | Row gap, page columns |
| `lg` | 16 | Card padding |
| `xl` | 24 | Page margin |
| `xxl` | 32 | Section separation |
| `xxxl` | 40 | Hero spacing |

## Radii

| Token | px | Use |
| --- | ---: | --- |
| `none` | 0 | Square surfaces |
| `xs` | 6 | Tiny chips |
| `sm` | 8 | Small controls, badges |
| `md` | 10 | Inputs, icon buttons |
| `lg` | 14 | Cards, dialogs |
| `xl` | 18 | Large panels |
| `pill` | 14 | Pills, toggles, segmented chips |

Qt renders a border radius larger than half the control height as a square.
Small badges therefore use explicit 8–10 px radii, while 30 px chips and
buttons use the 14 px pill token. New pill-shaped controls must respect this
ceiling instead of using `999px`.

## Typography

`FONT_FAMILY` is `"Segoe UI"`; monospaced values use
`"Cascadia Mono", "Consolas", monospace`.

| Token | Size | Weight | Use |
| --- | ---: | ---: | --- |
| `micro` | 10 | 700 | Uppercase labels |
| `caption` | 11 | 400 | Helper text |
| `label` | 10 | 700 | Field labels |
| `small` | 12 | 400 | Secondary rows, table values |
| `body` | 13 | 400 | Default text |
| `body_strong` | 13 | 600 | Emphasis, row titles |
| `subtitle` | 14 | 600 | Card titles, panel headings |
| `title` | 17 | 600 | Dialog titles, brand |
| `heading` | 20 | 600 | Page headings |
| `display` | 28 | 700 | Hero numbers, percentages |

Qt style sheets use point sizes derived from these tokens; layouts never rely
on a fixed DPI assumption. Helper text is no smaller than 11 px in the main
workspaces for readability.

## Motion

| Token | ms | Use |
| --- | ---: | --- |
| `instant` | 0 | State changes that must not animate |
| `fast` | 140 | Hover and press feedback |
| `normal` | 210 | Toggles, rail width, fades |
| `slow` | 300 | Larger panel transitions |

Motion rules:

- Animate only opacity, geometry and colour; never block the UI thread.
- Animations are disabled when the IDM **Reduce motion** preference is on, or
  when Windows reports that animation effects are disabled
  (`SPI_GETCLIENTAREAANIMATION`).
- Reduced motion sets every duration to `0`, so layouts jump to the final
  state.

## Icons and elevation

| Icon token | px |
| --- | ---: |
| `xs` | 12 |
| `sm` | 14 |
| `md` | 16 |
| `lg` | 18 |
| `xl` | 22 |
| `xxl` | 26 |
| `hero` | 32 |

All artwork is original IDM iconography drawn from the project's SVG set. The
application never bundles third-party brand artwork. Toolbar actions use
palette-aware line icons; the primary **Add URL** action uses a white glyph on
the azure gradient button.

Elevation uses `QGraphicsDropShadowEffect` with tokens:

| Level | Blur | Y offset | Alpha |
| --- | ---: | ---: | ---: |
| `flat` | 0 | 0 | 0 |
| `card` | 24 | 4 | 24 |
| `raised` | 36 | 10 | 44 |

Shadows are suppressed when motion or animation effects are disabled.

## Components

| Component | Rules |
| --- | --- |
| Card | `lg` radius, `lg` padding, hairline border, optional `card` elevation, header with title, caption and one action. |
| Buttons | 36 px height, `md` radius; only one accent-gradient primary action per region. |
| Icon buttons | 40 px toolbar targets and 30 px in-card targets; always carry a tooltip and accessible name. |
| Inputs | 36 px height, `md` radius, accent focus ring. |
| Toggles / checks | Accent fill with a white mark; no colour-only state. |
| Tables | 62 px row rhythm, painted file-type tile, file name with category subtitle, status pill, rounded progress meter with a right-aligned percentage and aligned numeric columns. The seven columns are File Name, Size, Status, Progress, Speed, Time Left and Date Added; Size shows live `downloaded/total` (for example `8.3/64 MB`) while a transfer is active. |
| Tabs | Segmented pill bar with an accent-soft active state; each dialog tab scrolls independently when needed. |
| Toasts | Bottom-right, stacked, auto-dismiss, never cover primary actions. |
| Empty state | Icon, short explanation and a single recovery action. |
| Video card | 128–144 px cinematic navy poster, quality/duration chips, metadata, gradient progress and a divided action row. |
| Dashboard transfer row | 62 px minimum, category tile, live status colour, gradient progress and compact metadata. |
| Download File Info dialog | Branded header with a 46 px gradient tile, eyebrow, title and transport badge; a scrollable body with the URL row, a gradient file hero card (56 px file-type tile, category pill, extension chip), a save-options card with icon-led category, file name, folder and description fields, and a compact server information card; fixed error line and a divided footer with Cancel, Download Later and the single primary Start Download. Unknown server values render as an em dash, never as invented text. After Start Download the same window switches to a compact live view with percentage, downloaded/total size in MB or GB, transfer rate, time left and status; it auto-closes on completion and closing early leaves the transfer running. |
| Download Complete window | Non-modal 540 px card: 52 px success badge, title, file name, destination line, a two-column details card (average speed, completed, size, source host), a hint, then Open Folder, Close and the single primary Open File, with a persisted completion-window checkbox above the footer. Values come from the finished `DownloadItem`; missing paths disable Open File. |
| Sidebar rows | 38 px rhythm, painted icon tile, label and right-aligned count pill; a 3 px accent bar marks the active destination. Custom categories use the same row and participate in counts, filtering and selection. |
| Status bar | 30 px bar: activity dot, active/queued counts, live transfer rate, total downloaded data, transient message and the version readout. |

## Layout and responsiveness

- Navigation rail: 240 px expanded, 68 px collapsed, 38 px item rhythm.
- Toolbar: 72 px height with a 126×40 px primary action and 40×40 px icon
  actions. Below 1320 px the toolbar switches to compact icon-only actions with
  tooltips; below 1200 px the inline search field is hidden.
- Content margins: 24 px sides, 20 px top, 16 px bottom; page columns use a
  3:2 split with 12 px gutters.
- Minimum supported window: 1040×600. The shell, download workspace, dialogs
  and both themes were reviewed at 1440×900; the automated suite exercises the
  1240×770 shell.
- The Download File Info dialog opens at 800×920 where space allows, clamps to
  the available screen minus 80 px, hides its footer hint below 720 px and
  scrolls its body from a 640×560 floor so the footer actions stay reachable on
  small displays. Its live progress mode switches to a compact 640×430 window
  (560×380 floor) centred on the main window.
- All sizes are device-independent pixels; Qt handles Windows scaling.
- Tables virtualize rows; video and card pages create widgets only for
  visible items and cache them.
- Long-running work (downloads, update checks, backups, hashing) runs in
  worker threads or timers; the UI thread never performs blocking I/O.

## Accessibility and keyboard

- Every interactive control is reachable with Tab; lists and cards accept
  Enter/Space.
- Icon-only buttons expose an accessible name equal to their tooltip.
- Focus states use the palette focus ring and are visible in all themes.
- Status is communicated with text and icon in addition to colour.
- Reduced motion and high-DPI support are part of the design system, not
  optional add-ons.

## Contribution rules

1. Read tokens from `idm/ui/design.py`; do not add local magic numbers.
2. Add new colours to all palettes in `idm/ui/theme.py` before using them.
3. Reuse `components.py` primitives before writing a new widget.
4. Keep toolbar and navigation icons monochrome and palette-aware.
5. Respect the Qt pill-radius ceiling: never use a radius larger than half the
   control height.
6. Run the UI snapshots and regression tests after changing tokens or QSS.
7. Keep page-specific styling in the page module; the global QSS owns shared
   surfaces only.
