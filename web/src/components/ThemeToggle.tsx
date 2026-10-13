import { useState } from "react";
import { currentTheme, setTheme, type Theme } from "../theme";
import Icon from "./Icon";

// Switches the whole site between light and dark. The choice is kept on this browser.
export default function ThemeToggle() {
  const [theme, setLocal] = useState<Theme>(currentTheme);

  function flip() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setLocal(next);
  }

  return (
    <button
      className="icon-button"
      type="button"
      onClick={flip}
      title={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
      aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
