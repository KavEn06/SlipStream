import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import {
  useAppearance,
  type AccentName,
  type DensityMode,
  type MotionMode,
  type ThemeName,
} from "../hooks/useAppearance";

type PreferenceOption<T extends string> = {
  value: T;
  label: string;
  description: string;
};

const THEME_OPTIONS: PreferenceOption<ThemeName>[] = [
  {
    value: "dark",
    label: "Dark",
    description: "Deep contrast for low-light review.",
  },
  {
    value: "light",
    label: "Light",
    description: "Brighter SlipStream surfaces.",
  },
];

const DENSITY_OPTIONS: PreferenceOption<DensityMode>[] = [
  {
    value: "comfortable",
    label: "Comfortable",
    description: "More breathing room.",
  },
  {
    value: "compact",
    label: "Compact",
    description: "Tighter lists and panels.",
  },
];

const MOTION_OPTIONS: PreferenceOption<MotionMode>[] = [
  {
    value: "standard",
    label: "Standard",
    description: "Keep the full UI motion.",
  },
  {
    value: "reduced",
    label: "Reduced",
    description: "Tone down movement.",
  },
];

const ACCENT_OPTIONS: {
  value: AccentName;
  swatch: string;
}[] = [
  {
    value: "red",
    swatch: "#d14b4b",
  },
  {
    value: "blue",
    swatch: "#4d79d8",
  },
  {
    value: "green",
    swatch: "#3fa06f",
  },
  {
    value: "gold",
    swatch: "#c99635",
  },
  {
    value: "pink",
    swatch: "#d85e9f",
  },
  {
    value: "purple",
    swatch: "#8a56d8",
  },
];

function PreferenceSection<T extends string>({
  name,
  title,
  value,
  options,
  onChange,
  footer,
}: {
  name: string;
  title: string;
  value: T;
  options: PreferenceOption<T>[];
  onChange: (value: T) => void;
  footer?: ReactNode;
}) {
  return (
    <section className="density-drawer-section">
      <p className="text-[11px] uppercase tracking-[0.18em] text-text-muted">
        {title}
      </p>
      <div className="mt-4 space-y-3">
        {options.map((option) => {
          const active = value === option.value;

          return (
            <label
              key={option.value}
              className={`density-drawer-option motion-safe-color block cursor-pointer rounded-[28px] border p-4 ${
                active
                  ? "border-accent/28 bg-accent/10 text-text-primary"
                  : "border-border/70 bg-surface-2/85 text-text-primary hover:border-border-strong hover:bg-surface-3"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={active}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-base font-semibold tracking-tight">
                    {option.label}
                  </p>
                  <p className="mt-1 text-sm text-text-secondary">
                    {option.description}
                  </p>
                </div>
                <span
                  className={`mt-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                    active
                      ? "border-accent bg-accent text-surface-1"
                      : "border-border-strong bg-surface-1 text-transparent"
                  }`}
                  aria-hidden="true"
                >
                  <svg
                    className="h-3 w-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                </span>
              </div>
            </label>
          );
        })}
      </div>
      {footer ? <div className="mt-4">{footer}</div> : null}
    </section>
  );
}

export function AppearanceDrawer({
  open,
  onClose,
  returnFocusRef,
}: {
  open: boolean;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  const {
    theme,
    setTheme,
    accent,
    setAccent,
    density,
    setDensity,
    motion,
    setMotion,
  } = useAppearance();
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    const getFocusableElements = () => {
      const panel = panelRef.current;
      if (!panel) {
        return [];
      }

      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden"));
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable = getFocusableElements();
      if (focusable.length === 0) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      returnFocusRef?.current?.focus?.();
      if (!returnFocusRef?.current && previouslyFocused) {
        previouslyFocused.focus();
      }
    };
  }, [open, onClose, returnFocusRef]);

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="pointer-events-none fixed inset-0 z-[140]"
      aria-hidden={!open}
    >
      <div className="absolute inset-y-0 left-20 right-0 isolate overflow-hidden">
        <button
          type="button"
          aria-label="Close appearance drawer"
          onClick={onClose}
          className={`motion-safe-fade absolute inset-0 z-0 bg-surface-0/55 backdrop-blur-sm ${
            open ? "opacity-100" : "opacity-0"
          } ${
            open ? "pointer-events-auto" : "pointer-events-none"
          }`}
        />

        <aside
          ref={panelRef}
          id="appearance-drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className={`density-drawer-panel themed-shadow-lg motion-safe-slide absolute left-0 top-0 z-10 flex h-full w-full max-w-md flex-col border-r border-border/70 bg-surface-1/92 px-5 py-6 backdrop-blur-xl isolate transform-gpu [backface-visibility:hidden] sm:px-6 ${
            open ? "translate-x-0" : "-translate-x-full"
          } ${
            open ? "pointer-events-auto" : "pointer-events-none"
          }`}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-text-muted">
                Preferences
              </p>
              <h2
                id={titleId}
                className="mt-2 text-2xl font-semibold tracking-tight text-text-primary"
              >
                Appearance
              </h2>
            </div>

            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              className="motion-safe-color inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-border/70 bg-surface-2/90 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
              aria-label="Close appearance drawer"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.8}
                  d="M6 6l12 12M18 6 6 18"
                />
              </svg>
            </button>
          </div>

          <div className="density-drawer-body mt-8 flex-1 overflow-y-auto pr-1">
            <PreferenceSection
              name="theme"
              title="Theme"
              value={theme}
              options={THEME_OPTIONS}
              onChange={setTheme}
              footer={
                <div className="rounded-3xl border border-border/70 bg-surface-2/72 px-4 py-3">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex min-w-0 items-center">
                      <p className="text-sm font-medium text-text-primary">
                        Accent
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {ACCENT_OPTIONS.map((option, index) => {
                        const selected = option.value === accent;

                        return (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => setAccent(option.value)}
                            className={`motion-safe-color inline-flex h-9 w-9 items-center justify-center rounded-lg border cursor-pointer ${
                              selected
                                ? "border-accent bg-surface-1 text-text-primary"
                                : "border-border/70 bg-surface-1/80 text-text-secondary hover:border-border-strong hover:bg-surface-3"
                            }`}
                            aria-label={`Set accent preset ${index + 1}`}
                            aria-pressed={selected}
                          >
                            <span
                              className="h-5 w-5 rounded-md border border-border/70"
                              style={{ backgroundColor: option.swatch }}
                              aria-hidden="true"
                            />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              }
            />

            <PreferenceSection
              name="density"
              title="Density"
              value={density}
              options={DENSITY_OPTIONS}
              onChange={setDensity}
            />

            <PreferenceSection
              name="motion"
              title="Motion"
              value={motion}
              options={MOTION_OPTIONS}
              onChange={setMotion}
            />
          </div>
        </aside>
      </div>
    </div>,
    document.body,
  );
}
