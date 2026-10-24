import { useEffect, useState } from "react";
import { Badge, Button, Divider, Drawer, Group, ScrollArea, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { modals } from "./modals";
import { notifications } from "@mantine/notifications";
import { IconPlayerPlay, IconPlayerStop, IconRefresh } from "@tabler/icons-react";
import { get, post } from "../api";
import { bps, bytes, clock, dur, num } from "../fmt";
import { IFACE } from "../theme";
import type { Component, Link, LogLine, State } from "../types";
import { StatusBadge } from "./ui";

export function ComponentDrawer({ id, state, onClose }: { id: string | null; state: State | null; onClose: () => void }) {
  const c = state?.components.find((x) => x.id === id) ?? null;
  const links = state?.links.filter((l) => l.a === id || l.b === id) ?? [];
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={560} title={
      c ? <Group gap="sm"><Text fw={700}>{c.label}</Text><StatusBadge status={c.status} /></Group> : id
    } overlayProps={{ backgroundOpacity: 0.3 }}>
      {c ? <Details c={c} links={links} /> : <Text c="dimmed">{id} is not part of the architecture model. It appeared because real traffic was seen from or to it.</Text>}
    </Drawer>
  );
}

function Details({ c, links }: { c: Component; links: Link[] }) {
  const [logs, setLogs] = useState<LogLine[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const wl = c.workload ?? c.id;

  useEffect(() => {
    if (c.virtual || !c.ns) return;
    let alive = true;
    const container = c.container ? `, container="${c.container}"` : "";
    const q = encodeURIComponent(`{namespace="${c.ns}", pod=~"${wl}-.*"${container}}`);
    const load = () => get<LogLine[]>(`/api/logs?query=${q}&minutes=60&limit=150`).then((d) => alive && setLogs(d)).catch(() => alive && setLogs([]));
    load();
    const t = setInterval(load, 4000);
    return () => { alive = false; clearInterval(t); };
  }, [c.id, c.ns, c.container, c.virtual, wl]);

  const act = (action: string) =>
    modals.confirm({
      title: `${action[0].toUpperCase()}${action.slice(1)} ${c.label}?`,
      body: c.container
        ? `${c.label} shares a pod with ${wl}; both will be affected.`
        : action === "stop" ? "It is scaled to 0 replicas. Anything depending on it will lose service." : "Kubernetes replaces the pod(s) with fresh ones.",
      confirm: action,
      danger: action !== "start",
      onConfirm: async () => {
        setBusy(action);
        try {
          await post(`/api/components/${c.id}/${action}`);
          notifications.show({ color: "teal", title: `${action} sent`, message: `${c.label}: the live view will follow the change.` });
        } catch (e) {
          notifications.show({ color: "red", title: `${action} failed`, message: String(e) });
        } finally { setBusy(null); }
      },
    });

  return (
    <Stack gap="md">
      <SimpleGrid cols={2} spacing="xs">
        <Field k="Software" v={c.software ?? "–"} />
        <Field k="Layer" v={c.layer} />
        <Field k={c.external ? "Host" : "Namespace"} v={c.external ? `${c.host ?? "external"} (outside the VM)` : c.ns ?? "–"} />
        <Field k="Workload" v={c.virtual ? "–" : `${c.kind ?? ""} ${wl}${c.container ? ` / ${c.container}` : ""}`} />
        <Field k="CPU" v={`${num(c.cpu * 1000)} mCPU`} />
        <Field k="Memory" v={bytes(c.mem)} />
      </SimpleGrid>

      {c.notes.length > 0 && (
        <Stack gap={4}>
          <Text className="section-title">Live checks</Text>
          {c.notes.map((n) => <Text key={n} size="sm">• {n}</Text>)}
        </Stack>
      )}

      {!c.virtual && (
        <Group>
          <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />} loading={busy === "restart"} onClick={() => act("restart")}>Restart</Button>
          {c.desired === 0
            ? <Button size="xs" variant="light" color="teal" leftSection={<IconPlayerPlay size={14} />} loading={busy === "start"} onClick={() => act("start")}>Start</Button>
            : c.kind !== "DaemonSet" && <Button size="xs" variant="light" color="red" leftSection={<IconPlayerStop size={14} />} loading={busy === "stop"} onClick={() => act("stop")}>Stop</Button>}
        </Group>
      )}

      <Divider label="Pods" labelPosition="left" />
      {c.pods.length === 0 ? <Text size="sm" c="dimmed">No pods.</Text> : (
        <Table className="dense" striped withRowBorders={false}>
          <Table.Thead><Table.Tr><Table.Th>Pod</Table.Th><Table.Th>IP</Table.Th><Table.Th>Ready</Table.Th><Table.Th>Restarts</Table.Th><Table.Th>Age</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>{c.pods.map((p) => (
            <Table.Tr key={p.name}>
              <Table.Td className="mono" style={{ fontSize: 11.5 }}>{p.name}</Table.Td>
              <Table.Td className="mono">{p.ip ?? "–"}</Table.Td>
              <Table.Td>{p.ready ? <Badge size="xs" color="teal" variant="light">ready</Badge> : <Badge size="xs" color="red" variant="light">{p.reason ?? p.phase}</Badge>}</Table.Td>
              <Table.Td className="mono">{p.restarts}</Table.Td>
              <Table.Td className="mono">{dur(p.age)}</Table.Td>
            </Table.Tr>))}
          </Table.Tbody>
        </Table>
      )}

      <Divider label="Links (measured)" labelPosition="left" />
      {links.length === 0 ? <Text size="sm" c="dimmed">No links.</Text> : (
        <Table className="dense" withRowBorders={false}>
          <Table.Tbody>{links.map((l) => (
            <Table.Tr key={`${l.a}-${l.b}-${l.iface}`}>
              <Table.Td><Badge size="xs" variant="outline" style={{ color: IFACE[l.iface]?.color, borderColor: IFACE[l.iface]?.color }}>{l.iface}</Badge></Table.Td>
              <Table.Td fz="xs">{l.a === c.id ? l.b : l.a}</Table.Td>
              <Table.Td className="mono">{bps(l.bps)}</Table.Td>
              <Table.Td c="dimmed" fz="xs">{l.status}{l.flows ? ` · ${l.flows} flows` : ""}</Table.Td>
            </Table.Tr>))}
          </Table.Tbody>
        </Table>
      )}

      {!c.virtual && (
        <>
          <Divider label="Recent logs (Loki, last hour)" labelPosition="left" />
          <ScrollArea h={300} type="auto" style={{ background: "#05080c", borderRadius: 8, padding: 8 }}>
            {logs === null ? <Text size="xs" c="dimmed">Loading…</Text> : logs.length === 0 ? <Text size="xs" c="dimmed">No log lines in the last hour.</Text> :
              logs.map((l, i) => (
                <div key={i} className="logline">
                  <span className="dim">{clock(l.ts)} </span>
                  <span style={{ color: levelColor(l.labels.level) }}>{l.line}</span>
                </div>))}
          </ScrollArea>
        </>
      )}
    </Stack>
  );
}

export function levelColor(level?: string) {
  switch ((level ?? "").toLowerCase()) {
    case "error": case "fatal": case "err": case "crit": return "#ff7b86";
    case "warning": case "warn": return "#f5c451";
    case "debug": case "trace": return "#6b7a8c";
    default: return "#cbd5e1";
  }
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <Text size="10.5px" c="dimmed" tt="uppercase" style={{ letterSpacing: ".06em" }}>{k}</Text>
      <Text size="sm" className="mono" truncate>{v}</Text>
    </div>
  );
}
