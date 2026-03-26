import { Link, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CaptureStatus } from "../types";

const NAV_ITEMS = [
  { path: "/", label: "Home" },
  { path: "/sessions", label: "Sessions" },
];

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onOpen: () => void;
}

export function Sidebar({ isOpen, onClose, onOpen }: SidebarProps) {
  const location = useLocation();
  const [capture, setCapture] = useState<CaptureStatus | null>(null);

  useEffect(() => {
    const poll = () =>
      api.getCaptureStatus().then(setCapture).catch(() => {});
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside
      className={`shrink-0 border-r border-white/4 bg-black/30 backdrop-blur transition-all duration-200 ${
        isOpen ? "w-56" : "w-0 overflow-hidden border-r-0"
      }`}
    >
      <div
        className={`flex h-full flex-col transition-opacity duration-200 ${
          isOpen ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        <div className="flex items-start justify-between px-6 pb-5 pt-7">
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
            onClick={onClose}
            className="mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
            aria-label="Close sidebar"
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

        <nav className="flex-1 px-3 py-2 space-y-1">
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

        {capture && (
          <div className="mx-4 mb-4 rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-3">
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${
                  capture.is_active
                    ? "bg-success animate-pulse"
                    : "bg-text-muted"
                }`}
              />
              <span className="text-xs text-text-secondary truncate">
                {capture.is_active
                  ? `Recording ${capture.session_id ?? ""}`
                  : "Idle"}
              </span>
            </div>
            {capture.is_active && (
              <p className="text-[11px] text-text-muted mt-1 pl-4">
                {capture.laps_detected} laps detected
              </p>
            )}
          </div>
        )}
      </div>
      {!isOpen && (
        <button
          type="button"
          onClick={onOpen}
          className="sr-only"
          aria-label="Open sidebar"
        />
      )}
    </aside>
  );
}
