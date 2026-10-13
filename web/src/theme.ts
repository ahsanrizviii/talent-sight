// Light or dark (UI refresh).
// Until someone chooses, the site follows the setting on their computer. Once they choose,
// that choice is kept on this browser and used everywhere, including the next visit.

export type Theme = "light" | "dark";

const KEY = "talentsight_theme";

export function savedTheme(): Theme | null {
  const saved = localStorage.getItem(KEY);
  return saved === "light" || saved === "dark" ? saved : null;
}

export function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function currentTheme(): Theme {
  return savedTheme() ?? systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  // The browser's own parts (scrollbars, form controls) follow this.
  document.documentElement.style.colorScheme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", theme === "dark" ? "#0e1013" : "#eef1f5");
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
  applyTheme(theme);
}

// Called once when the app starts, before anything is drawn, so there is no flash of the wrong theme.
export function startTheme(): void {
  applyTheme(currentTheme());
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!savedTheme()) applyTheme(systemTheme()); // still following the computer
  });
}
