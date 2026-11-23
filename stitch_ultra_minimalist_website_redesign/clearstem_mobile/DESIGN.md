---
name: ClearSTEM Mobile
colors:
  surface: '#f9f9ff'
  surface-dim: '#cfdaf2'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f0f3ff'
  surface-container: '#e7eeff'
  surface-container-high: '#dee8ff'
  surface-container-highest: '#d8e3fb'
  on-surface: '#111c2d'
  on-surface-variant: '#434656'
  inverse-surface: '#263143'
  inverse-on-surface: '#ecf1ff'
  outline: '#737688'
  outline-variant: '#c3c5d9'
  surface-tint: '#004fe5'
  primary: '#0045cc'
  on-primary: '#ffffff'
  primary-container: '#0d5bff'
  on-primary-container: '#ebecff'
  inverse-primary: '#b6c4ff'
  secondary: '#006c47'
  on-secondary: '#ffffff'
  secondary-container: '#8af5be'
  on-secondary-container: '#00714b'
  tertiary: '#804300'
  on-tertiary: '#ffffff'
  tertiary-container: '#a45700'
  on-tertiary-container: '#ffe9db'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dce1ff'
  primary-fixed-dim: '#b6c4ff'
  on-primary-fixed: '#00164f'
  on-primary-fixed-variant: '#003bb0'
  secondary-fixed: '#8df7c1'
  secondary-fixed-dim: '#71dba6'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005235'
  tertiary-fixed: '#ffdcc3'
  tertiary-fixed-dim: '#ffb77e'
  on-tertiary-fixed: '#2f1500'
  on-tertiary-fixed-variant: '#6e3900'
  background: '#f9f9ff'
  on-background: '#111c2d'
  surface-variant: '#d8e3fb'
  canvas-bg: '#F8FAFC'
  surface-card: '#FFFFFF'
  border-subtle: '#E2E8F0'
  border-strong: '#0F172A'
  action-error: '#DC2626'
  action-focus: '#FACC15'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '800'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '700'
    lineHeight: 28px
  body-xl:
    fontFamily: Atkinson Hyperlegible Next
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 30px
  body-lg:
    fontFamily: Atkinson Hyperlegible Next
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Atkinson Hyperlegible Next
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-code:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  label-button:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '700'
    lineHeight: 24px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Atkinson Hyperlegible Next
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  margin: 1.25rem
  space-xs: 0.375rem
  space-sm: 0.75rem
  space-md: 1.25rem
  space-lg: 1.75rem
  space-xl: 2.5rem
---

## Brand & Style

This design system delivers an ultra-minimalist, hyper-clear, cognitive-accessibility-first mobile experience tailored for young learners, neurodivergent students, and users requiring absolute operational clarity. Visual noise is treated as a defect. The aesthetic draws on disciplined modern minimalism crossed with warm, oversized tactile affordances: high tonal contrast, generous touch targets, clear iconography with explicit labels, and an unambiguous hierarchy that prevents decision paralysis.

The emotional tone is calm, reassuring, and empowering. Interactive states provide immediate, predictable feedback without jarring transitions or overwhelming sensory stimulation. Layouts favor single-column vertical flows with ample negative space to keep cognitive load minimal.

## Colors

The color system prioritizes extreme legibility and cognitive ease, compliant with WCAG AAA standards across core functional paths.

- **Primary (`#0D5BFF`)**: A vivid, unambiguous electric cobalt blue used strictly for primary call-to-actions, active step indicators, and confirmation states.
- **Secondary (`#00875A`)**: A deep, saturated emerald green for verified success states, positive completion, and correct answers.
- **Tertiary (`#FF8B00`)**: A warm amber for helpful cues, hints, and secondary attention anchors.
- **Neutral (`#1E293B`)**: A deep slate black that provides maximum text contrast against bright backdrops without the harshness of pure black.

Surfaces remain pristine off-white (`#F8FAFC`) to minimize glare, paired with pure white (`#FFFFFF`) card containers. Focus indicators employ high-contrast dual rings with `#FACC15` to guarantee immediate visibility for assistive inputs.

## Typography

Typography is calibrated to maximize glyph differentiation and reading ease.

