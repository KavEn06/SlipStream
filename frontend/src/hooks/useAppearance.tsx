import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export const APPEARANCE_STORAGE_KEY = "slipstream-appearance";
export const LEGACY_THEME_STORAGE_KEY = "slipstream-theme";

export type ThemeName = "dark" | "light";
export type AccentName = "red" | "blue" | "green" | "gold" | "purple" | "pink";
export type DensityMode = "comfortable" | "compact";
export type MotionMode = "standard" | "reduced";

export interface AppearancePreferences {
  theme: ThemeName;
  accent: AccentName;
  density: DensityMode;
  motion: MotionMode;
}

const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: "dark",
  accent: "red",
  density: "comfortable",
  motion: "standard",
};

interface AppearanceContextValue extends AppearancePreferences {
  setTheme: (theme: ThemeName) => void;
  setAccent: (accent: AccentName) => void;
  setDensity: (density: DensityMode) => void;
  setMotion: (motion: MotionMode) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function isThemeName(value: string | null | undefined): value is ThemeName {
  return value === "dark" || value === "light";
}

function isAccentName(value: string | null | undefined): value is AccentName {
  return (
    value === "red" ||
    value === "blue" ||
    value === "green" ||
    value === "gold" ||
    value === "purple" ||
    value === "pink"
  );
}

function isDensityMode(value: string | null | undefined): value is DensityMode {
  return value === "comfortable" || value === "compact";
}

function isMotionMode(value: string | null | undefined): value is MotionMode {
  return value === "standard" || value === "reduced";
}

function normalizeAppearance(
  partial: Partial<AppearancePreferences> | null | undefined,
): AppearancePreferences {
  return {
    theme: isThemeName(partial?.theme)
      ? partial.theme
      : DEFAULT_APPEARANCE.theme,
    accent: isAccentName(partial?.accent)
      ? partial.accent
      : DEFAULT_APPEARANCE.accent,
    density: isDensityMode(partial?.density)
      ? partial.density
      : DEFAULT_APPEARANCE.density,
    motion: isMotionMode(partial?.motion)
      ? partial.motion
      : DEFAULT_APPEARANCE.motion,
  };
}

function getAppearanceFromDocument(): AppearancePreferences | null {
  if (typeof document === "undefined") {
    return null;
  }

  const { theme, accent, density, motion } = document.documentElement.dataset;
  if (!theme && !accent && !density && !motion) {
    return null;
  }

  return normalizeAppearance({
    theme: isThemeName(theme) ? theme : undefined,
    accent: isAccentName(accent) ? accent : undefined,
    density: isDensityMode(density) ? density : undefined,
    motion: isMotionMode(motion) ? motion : undefined,
  });
}

export function getStoredAppearance(): AppearancePreferences {
  if (typeof window === "undefined") {
    return DEFAULT_APPEARANCE;
  }

  try {
    const storedAppearance = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    if (storedAppearance) {
      const parsed = JSON.parse(storedAppearance) as Partial<AppearancePreferences>;
      return normalizeAppearance(parsed);
    }

    const legacyTheme = window.localStorage.getItem(LEGACY_THEME_STORAGE_KEY);
    return normalizeAppearance({
      theme: isThemeName(legacyTheme) ? legacyTheme : undefined,
    });
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function applyAppearance(appearance: AppearancePreferences) {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.dataset.theme = appearance.theme;
  document.documentElement.dataset.accent = appearance.accent;
  document.documentElement.dataset.density = appearance.density;
  document.documentElement.dataset.motion = appearance.motion;
}

export function initializeAppearance() {
  const appearance = getAppearanceFromDocument() ?? getStoredAppearance();
  applyAppearance(appearance);
  return appearance;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearanceState] = useState<AppearancePreferences>(
    () => getAppearanceFromDocument() ?? getStoredAppearance(),
  );

  const persistAppearance = (next: AppearancePreferences) => {
    applyAppearance(next);

    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(
          APPEARANCE_STORAGE_KEY,
          JSON.stringify(next),
        );
      } catch {
        // Ignore localStorage failures and keep the in-memory preference.
      }
    }
  };

  const value = useMemo<AppearanceContextValue>(
    () => ({
      ...appearance,
      setTheme: (theme) => {
        setAppearanceState((current) => {
          const next = { ...current, theme };
          persistAppearance(next);
          return next;
        });
      },
      setAccent: (accent) => {
        setAppearanceState((current) => {
          const next = { ...current, accent };
          persistAppearance(next);
          return next;
        });
      },
      setDensity: (density) => {
        setAppearanceState((current) => {
          const next = { ...current, density };
          persistAppearance(next);
          return next;
        });
      },
      setMotion: (motion) => {
        setAppearanceState((current) => {
          const next = { ...current, motion };
          persistAppearance(next);
          return next;
        });
      },
    }),
    [appearance],
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
