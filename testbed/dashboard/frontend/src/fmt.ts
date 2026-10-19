export function bps(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "–";
  if (v < 1) return "0 bit/s";
  const u = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s"];
  let i = 0;
  while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

export function bytes(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "–";
  const u = ["B", "KiB", "MiB", "GiB"];
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

export function num(v: number | null | undefined, digits = 0): string {
  return v == null || !isFinite(v) ? "–" : v.toFixed(digits);
}

export function pct(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "–" : `${(v * 100).toFixed(0)}%`;
}

export function dur(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "–";
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function clock(tsNs: number): string {
  const d = new Date(tsNs / 1e6);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

export function ago(iso: string | null): string {
  if (!iso) return "–";
  return dur((Date.now() - new Date(iso).getTime()) / 1000) + " ago";
}
