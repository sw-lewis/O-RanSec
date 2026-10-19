import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";
import { IFACE } from "../theme";
import { bps as fmtBps } from "../fmt";
import type { Link } from "../types";

/** Particles per direction and seconds per trip, from the measured bit rate. */
function motion(bitRate: number) {
  if (bitRate < 1) return { n: 0, dur: 0 };
  const lg = Math.log10(bitRate); // 1 kbit/s -> 3, 1 Mbit/s -> 6
  return {
    n: Math.max(1, Math.min(6, Math.round(lg - 1.5))),
    dur: Math.max(0.5, Math.min(4, 5.5 - lg * 0.7)),
  };
}

export function FlowEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected } = props;
  const link = (data as { link: Link; dimmed?: boolean }).link;
  const dimmed = (data as { dimmed?: boolean }).dimmed;
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const color = link.expected ? (IFACE[link.iface]?.color ?? "#94a3b8") : IFACE.other.color;
  const st = link.status;
  const { n, dur } = motion(link.bps);
  const opacity = dimmed ? 0.12 : st === "idle" ? 0.28 : st === "down" ? 0.5 : 0.9;
  const width = st === "active" ? Math.min(5, 1.6 + Math.log10(Math.max(link.bps, 1)) / 2.2) : 1.4;
  const dash = st === "down" ? "5 5" : !link.expected ? "7 4" : st === "idle" ? "2 5" : undefined;
  return (
    <>
      <BaseEdge id={id} path={path}
        style={{ stroke: st === "down" ? "var(--bad)" : color, strokeWidth: selected ? width + 1.5 : width,
                 strokeDasharray: dash, opacity, transition: "stroke-width .4s" }} />
      {!dimmed && st === "active" && Array.from({ length: n }).map((_, i) => (
        <g key={`f${i}`}>
          <circle r={3} fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }}>
            <animateMotion dur={`${dur}s`} begin={`${(i * dur) / n}s`} repeatCount="indefinite" path={path} />
          </circle>
          {/* return direction: traffic on these links is two-way */}
          <circle r={2} fill={color} opacity={0.55}>
            <animateMotion dur={`${dur * 1.15}s`} begin={`${(i * dur) / n + dur / 2}s`} repeatCount="indefinite"
                           path={path} keyPoints="1;0" keyTimes="0;1" calcMode="linear" />
          </circle>
        </g>
      ))}
      {!dimmed && (st === "active" || selected || !link.expected) && (
        <EdgeLabelRenderer>
          <div className="mono" style={{
            position: "absolute", transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`,
            fontSize: 10.5, padding: "1px 6px", borderRadius: 6, background: "#0b1119e6",
            border: `1px solid ${color}55`, color, pointerEvents: "none", whiteSpace: "nowrap",
          }}>
            {link.expected ? link.iface : `⚠ ${link.iface}`} · {fmtBps(link.bps)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
