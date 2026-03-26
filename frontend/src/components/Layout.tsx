import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";

export function Layout({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex min-h-screen">
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onOpen={() => setSidebarOpen(true)}
      />
      <main className="flex-1 px-5 py-6 lg:px-8 lg:py-8">
        <div className="mb-6 flex items-center gap-3">
          <button
            type="button"
            onClick={() => setSidebarOpen((current) => !current)}
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/6 bg-white/[0.02] text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
            aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
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
                d={
                  sidebarOpen
                    ? "M15 6l-6 6 6 6"
                    : "M9 6l6 6-6 6"
                }
              />
            </svg>
          </button>
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.24em] text-text-muted">
              Home
            </p>
            <p className="text-sm text-text-secondary">Sessions</p>
          </div>
        </div>
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
