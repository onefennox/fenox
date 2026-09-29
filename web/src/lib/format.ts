/** Join class names, dropping anything falsy. */
export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

/** Bytes as something a person reads: 143 MB, not 150417016. */
export function formatBytes(bytes: number | null | undefined, decimals = 1): string {
  const value = Number(bytes ?? 0);
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const scaled = value / 1024 ** power;
  return `${scaled.toFixed(power === 0 ? 0 : decimals)} ${units[power]}`;
}

/** "2 minutes ago" — short, and never "in the future" because of clock skew. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days}d ago` : `${Math.round(days / 30)}mo ago`;
}

/** Thousands separators, for counts and sizes shown in tables. */
export function formatNumber(value: number | null | undefined): string {
  return Number(value ?? 0).toLocaleString();
}
