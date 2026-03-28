import { Link } from "react-router-dom";
import { useCaptureController } from "../hooks/useCaptureController";

export const NAV_ITEMS = [
  { path: "/", label: "Home" },
  { path: "/sessions", label: "Sessions" },
] as const;

function isNavItemActive(pathname: string, path: string): boolean {
  if (path === "/") {
    return pathname === "/";
  }

  if (path === "/sessions") {
    return pathname.startsWith("/sessions");
  }

  return pathname === path;
}

function HomeIcon() {
  return (
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
        d="M3 10.5 12 3l9 7.5"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M5.25 9.75V21h13.5V9.75"
      />
    </svg>
  );
}

function SessionsIcon() {
  return (
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
        d="M7.5 3.75h6.879a1.5 1.5 0 0 1 1.06.44l2.371 2.37a1.5 1.5 0 0 1 .44 1.061V18.75A1.5 1.5 0 0 1 16.75 20.25h-9.25A1.5 1.5 0 0 1 6 18.75V5.25a1.5 1.5 0 0 1 1.5-1.5Z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M14.25 3.75v3.375c0 .414.336.75.75.75h3.375"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M8.625 11.25h6.75"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M8.625 15h6.75"
      />
    </svg>
  );
}

function AppearanceIcon() {
  return (
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
        d="M10.5 3.75h3l.65 2.164a1.5 1.5 0 0 0 1.03 1.002l2.18.631.75 2.598-1.612 1.59a1.5 1.5 0 0 0-.39 1.387l.42 2.216-2.25 1.53-1.92-1.173a1.5 1.5 0 0 0-1.56 0l-1.92 1.173-2.25-1.53.42-2.216a1.5 1.5 0 0 0-.39-1.386l-1.612-1.591.75-2.598 2.18-.631a1.5 1.5 0 0 0 1.03-1.002L10.5 3.75Z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M9.75 12a2.25 2.25 0 1 0 4.5 0 2.25 2.25 0 0 0-4.5 0Z"
      />
    </svg>
  );
}

function getItemIcon(path: string) {
  if (path === "/") {
    return <HomeIcon />;
  }

  return <SessionsIcon />;
}

export function SlimNavRail({
  pathname,
  appearanceOpen,
  onOpenAppearance,
}: {
  pathname: string;
  appearanceOpen: boolean;
  onOpenAppearance: () => void;
}) {
  const capture = useCaptureController();
  const isActive = capture.status?.is_active ?? false;
  const statusLabel = isActive
    ? `${capture.status?.laps_detected ?? 0} laps`
    : "Standby";

  return (
    <aside className="sticky top-0 h-screen shrink-0 self-start border-r border-border/70 bg-surface-1/80 backdrop-blur-xl">
      <div className="flex h-full w-20 flex-col items-center px-3 py-5">
        <Link
          to="/"
          className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-border/70 bg-surface-2/90 text-sm font-semibold tracking-[0.2em] text-text-primary transition-colors hover:border-border-strong hover:bg-surface-3"
          aria-label="SlipStream Home"
          title="SlipStream"
        >
          SS
        </Link>

        <nav className="mt-8 flex flex-col items-center gap-3">
          {NAV_ITEMS.map((item) => {
            const active = isNavItemActive(pathname, item.path);

            return (
              <Link
                key={item.path}
                to={item.path}
                aria-label={item.label}
                title={item.label}
                className={`inline-flex h-12 w-12 items-center justify-center rounded-2xl border transition-colors ${
                  active
                    ? "border-accent/24 bg-accent/12 text-accent"
                    : "border-border/70 bg-surface-2/78 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                }`}
              >
                {getItemIcon(item.path)}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col items-center gap-3 pb-1">
          <button
            type="button"
            onClick={onOpenAppearance}
            aria-label="Appearance"
            aria-pressed={appearanceOpen}
            title="Appearance"
            className={`inline-flex h-11 w-11 items-center justify-center rounded-2xl border transition-colors cursor-pointer ${
              appearanceOpen
                ? "border-accent/24 bg-accent/12 text-accent"
                : "border-border/70 bg-surface-2/88 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
            }`}
          >
            <AppearanceIcon />
          </button>

          <div
            className="flex h-11 w-11 items-center justify-center rounded-2xl border border-border/70 bg-surface-2/88"
            title={isActive ? "Capture live" : "Capture standby"}
            aria-label={isActive ? "Capture live" : "Capture standby"}
          >
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                isActive ? "bg-success animate-pulse" : "bg-text-muted"
              }`}
            />
          </div>
          <p className="text-center text-[10px] uppercase tracking-[0.14em] text-text-muted">
            {statusLabel}
          </p>
        </div>
      </div>
    </aside>
  );
}
