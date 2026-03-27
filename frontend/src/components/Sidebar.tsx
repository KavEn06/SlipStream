import { Link, useLocation } from "react-router-dom";
import { useCaptureController } from "../hooks/useCaptureController";

const NAV_ITEMS = [
  { path: "/", label: "Home" },
  { path: "/sessions", label: "Sessions" },
];

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  const location = useLocation();
  const capture = useCaptureController();

  return (
    <aside
      className={`shrink-0 border-r border-white/4 bg-black/30 backdrop-blur transition-all duration-200 ${
        isOpen ? "w-56" : "w-18"
      }`}
    >
      {isOpen ? (
        <div className="flex h-full flex-col">
          <div className="flex items-start justify-between gap-3 px-6 pb-5 pt-7">
            <div>
              <h1 className="text-sm font-semibold tracking-[0.32em] text-white">
                SLIPSTREAM
              </h1>
              <p className="mt-1 text-[11px] tracking-[0.2em] text-text-muted uppercase">
                Telemetry Coach
              </p>
            </div>
            <button
              type="button"
              onClick={onToggle}
              className="inline-flex size-10 shrink-0 aspect-square items-center justify-center rounded-md border border-white/6 bg-white/[0.02] p-0 text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
              aria-label="Collapse sidebar"
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
                  d="M15 6l-6 6 6 6"
                />
              </svg>
            </button>
          </div>

          <nav className="flex-1 px-3 py-4 space-y-1">
            {NAV_ITEMS.map((item) => {
              const active =
                item.path === "/"
                  ? location.pathname === "/"
                  : item.path === "/sessions"
                    ? location.pathname.startsWith("/sessions")
                    : location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`block rounded-full px-4 py-2 text-sm transition-colors ${
                    active
                      ? "bg-white/4 text-accent"
                      : "text-text-secondary hover:bg-white/3 hover:text-white"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {capture.status && (
            <div className="mx-4 mb-4 rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-3">
              <div className="flex items-center gap-2">
                <div
                  className={`w-2 h-2 rounded-full ${
                    capture.status.is_active
                      ? "bg-success animate-pulse"
                      : "bg-text-muted"
                  }`}
                />
                <span className="text-xs text-text-secondary truncate">
                  {capture.status.is_active
                    ? `Recording ${capture.status.session_id ?? ""}`
                    : "Idle"}
                </span>
              </div>
              {capture.status.is_active && (
                <p className="text-[11px] text-text-muted mt-1 pl-4">
                  {capture.status.laps_detected} laps detected
                </p>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="flex h-full flex-col items-center gap-3 px-2 py-4">
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex size-10 shrink-0 aspect-square items-center justify-center rounded-md border border-white/6 bg-white/[0.02] p-0 text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
            aria-label="Open sidebar"
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
                d="M5 7.5h14"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.8}
                d="M5 12h14"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.8}
                d="M5 16.5h14"
              />
            </svg>
          </button>
        </div>
      )}
    </aside>
  );
}
