import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export const APPEARANCE_STORAGE_KEY = "slipstream-theme";

export type ThemeName = "dark" | "light";

interface AppearanceContextValue {
  theme: ThemeName;
  setTheme: (theme: ThemeName) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function isThemeName(value: string | null): value is ThemeName {
  return value === "dark" || value === "light";
}

function getThemeFromDocument(): ThemeName | null {
  if (typeof document === "undefined") {
    return null;
  }

  const theme = document.documentElement.dataset.theme ?? null;
  return isThemeName(theme) ? theme : null;
}

export function getStoredTheme(): ThemeName {
  if (typeof window === "undefined") {
    return "dark";
  }

  try {
    const stored = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    return isThemeName(stored) ? stored : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: ThemeName) {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.dataset.theme = theme;
}

export function initializeAppearance() {
  const theme = getThemeFromDocument() ?? getStoredTheme();
  applyTheme(theme);
  return theme;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>(
    () => getThemeFromDocument() ?? getStoredTheme(),
  );

  const value = useMemo<AppearanceContextValue>(
    () => ({
      theme,
      setTheme: (nextTheme) => {
        applyTheme(nextTheme);
        setThemeState(nextTheme);

        if (typeof window !== "undefined") {
          try {
            window.localStorage.setItem(APPEARANCE_STORAGE_KEY, nextTheme);
          } catch {
            // Ignore localStorage failures and keep the in-memory theme.
          }
        }
      },
    }),
    [theme],
  );

  return (
    <AppearanceContext.Provider value={value}>
      {children}
    </AppearanceContext.Provider>
  );
}

export function useAppearance() {
  const context = useContext(AppearanceContext);

  if (!context) {
    throw new Error("useAppearance must be used within AppearanceProvider");
  }

  return context;
}
