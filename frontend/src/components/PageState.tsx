import type { ReactNode } from "react";

export function SurfaceSkeleton({
  className = "",
  rows = 4,
}: {
  className?: string;
  rows?: number;
}) {
  return (
    <div
      className={`density-analysis-chart rounded-[28px] border border-border/70 bg-surface-1/85 ${className}`.trim()}
      aria-hidden="true"
    >
      <div className="animate-pulse space-y-3">
        <div className="h-4 w-28 rounded-full bg-surface-3/90" />
        {Array.from({ length: rows }).map((_, index) => (
          <div
            key={index}
            className={`h-10 rounded-2xl bg-surface-2/86 ${
              index === rows - 1 ? "w-2/3" : "w-full"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

export function SurfaceMessage({
  title,
  message,
  actionLabel,
  onAction,
  tone = "default",
  children,
  className = "",
}: {
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
  tone?: "default" | "danger";
  children?: ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "danger"
      ? "border-danger/20 bg-danger/8"
      : "border-border/70 bg-surface-1/85";

  return (
    <div
      className={`density-analysis-chart rounded-[28px] border text-center ${toneClass} ${className}`.trim()}
    >
      <p className="text-base font-medium text-text-primary">{title}</p>
      {message && (
        <p className="mt-2 text-sm text-text-secondary">{message}</p>
      )}
      {children}
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="motion-safe-color mt-4 inline-flex h-10 items-center rounded-full border border-accent/20 bg-accent/10 px-4 text-sm font-medium text-accent hover:bg-accent/16 cursor-pointer"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

export function RouteLoadingFallback() {
  return (
    <div className="mx-auto max-w-7xl space-y-5" aria-hidden="true">
      <SurfaceSkeleton rows={3} />
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <SurfaceSkeleton rows={4} />
        <SurfaceSkeleton rows={5} />
      </div>
      <SurfaceSkeleton rows={6} />
    </div>
  );
}
