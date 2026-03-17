"use client";

import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "heidi-theme";

function isTheme(value: string | null | undefined): value is Theme {
  return value === "light" || value === "dark";
}

function getSystemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    const storedTheme = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;
    const rootTheme = document.documentElement.dataset.theme;
    const nextTheme = isTheme(rootTheme) ? rootTheme : isTheme(storedTheme) ? storedTheme : getSystemTheme();
    setThemeState(nextTheme);
    applyTheme(nextTheme);

    if (isTheme(storedTheme) || typeof window.matchMedia !== "function") {
      return;
    }

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      const updatedTheme: Theme = event.matches ? "dark" : "light";
      setThemeState(updatedTheme);
      applyTheme(updatedTheme);
    };

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }

    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  function setTheme(nextTheme: Theme) {
    setThemeState(nextTheme);
    applyTheme(nextTheme);
    window.localStorage.setItem(STORAGE_KEY, nextTheme);
  }

  return { theme, setTheme };
}
