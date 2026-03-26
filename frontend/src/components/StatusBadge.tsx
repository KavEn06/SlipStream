export function StatusBadge({ processed }: { processed: boolean }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
        processed
          ? "bg-success/12 text-success"
          : "bg-warning/12 text-warning"
      }`}
    >
      {processed ? "Processed" : "Raw Only"}
    </span>
  );
}
