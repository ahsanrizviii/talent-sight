// Dates and times, written the same way everywhere.
// The browser's own time zone is used, so a time always means what the reader expects.

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function shortDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "in 2 hours", "in 3 days", "25 minutes ago". Used beside a scheduled time. */
export function untilText(iso: string): string {
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  const ahead = minutes >= 0;
  const size = Math.abs(minutes);

  let amount: string;
  if (size < 1) amount = "less than a minute";
  else if (size < 60) amount = `${size} minute${size === 1 ? "" : "s"}`;
  else if (size < 60 * 24) {
    const hours = Math.round(size / 60);
    amount = `${hours} hour${hours === 1 ? "" : "s"}`;
  } else {
    const days = Math.round(size / (60 * 24));
    amount = `${days} day${days === 1 ? "" : "s"}`;
  }
  return ahead ? `in ${amount}` : `${amount} ago`;
}

/** "15 min" or "1 h 05 min", from a number of seconds. */
export function lengthText(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}
