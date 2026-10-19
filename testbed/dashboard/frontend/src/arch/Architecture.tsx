import { useMemo, useState } from "react";
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { Badge, Chip, Group, Paper, SegmentedControl, Stack, Text } from "@mantine/core";
import { ComponentNode, ZoneNode } from "./ComponentNode";
import { FlowEdge } from "./FlowEdge";
import { POS, ZONES, NODE_H, NODE_W, devicePos, fallbackPos } from "./layout";
import { IFACE, STATUS } from "../theme";
import { bps } from "../fmt";
import type { Component, State } from "../types";

const nodeTypes = { comp: ComponentNode, zone: ZoneNode };
const edgeTypes = { flow: FlowEdge };

function handles(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? ["s-right", "t-left"] : ["s-left", "t-right"];
  return dy >= 0 ? ["s-bottom", "t-top"] : ["s-top", "t-bottom"];
}

export function Architecture({ state, onSelect, selected }: { state: State; onSelect: (id: string) => void; selected: string | null }) {
  const [ifaces, setIfaces] = useState<string[]>(["Uu", "N2", "N3", "N4", "N6", "SBI", "E2", "E42", "DB", "other"]);
  const [slice, setSlice] = useState("all");

  const { nodes, edges } = useMemo(() => {
    const byId = new Map(state.components.map((c) => [c.id, c]));
    const sliceOf = new Map(state.slices.map((s) => [s.id, s.color]));
    // endpoints of unexpected links that are not in the model
    const extra: Component[] = [];
    for (const l of state.links) for (const id of [l.a, l.b]) {
      if (!byId.has(id) && !extra.find((e) => e.id === id)) {
        extra.push({ id, label: id, layer: "unknown", status: "unknown", notes: ["seen in live traffic"], pods: [], cpu: 0, mem: 0 });
      }
    }
    const all = [...state.components.filter((c) => POS[c.id] || c.layer !== "cloud"), ...extra]
      .filter((c) => c.layer !== "cloud");
    const pos = new Map<string, { x: number; y: number }>();
    let k = 0, dv = 0;
    for (const c of all) pos.set(c.id, POS[c.id] ?? (c.device ? devicePos(dv++) : fallbackPos(k++)));

    const inSlice = (c: Component) => slice === "all" || !c.slice || c.slice === slice;
    const nodes: Node[] = [
      ...ZONES.map((z) => ({ id: z.id, type: "zone", position: { x: z.x, y: z.y }, data: z, selectable: false, draggable: false, zIndex: -1 })),
      ...all.map((c) => ({
        id: c.id, type: "comp", position: pos.get(c.id)!, draggable: true,
        data: { c, dimmed: !inSlice(c), sliceColor: c.slice ? sliceOf.get(c.slice) : undefined },
        selected: selected === c.id, width: NODE_W, height: NODE_H,
      })),
    ];
    const edges: Edge[] = state.links
      .filter((l) => pos.has(l.a) && pos.has(l.b))
      .filter((l) => ifaces.includes(l.expected ? l.iface : "other"))
      .map((l) => {
        const [sh, th] = handles(pos.get(l.a)!, pos.get(l.b)!);
        const ca = byId.get(l.a), cb = byId.get(l.b);
        const dimmed = slice !== "all" && [ca, cb].some((c) => c?.slice && c.slice !== slice);
        return { id: `${l.a}|${l.b}|${l.iface}`, source: l.a, target: l.b, sourceHandle: sh, targetHandle: th,
                 type: "flow", data: { link: l, dimmed }, zIndex: l.status === "active" ? 2 : 1 };
      });
    return { nodes, edges };
  }, [state, ifaces, slice, selected]);

  const active = state.links.filter((l) => l.status === "active");
  const unexpected = state.links.filter((l) => !l.expected);

  return (
    <Stack gap="sm">
      <Paper p="sm" radius="md">
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="md">
          <Stack gap={8}>
            <Group gap={6}>
              <Text className="section-title" w={92}>Interfaces</Text>
              <Chip.Group multiple value={ifaces} onChange={setIfaces}>
                <Group gap={4}>
                  {Object.entries(IFACE).map(([k, v]) => (
                    <Chip key={k} value={k} size="xs" variant="outline" color="gray"
                          styles={{ label: { color: v.color, borderColor: `${v.color}66` } }}>{k === "other" ? "unexpected" : k}</Chip>
                  ))}
                </Group>
              </Chip.Group>
            </Group>
            <Group gap={6}>
              <Text className="section-title" w={92}>Slice focus</Text>
              <SegmentedControl size="xs" value={slice} onChange={setSlice}
                data={[{ value: "all", label: "All" }, ...state.slices.map((s) => ({ value: s.id, label: s.label }))]} />
            </Group>
          </Stack>
          <Group gap="lg" align="flex-start">
            <Stat label="Active links" value={`${active.length} / ${state.links.length}`} />
            <Stat label="N3 user plane" value={bps(state.kpis.n3Bps)} />
            <Stat label="N6 Internet" value={bps(state.kpis.n6Bps)} />
            <Stat label="Unexpected links" value={String(unexpected.length)} color={unexpected.length ? "var(--bad)" : undefined} />
            <Badge size="sm" variant="dot" color={state.sources.flowmon?.ok ? "teal" : "red"} mt={4}>flowmon {state.sources.flowmon?.ok ? "live" : "stale"}</Badge>
          </Group>
        </Group>
        <Text size="10.5px" c="dimmed" mt={6}>
          Moving dots are traffic measured every second: kernel connection tracking (flowmon) for pod-to-pod links, and the
          srsRAN gNB's per-UE MAC bit rates for the srsUE radio link. Faster and denser means more bits per second.
          Dotted = defined but idle. Red dashed = traffic the architecture does not expect.
        </Text>
      </Paper>
      <div style={{ height: "calc(100vh - 230px)", minHeight: 520, borderRadius: 12, overflow: "hidden", border: "1px solid var(--line)" }}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
                   fitView fitViewOptions={{ padding: 0.04 }} minZoom={0.2} maxZoom={2}
                   onNodeClick={(_, n) => n.type === "comp" && onSelect(n.id)} proOptions={{ hideAttribution: true }}>
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1b2533" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeColor={(n) => n.type === "zone" ? "transparent" :
            (STATUS[((n.data as { c: Component }).c?.status) ?? "unknown"]?.color ?? "#555")} maskColor="#080c12cc" />
        </ReactFlow>
      </div>
    </Stack>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <Text size="10.5px" c="dimmed" tt="uppercase" style={{ letterSpacing: ".06em" }}>{label}</Text>
      <Text className="mono" fw={600} size="sm" style={{ color }}>{value}</Text>
    </div>
  );
}
