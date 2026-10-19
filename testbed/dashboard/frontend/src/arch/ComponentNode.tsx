import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Group, Text } from "@mantine/core";
import { StatusDot } from "../components/ui";
import { STATUS } from "../theme";
import { NODE_H, NODE_W } from "./layout";
import type { Component } from "../types";

const SIDES = [Position.Left, Position.Right, Position.Top, Position.Bottom];

export function ComponentNode({ data, selected }: NodeProps) {
  const c = (data as { c: Component; dimmed?: boolean; sliceColor?: string }).c;
  const dimmed = (data as { dimmed?: boolean }).dimmed;
  const sliceColor = (data as { sliceColor?: string }).sliceColor;
  const s = STATUS[c.status] ?? STATUS.unknown;
  const unknown = c.layer === "unknown";
  return (
    <div style={{
      width: NODE_W, height: NODE_H, padding: "8px 11px", borderRadius: 10,
      background: unknown ? "#2a0f14" : "var(--panel-2)",
      border: `1px solid ${selected ? "#e2e8f0" : unknown ? "var(--bad)" : c.status === "up" ? "#233142" : s.color}`,
      boxShadow: selected ? "0 0 0 2px #22d3ee55" : c.status === "down" ? `0 0 14px ${s.color}55` : "0 2px 10px #0006",
      opacity: dimmed ? 0.25 : 1, transition: "opacity .25s", cursor: "pointer",
      borderLeft: sliceColor ? `4px solid ${sliceColor}` : undefined,
    }}>
      {SIDES.map((p) => (
        <span key={p}>
          <Handle type="source" id={`s-${p}`} position={p} style={{ opacity: 0 }} />
          <Handle type="target" id={`t-${p}`} position={p} style={{ opacity: 0 }} />
        </span>
      ))}
      <Group gap={8} wrap="nowrap">
        <StatusDot status={c.status} />
        <Text fw={600} size="sm" truncate>{c.label}</Text>
      </Group>
      <Text size="10.5px" c="dimmed" truncate mt={2}>{unknown ? "Not in the architecture model" : c.software ?? ""}</Text>
      <Text size="10.5px" truncate mt={2} style={{ color: c.status === "up" ? "#94a3b8" : s.color }}>
        {c.notes[0] ?? s.label}
      </Text>
    </div>
  );
}

export function ZoneNode({ data }: NodeProps) {
  const z = data as { label: string; w: number; h: number; color: string };
  return (
    <div style={{ width: z.w, height: z.h, borderRadius: 14, border: `1px dashed ${z.color}40`,
                  background: `${z.color}07`, pointerEvents: "none" }}>
      <Text size="11px" fw={600} tt="uppercase" style={{ letterSpacing: ".08em", color: `${z.color}cc`, padding: "6px 12px" }}>
        {z.label}
      </Text>
    </div>
  );
}
