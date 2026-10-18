export function formatDuration(durationMs: number | null | undefined) {
  if (durationMs == null) return "—";
  const seconds = Math.floor(durationMs / 1000);
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
}
