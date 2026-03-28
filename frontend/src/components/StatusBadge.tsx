export function StatusBadge({ processed }: { processed: boolean }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
        processed
          ? "border-success/18 bg-success/12 text-success"
          : "border-warning/18 bg-warning/12 text-warning"
      }`}
    >
      {processed ? "Processed" : "Raw Only"}
    </span>
  );
}
