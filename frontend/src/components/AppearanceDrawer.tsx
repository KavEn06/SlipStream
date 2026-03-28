import { useEffect, useId, useRef } from "react";
import {
  useAppearance,
  type ThemeName,
} from "../hooks/useAppearance";

const THEME_OPTIONS: Array<{
  value: ThemeName;
  label: string;
  description: string;
}> = [
  {
    value: "dark",
    label: "Dark",
    description: "Low-light telemetry surfaces with deeper contrast.",
  },
  {
    value: "light",
    label: "Light",
    description: "A brighter SlipStream palette with the same motorsport feel.",
  },
];

export function AppearanceDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { theme, setTheme } = useAppearance();
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  return (
    <div
      className={`fixed inset-0 z-50 ${open ? "" : "pointer-events-none"}`}
      aria-hidden={!open}
    >
      <button
        type="button"
        aria-label="Close appearance drawer"
        onClick={onClose}
        className={`absolute inset-0 bg-surface-0/55 backdrop-blur-sm transition-opacity ${
          open ? "opacity-100" : "opacity-0"
        }`}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`themed-shadow-lg absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-border/70 bg-surface-1/92 px-5 py-6 backdrop-blur-xl transition-transform duration-300 sm:px-6 ${
          open ? "translate-x-0" : "translate-x-full"
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
            <p className="mt-2 max-w-sm text-sm text-text-secondary">
              Choose how SlipStream looks across the dashboard and review screens.
            </p>
          </div>

          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-border/70 bg-surface-2/90 text-text-secondary transition-colors hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
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

        <div className="mt-8">
          <p className="text-[11px] uppercase tracking-[0.18em] text-text-muted">
            Theme
          </p>
          <div className="mt-4 space-y-3">
            {THEME_OPTIONS.map((option) => {
              const active = theme === option.value;

              return (
                <label
                  key={option.value}
                  className={`block cursor-pointer rounded-[28px] border p-4 transition-colors ${
                    active
                      ? "border-accent/28 bg-accent/10 text-text-primary"
                      : "border-border/70 bg-surface-2/85 text-text-primary hover:border-border-strong hover:bg-surface-3"
                  }`}
                >
                  <input
                    type="radio"
                    name="theme"
                    value={option.value}
                    checked={active}
                    onChange={() => setTheme(option.value)}
                    className="sr-only"
                  />
                  <div className="flex items-start justify-between gap-4">
                    <div>
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
        </div>
      </aside>
    </div>
  );
}
