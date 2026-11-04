const PATHS = {
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M9 13h6 M9 17h6",
  check: "m5 12.5 4.5 4.5L19 7.5",
  send: "M12 19V5 M5 12l7-7 7 7",
  stop: "M7 7h10v10H7z",
  up: "M12 16V4 M7 9l5-5 5 5 M5 20h14",
  x: "M6 6l12 12 M18 6 6 18",
  left: "m15 5-7 7 7 7",
  right: "m9 5 7 7-7 7",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  search: "M11 4.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z m5 11.5 4 4",
  eye: "M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z M12 9.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2z",
  copy: "M11 9h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z M5 15V6a2 2 0 0 1 2-2h9",
  library: "M4 5h4v14H4z M10 5h4v14h-4z M16.5 6.2l3.6-1 3 13.2-3.6 1z",
  shield: "M12 3 5 6v6c0 4.4 3 7.3 7 9 4-1.7 7-4.6 7-9V6z m-3 9 2.2 2.2L15.5 10",
  trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  external: "M14 4h6v6 M20 4l-9 9 M18 14v5H5V6h5",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
