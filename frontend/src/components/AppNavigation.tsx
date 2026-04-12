import { type RefObject } from "react";
import { Link } from "react-router-dom";
import { useCaptureController } from "../hooks/useCaptureController";

export const NAV_ITEMS = [
  { path: "/", label: "Home" },
  { path: "/sessions", label: "Sessions" },
  { path: "/analysis", label: "Analysis" },
  { path: "/compare/laps", label: "Compare" },
] as const;

function isNavItemActive(pathname: string, path: string): boolean {
  if (path === "/") {
    return pathname === "/";
  }

  if (path === "/sessions") {
    return pathname.startsWith("/sessions");
  }

  if (path === "/analysis") {
    return pathname.startsWith("/analysis");
  }

  if (path === "/compare/laps") {
    return pathname.startsWith("/compare");
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
        d="M3.75 7.5A1.5 1.5 0 0 1 5.25 6h4.19c.398 0 .78.158 1.061.439l1.06 1.061H18.75a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H5.25a1.5 1.5 0 0 1-1.5-1.5v-9Z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M3.75 10.5h16.5"
      />
    </svg>
  );
}

function CompareIcon() {
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
        d="M4.5 7.5h15"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M4.5 12h15"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M4.5 16.5h15"
      />
      <circle cx="8" cy="7.5" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="11" cy="16.5" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function AnalysisIcon() {
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
        d="M5.25 18.75V11.25"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M12 18.75V7.5"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M18.75 18.75V4.5"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M3.75 19.5h16.5"
      />
    </svg>
  );
}

function AppearanceIcon() {
  return (
    <svg
      className="h-4 w-4"
      fill="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M9.596 2.553A1 1 0 0 1 10.585 2h2.83a1 1 0 0 1 .989.553l.673 1.366a1 1 0 0 0 .58.49l1.478.43a1 1 0 0 1 .699.902l.102 1.52a1 1 0 0 0 .352.677l1.18.964a1 1 0 0 1 .274 1.13l-.875 2.691a1 1 0 0 0 0 .618l.875 2.691a1 1 0 0 1-.274 1.13l-1.18.964a1 1 0 0 0-.352.678l-.102 1.518a1 1 0 0 1-.699.903l-1.478.43a1 1 0 0 0-.58.49l-.673 1.366a1 1 0 0 1-.99.553h-2.829a1 1 0 0 1-.99-.553l-.672-1.365a1 1 0 0 0-.58-.491l-1.479-.43a1 1 0 0 1-.698-.903l-.103-1.518a1 1 0 0 0-.351-.678l-1.18-.964a1 1 0 0 1-.274-1.13l.875-2.69a1 1 0 0 0 0-.619l-.875-2.69a1 1 0 0 1 .274-1.13l1.18-.964a1 1 0 0 0 .351-.678l.103-1.519a1 1 0 0 1 .698-.902l1.478-.43a1 1 0 0 0 .58-.49l.673-1.366ZM12 8.25a3.75 3.75 0 1 0 0 7.5a3.75 3.75 0 0 0 0-7.5Z"
      />
    </svg>
  );
}

function getItemIcon(path: string) {
  if (path === "/") {
    return <HomeIcon />;
  }

  if (path === "/compare/laps") {
    return <CompareIcon />;
  }

  if (path === "/analysis") {
    return <AnalysisIcon />;
  }

  return <SessionsIcon />;
}

export function SlimNavRail({
  pathname,
  appearanceOpen,
  appearanceButtonRef,
  onToggleAppearance,
}: {
  pathname: string;
  appearanceOpen: boolean;
  appearanceButtonRef: RefObject<HTMLButtonElement | null>;
  onToggleAppearance: () => void;
}) {
  const capture = useCaptureController();
  const isActive = capture.status?.is_active ?? false;
  const statusLabel = isActive
    ? `${capture.status?.laps_detected ?? 0} laps`
    : "Standby";

  return (
    <aside className="sticky top-0 z-[60] h-screen shrink-0 self-start border-r border-border/70 bg-surface-1/80 backdrop-blur-xl">
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
                aria-current={active ? "page" : undefined}
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
            ref={appearanceButtonRef}
            type="button"
            onClick={onToggleAppearance}
            aria-label="Appearance"
            aria-pressed={appearanceOpen}
            aria-controls="appearance-drawer"
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
