import { Text } from "@mantine/core";
import { bps as fmtBps } from "../fmt";

export type Hop = { id: string; label: string; sub: string; up: boolean };
export type Leg = { label: string; bps: number | null; color: string; active: boolean };

/** One device's end-to-end path. Each leg's dots move at a speed set by the traffic measured on it. */
export function PathFlow({ hops, legs }: { hops: Hop[]; legs: Leg[] }) {
  const W = 1200, H = 190, pad = 70;
  const step = (W - pad * 2) / (hops.length - 1);
  const y = 80;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      <defs>
        <filter id="glow"><feGaussianBlur stdDeviation="2.5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {legs.map((l, i) => {
        const x1 = pad + i * step + 34, x2 = pad + (i + 1) * step - 34;
        const path = `M ${x1} ${y} L ${x2} ${y}`;
        const v = l.bps ?? 0;
        const lg = v > 1 ? Math.log10(v) : 0;
        const n = l.active ? Math.max(1, Math.min(6, Math.round(lg - 1.5))) : 0;
        const dur = Math.max(0.5, Math.min(4, 5.5 - lg * 0.7));
        return (
          <g key={i}>
            <path d={path} stroke={l.color} strokeWidth={l.active ? 3 : 1.5} opacity={l.active ? 0.85 : 0.3}
                  strokeDasharray={l.active ? undefined : "4 6"} fill="none" />
            {Array.from({ length: n }).map((_, k) => (
              <circle key={k} r={4.5} fill={l.color} filter="url(#glow)">
                <animateMotion dur={`${dur}s`} begin={`${(k * dur) / n}s`} repeatCount="indefinite" path={path} />
              </circle>
            ))}
            <text x={(x1 + x2) / 2} y={y - 16} textAnchor="middle" fill={l.color} fontSize="12" fontFamily="JetBrains Mono, monospace">
              {l.bps == null ? "" : fmtBps(l.bps)}
            </text>
            <text x={(x1 + x2) / 2} y={y + 26} textAnchor="middle" fill="#64748b" fontSize="11">{l.label}</text>
          </g>
        );
      })}
      {hops.map((h, i) => {
        const x = pad + i * step;
        return (
          <g key={h.id}>
            <circle cx={x} cy={y} r={30} fill="#121a24" stroke={h.up ? "#2fd27a" : "#ff4d5a"} strokeWidth={2.5} />
            <circle cx={x} cy={y} r={6} fill={h.up ? "#2fd27a" : "#ff4d5a"} />
            <text x={x} y={y + 56} textAnchor="middle" fill="#e2e8f0" fontSize="13" fontWeight={600}>{h.label}</text>
            <text x={x} y={y + 73} textAnchor="middle" fill="#8b97a7" fontSize="11">{h.sub}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function PathLegend() {
  return <Text size="xs" c="dimmed">Moving dots show traffic measured on each hop this second. Green ring = up, red = down or not connected.</Text>;
}
