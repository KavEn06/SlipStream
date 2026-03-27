import { useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const toggleSidebar = () => setSidebarOpen((current) => !current);
  const header = useMemo(() => {
    if (location.pathname === "/") {
      return { eyebrow: "Home", title: "Dashboard" };
    }
    if (location.pathname === "/sessions") {
      return { eyebrow: "Library", title: "Sessions" };
    }
    if (/^\/sessions\/[^/]+\/laps\/[^/]+$/.test(location.pathname)) {
      return { eyebrow: "Analysis", title: "Lap Review" };
    }
    if (/^\/sessions\/[^/]+$/.test(location.pathname)) {
      return { eyebrow: "Sessions", title: "Session Detail" };
    }
    return { eyebrow: "SlipStream", title: "Telemetry Coach" };
  }, [location.pathname]);
  const showBackButton = location.pathname !== "/";

  return (
    <div className="flex min-h-screen">
      <Sidebar isOpen={sidebarOpen} onToggle={toggleSidebar} />
      <main className="flex-1 px-5 py-6 lg:px-8 lg:py-8">
        <div className="mb-6 flex items-center gap-3 min-w-0">
          {showBackButton && (
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/6 bg-white/[0.02] text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
              aria-label="Go back"
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
          )}
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.24em] text-text-muted">
              {header.eyebrow}
            </p>
            <p className="text-sm text-text-secondary">{header.title}</p>
          </div>
        </div>
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
