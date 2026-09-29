import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import themeLightUrl from "primereact/resources/themes/lara-light-blue/theme.css?url";
import themeDarkUrl from "primereact/resources/themes/lara-dark-blue/theme.css?url";

export const THEME_STORAGE_KEY = "rc-theme";
export const THEMES = Object.freeze({ light: "light", dark: "dark" });

const ThemeContext = createContext(null);

const PRIME_THEME_HREF = {
  light: themeLightUrl,
  dark: themeDarkUrl,
};

export function resolveInitialTheme() {
  if (typeof document !== "undefined") {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === THEMES.dark || attr === THEMES.light) return attr;
  }
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === THEMES.dark || stored === THEMES.light) return stored;
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? THEMES.dark
      : THEMES.light;
  }
  return THEMES.light;
}

function ensurePrimeThemeLink(theme) {
  const href = PRIME_THEME_HREF[theme] || PRIME_THEME_HREF.light;
  let link = document.getElementById("app-prime-theme");
  if (!link) {
    link = document.createElement("link");
    link.id = "app-prime-theme";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== href) {
    link.setAttribute("href", href);
  }
}

export function applyTheme(theme) {
  const next = theme === THEMES.dark ? THEMES.dark : THEMES.light;
  document.documentElement.setAttribute("data-theme", next);
  document.documentElement.style.colorScheme = next;
  ensurePrimeThemeLink(next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  return next;
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => resolveInitialTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next) => {
    setThemeState(applyTheme(next));
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) =>
      applyTheme(prev === THEMES.dark ? THEMES.light : THEMES.dark)
    );
  }, []);

  const value = useMemo(
    () => ({
      theme,
      isDark: theme === THEMES.dark,
      setTheme,
      toggleTheme,
    }),
    [theme, setTheme, toggleTheme]
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return ctx;
}

// Apply early so PrimeReact CSS + data-theme match before first paint of app chrome
if (typeof document !== "undefined") {
  applyTheme(resolveInitialTheme());
}
