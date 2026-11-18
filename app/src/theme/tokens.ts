// morehere. design tokens, brand v1 ("Isar & Ochre").
//
// The one place the app's colours, type, spacing and corners live. Screens use
// these names, never raw hex values. See docs/brand.md for when to use what.
//
// Format rule (tests/test_brand_tokens.py parses this file): colours are
// written as `name: "#RRGGBB",` one per line inside `light` and `dark`, and
// both palettes have exactly the same names.
//
// Dark mode rule: every text colour is light. No dark text on any fill.

/** Light palette: linen paper, petrol ink, Isar teal, Theatiner ochre. */
export const light = {
  // Surfaces
  background: "#FAF6EE", // linen: the page
  surface: "#FFFFFF", // cards, sheets, nav bar
  surfaceMist: "#DDF1EE", // Isar mist: wordmark box, selected nav pill, info strips
  border: "#E2DCCF", // card and input outlines
  borderStrong: "#C7BFAF", // secondary button outline, postcard line

  // Text
  ink: "#12343B", // petrol: headings and body text
  inkMuted: "#4F5F62", // secondary text: subtitles, meta, unselected tabs
  inkSubtle: "#8A9799", // decoration only (placeholder icons); never for text

  // Primary: anything you tap
  primary: "#17766F", // Isar teal: fills of main buttons and selected controls
  primaryPressed: "#115A55",
  link: "#17766F", // teal used as text or a line: links, selected tab underline
  onPrimary: "#FFFFFF",
  primaryTint: "#DDF1EE", // tag and chip backgrounds
  onPrimaryTint: "#0F5652",
  focusRing: "#17766F",

  // Accent: the good moments ("I went!", a new postcard)
  accent: "#E0A33A", // Theatiner ochre
  accentPressed: "#C98E27",
  onAccent: "#12343B", // ochre always carries dark text
  accentTint: "#F8E9C8",
  onAccentTint: "#6E4A0E",
  wordmarkDot: "#D18F1F",

  // Status (rare; most screens never need these)
  success: "#2F7A4A",
  successTint: "#E0F0E4",
  onSuccessTint: "#235E39",
  warningTint: "#F8E9C8",
  onWarningTint: "#6E4A0E",
  error: "#B23A2E",
  errorTint: "#F8E1DD",
  onErrorTint: "#8C2A20",

  // Disabled
  disabled: "#ECE7DC",
  onDisabled: "#5A6669",
} as const;

/** Dark palette: the Isar at night. Same names as `light`. */
export const dark = {
  background: "#0E2328",
  surface: "#15313A",
  surfaceMist: "#1B4148",
  border: "#28474F",
  borderStrong: "#3C5E66",

  ink: "#F3EFE6",
  inkMuted: "#A9BDBE",
  inkSubtle: "#6C8589",

  primary: "#17766F", // same deep teal fill as light mode, so its text stays light
  primaryPressed: "#115A55",
  link: "#5CC2B8", // the bright teal is for text and lines only
  onPrimary: "#F3EFE6",
  primaryTint: "#1B4148",
  onPrimaryTint: "#A8E3DC",
  focusRing: "#8AD8CF",

  accent: "#946512", // deep amber fill, so "I went!" keeps light text
  accentPressed: "#7E5510",
  onAccent: "#FFF6E5",
  accentTint: "#3B3322",
  onAccentTint: "#F2D49A",
  wordmarkDot: "#E9B65A",

  success: "#7FCB98",
  successTint: "#1D3B2A",
  onSuccessTint: "#A9E0BB",
  warningTint: "#3B3322",
  onWarningTint: "#F2D49A",
  error: "#F0907F",
  errorTint: "#45231F",
  onErrorTint: "#F8B9AD",

  disabled: "#1F3940",
  onDisabled: "#8DA1A3",
} as const;

export type ColorName = keyof typeof light;
export type Palette = Record<ColorName, string>;

/** Outfit is the only typeface. Weights map to the loaded font files. */
export const fontFamily = {
  regular: "Outfit_400Regular",
  medium: "Outfit_500Medium",
  semibold: "Outfit_600SemiBold",
  bold: "Outfit_700Bold",
} as const;

/** Type scale. Sizes and line heights in points; letterSpacing in points (React Native has no em). */
export const type = {
  display: { fontFamily: fontFamily.bold, fontSize: 34, lineHeight: 38, letterSpacing: -1 }, // screen hero ("Somewhere to be tonight.")
  title: { fontFamily: fontFamily.bold, fontSize: 28, lineHeight: 32, letterSpacing: -0.6 }, // detail screen title
  heading: { fontFamily: fontFamily.bold, fontSize: 22, lineHeight: 27, letterSpacing: -0.4 }, // card title
  subheading: { fontFamily: fontFamily.semibold, fontSize: 18, lineHeight: 24, letterSpacing: -0.2 },
  body: { fontFamily: fontFamily.regular, fontSize: 16, lineHeight: 23, letterSpacing: 0 },
  bodyStrong: { fontFamily: fontFamily.semibold, fontSize: 16, lineHeight: 23, letterSpacing: 0 }, // buttons
  label: { fontFamily: fontFamily.semibold, fontSize: 14, lineHeight: 18, letterSpacing: 0 }, // tags, tabs, meta
  caption: { fontFamily: fontFamily.medium, fontSize: 13, lineHeight: 17, letterSpacing: 0 }, // evidence quotes, "last verified"
  overline: { fontFamily: fontFamily.bold, fontSize: 12, lineHeight: 16, letterSpacing: 1 }, // UPPERCASE section labels
} as const;

/** 4-point spacing grid. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32, huge: 40 } as const;

/** Corner radii. */
export const radius = { tag: 8, button: 14, card: 20, sheet: 28, pill: 999 } as const;

/** Sizes that are rules, not suggestions. */
export const size = {
  minTouch: 44, // every tappable thing is at least 44 x 44
  buttonHeight: 48,
  borderWidth: 1.5,
  focusRingWidth: 2,
} as const;
