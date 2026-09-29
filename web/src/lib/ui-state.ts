import { create } from "zustand";

/**
 * Interface state that is not server data.
 *
 * TanStack Query owns everything the hub knows; this owns what the browser
 * knows — which theme, whether the sidebar is collapsed, whether the palette is
 * open. Keeping them apart means a theme change cannot invalidate a device
 * query, and a refetch cannot close a panel.
 */
type Theme = "dark" | "light";

interface UiState {
  theme: Theme;
  sidebarCollapsed: boolean;
  paletteOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setPaletteOpen: (open: boolean) => void;
}

const THEME_KEY = "fenox.theme";
const SIDEBAR_KEY = "fenox.sidebar";

function stored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const value = localStorage.getItem(key) as T | null;
    return value && allowed.includes(value) ? value : fallback;
  } catch {
    return fallback; // private mode, or storage disabled
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Remembering is a convenience, not a requirement.
  }
}

/** Put the theme on <html>, which is where the token overrides live. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

const initialTheme = stored<Theme>(THEME_KEY, "dark", ["dark", "light"]);
applyTheme(initialTheme);

export const useUi = create<UiState>((set, get) => ({
  theme: initialTheme,
  sidebarCollapsed: stored(SIDEBAR_KEY, "expanded", ["expanded", "collapsed"]) === "collapsed",
  paletteOpen: false,
  setTheme: (theme) => {
    applyTheme(theme);
    remember(THEME_KEY, theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
  toggleSidebar: () => {
    const next = !get().sidebarCollapsed;
    remember(SIDEBAR_KEY, next ? "collapsed" : "expanded");
    set({ sidebarCollapsed: next });
  },
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
}));
