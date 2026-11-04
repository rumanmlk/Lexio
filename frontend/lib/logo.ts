/** The Lexio mark in a 32 x 32 box: an L made from a page margin and an amber highlighter stroke.
 * Shared by the Logo component and the share image; app/icon.svg is a copy kept in step by a test. */
export type LogoPart = { role: "tile" | "stem" | "line" | "foot"; x: number; y: number; width: number; height: number; rx: number };

export const LOGO: LogoPart[] = [
  { role: "tile", x: 0, y: 0, width: 32, height: 32, rx: 8 },
  { role: "stem", x: 8, y: 6, width: 4.4, height: 19.6, rx: 2.2 },
  { role: "line", x: 15.5, y: 8.6, width: 8.5, height: 2.4, rx: 1.2 },
  { role: "line", x: 15.5, y: 13.4, width: 6, height: 2.4, rx: 1.2 },
  { role: "foot", x: 8, y: 20.4, width: 17, height: 5.2, rx: 2.2 },
];

/** Light-theme colours for contexts without the app's CSS (the share image). */
export const LOGO_COLORS = { tile: "#0b5f57", stem: "#ffffff", line: "#ffffff", foot: "#ffc94d" } as const;