- **Headline (`Plus Jakarta Sans`)**: Friendly, rounded geometric sans with open apertures, reassuring without feeling childish.
- **Body (`Atkinson Hyperlegible Next`)**: Engineered specifically for cognitive accessibility and low-vision legibility, featuring distinct letterforms that prevent letter-mirroring confusion (e.g., 'b' and 'd', 'p' and 'q').
- **Monospace / Code (`JetBrains Mono`)**: Clean, wide monospace font providing unambiguous distinctions between `0` and `O`, `1`, `l`, and `I` for instructional STEM code snippets and numerical puzzles.

Body text never drops below 16px on mobile interfaces. Line spacing is deliberately relaxed (1.4–1.5x) to maintain line tracking.

## Layout & Spacing

The layout model is mobile-first, single-column, and strictly vertical. Complex multi-column arrangements are avoided on handheld devices to prevent scanning fragmentation.

- **Layout Structure**: Single 1-column stack across phones, expanding to a disciplined 2-column card deck on tablets. Outer canvas margin is fixed at `1.25rem` (20px) to provide a generous touch boundary and prevent accidental thumb triggers along device bezels.
- **Vertical Rhythm**: Generous vertical separation (`space-md` to `space-xl`) between distinct cognitive steps. Interactive elements are isolated with sufficient breathing room so users never trigger unintended actions.
- **Safe Area**: Touch areas always honor a strict minimum tap bounding box of 56×56px, exceeding standard mobile guidelines to support low motor-precision control.

## Elevation & Depth

Visual hierarchy avoids noisy, complex drop shadows or blurry skeuomorphic treatments that can distract neurodivergent users. Depth is achieved via:

- **Tonal Contrast & 2D Layering**: Pure white cards sitting on top of the soft `#F8FAFC` foundation.
- **Tactile Stacking / Crisp Borders**: Elements employ a sturdy `1.5px` to `2px` stroke (`border-subtle` or `border-strong`) that explicitly defines interactive hit zones.
- **Subtle Hard-Edge Elevation**: Where tactile button depth is required, an intentional 3px solid, non-diffused offset border (`box-shadow: 0 3px 0 0 #0F172A`) provides immediate physical metaphor without spatial blur or visual mud.

## Shapes

The design system utilizes roundedness level `2`. Corners are distinct, friendly, and approachable without losing structural discipline.

- **Standard Containers & Cards**: `rounded-md` (0.5rem / 8px) to `rounded-lg` (1rem / 16px) for distinct bounding contours.
- **Interactive Controls**: Buttons, text inputs, and choice chips feature `rounded-lg` (1rem) or pill caps where continuous linear guidance helps draw eyes to progress triggers.
- **Visual Targets**: Interactive items always exhibit well-defined geometric boundaries that reinforce clickable boundaries.

## Components

### Buttons
- **Primary Action**: 56px height, full-width or oversized inline format. Filled with primary blue (`#0D5BFF`), white bold text, accompanied by an explicit action icon (e.g., forward arrow). Pressed state renders a 2px downward tactile translation.
- **Secondary / Cancel**: 56px height, pure white surface with a solid 2px outline in slate neutral (`#1E293B`).

### Interactive Chips & Choice Selectors
- Used for single/multi-choice quiz and code logic assembly.
- Minimum size 52px height with internal padding of `space-md`. Default state has a soft gray background and 2px border. Selected state swaps to an unmistakable primary blue border with a clear checkmark icon prefix.

### Text & Code Input Fields
- Generously padded input fields (56px minimum height) featuring large 18px text.
- Label permanently visible above the input, never relying on fading placeholder text.
- Thick 2px border that transitions to high-contrast blue with a secondary yellow ring on active focus.

### Cards & Content Containers
- Single-concept containers: one primary instruction per card.
- Crisp 1.5px border (`#E2E8F0`), flat white background, `space-lg` internal padding. Prevents edge crowding.

### Checkboxes & Radios
- Oversized (32×32px minimum glyph box inside a 56px hit target).
- Explicit, unmistakable checkmarks and solid dots. Binary states are color-coded (slate neutral for unchecked, primary blue for checked).

### Progress & Step Indicators
- High-visibility linear segmented bar with step numbers and short verbal milestones (e.g., "Step 2 of 4: Test Code"). No unlabelled dots or ambiguous circular gauges.