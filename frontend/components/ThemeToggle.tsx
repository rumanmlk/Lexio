"use client";

import { useEffect, useState } from "react";
import { Icon } from "./Icon";

type Theme = "light" | "dark";

/** Light and dark follow the system until the visitor picks one; the pick is remembered. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const set = document.documentElement.dataset.theme;
    setTheme(set === "light" || set === "dark" ? set : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("lexio-theme", next);
    } catch {
      // private mode: the choice just lasts for this visit
    }
    setTheme(next);
  }

  return (
    <button type="button" className="icon-btn" onClick={toggle} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} suppressHydrationWarning>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
