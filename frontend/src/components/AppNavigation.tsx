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
        d="M4.5 6.75h15"
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
        d="M4.5 17.25h15"
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

export function SlimNavRail({ pathname }: { pathname: string }) {
  const capture = useCaptureController();
  const isActive = capture.status?.is_active ?? false;
  const statusLabel = isActive
    ? `${capture.status?.laps_detected ?? 0} laps`
    : "Standby";

  return (
    <aside className="shrink-0 border-r border-white/4 bg-black/30 backdrop-blur">
      <div className="flex min-h-screen w-20 flex-col items-center px-3 py-5">
        <Link
          to="/"
          className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-white/8 bg-white/[0.03] text-sm font-semibold tracking-[0.2em] text-white"
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
                    : "border-white/6 bg-white/[0.02] text-text-secondary hover:bg-white/[0.04] hover:text-white"
                }`}
              >
                {getItemIcon(item.path)}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col items-center gap-2 pb-1">
          <div
            className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/8 bg-white/[0.03]"
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
