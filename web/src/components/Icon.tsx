// The small line drawings used in the sidebar, buttons and empty states.
// They are drawn here instead of loaded from an icon package: a handful of shapes is smaller
// than a library, and they all share one stroke weight so the screen looks of a piece.

export type IconName =
  | "dashboard"
  | "jobs"
  | "people"
  | "interviews"
  | "sparkle"
  | "search"
  | "sun"
  | "moon"
  | "logout"
  | "back"
  | "forward"
  | "check"
  | "external"
  | "download"
  | "plus";

const PATHS: Record<IconName, string> = {
  dashboard: "M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z",
  jobs: "M3 7h18v13H3zM8 7V4h8v3",
  people: "M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 7.5a3 3 0 1 0 0 .01M17 11l2 2 4-4",
  interviews: "M3 5h13v11H3zM16 9l5-3v9l-5-3M6 20h8",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM18 15l.8 2.2 2.2.8-2.2.8L18 21l-.8-2.2-2.2-.8 2.2-.8z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  back: "M15 18l-6-6 6-6",
  forward: "M5 12h14M13 6l6 6-6 6",
  check: "M20 6L9 17l-5-5",
  external: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  plus: "M12 5v14M5 12h14",
};

export default function Icon({ name, title, size = 17 }: { name: IconName; title?: string; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
    >
      {title && <title>{title}</title>}
      <path d={PATHS[name]} />
    </svg>
  );
}
