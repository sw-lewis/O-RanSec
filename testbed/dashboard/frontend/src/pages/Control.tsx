import { useState } from "react";
import { Accordion, Badge, Button, Code, Grid, Group, ScrollArea, Select, Stack, Table, Text, Timeline } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlayerPlay, IconPlayerStop, IconRefresh, IconRoute, IconWaveSine } from "@tabler/icons-react";
import { get, post, usePoll } from "../api";
import { Panel, StatusBadge } from "../components/ui";
import { modals } from "../components/modals";
import { bytes, num } from "../fmt";
import type { Component, State } from "../types";

type Procedure = { id: string; status: string; step: number; steps: number; log: string[] };
type Audit = { ts: number; action: string; target?: string; result: string; error?: string };
type Ue = { id: string; status: Record<string, unknown>; sessions: Record<string, Record<string, unknown>> | null };

const ORDER = ["ue", "ran", "ric", "core", "cloud"];

export function Control({ state, onSelect }: { state: State; onSelect: (id: string) => void }) {
  const [proc, setProc] = useState<Procedure | null>(null);
  const audit = usePoll<Audit[]>("/api/audit?minutes=1440&limit=100", 6000);

  const act = (c: Component, action: string) => modals.confirm({
    title: `${action} ${c.label}`,
    body: action === "stop" ? `${c.label} will be scaled to 0. Dependent parts will lose service until you start it again.`
      : action === "start" ? `${c.label} will be scaled back to 1 replica.`
      : `The pod(s) of ${c.label} are replaced with fresh ones.`,
    confirm: action, danger: action !== "start",
    onConfirm: async () => {
      try { await post(`/api/components/${c.id}/${action}`); notifications.show({ color: "teal", message: `${action}: ${c.label}` }); }
      catch (e) { notifications.show({ color: "red", title: "Failed", message: String(e) }); }
    },
  });

  const restartNetwork = () => modals.confirm({
    title: "Safe restart of the mobile network",
    body: "Restarts in the order proven safe on this testbed: UPFs, then SMF, then gNBs, then UEs. Every step waits until the previous one is ready. UEs will briefly lose connectivity.",
    confirm: "restart", danger: true,
    onConfirm: async () => {
      const p = await post<Procedure>("/api/procedures/restart-network");
      setProc(p);
      const t = setInterval(async () => {
        const cur = await get<Procedure>(`/api/procedures/${p.id}`);
        setProc(cur);
        if (cur.status !== "running") clearInterval(t);
      }, 2000);
    },
  });

  const grouped = ORDER.map((layer) => [layer, state.components.filter((c) => c.layer === layer && !c.virtual)] as const);

  return (
    <Grid>
      <Grid.Col span={{ base: 12, xl: 8 }}>
        <Stack>
          <Panel title="Components" right={
            <Button size="xs" variant="light" color="orange" leftSection={<IconRoute size={14} />} onClick={restartNetwork}>Safe network restart</Button>}>
            <Table className="dense" highlightOnHover>
              <Table.Thead><Table.Tr>
                <Table.Th>Component</Table.Th><Table.Th>Status</Table.Th><Table.Th>Live check</Table.Th>
                <Table.Th>CPU</Table.Th><Table.Th>Mem</Table.Th><Table.Th ta="right">Actions</Table.Th>
              </Table.Tr></Table.Thead>
              <Table.Tbody>
                {grouped.map(([layer, list]) => list.length === 0 ? null : [
                  <Table.Tr key={layer}><Table.Td colSpan={6}><Text className="section-title">{layer}</Text></Table.Td></Table.Tr>,
                  ...list.map((c) => (
                    <Table.Tr key={c.id}>
                      <Table.Td><Text size="sm" fw={500} style={{ cursor: "pointer" }} onClick={() => onSelect(c.id)}>{c.label}</Text>
                        <Text size="xs" c="dimmed">{c.software}</Text></Table.Td>
                      <Table.Td><StatusBadge status={c.status} /></Table.Td>
                      <Table.Td><Text size="xs" c="dimmed" lineClamp={2}>{c.notes.join(" · ") || "–"}</Text></Table.Td>
                      <Table.Td className="mono">{num(c.cpu * 1000)}m</Table.Td>
                      <Table.Td className="mono">{bytes(c.mem)}</Table.Td>
                      <Table.Td>
                        <Group gap={4} justify="flex-end" wrap="nowrap">
                          <Button size="compact-xs" variant="subtle" onClick={() => act(c, "restart")}><IconRefresh size={14} /></Button>
                          {c.desired === 0
                            ? <Button size="compact-xs" variant="subtle" color="teal" onClick={() => act(c, "start")}><IconPlayerPlay size={14} /></Button>
                            : c.kind !== "DaemonSet" && <Button size="compact-xs" variant="subtle" color="red" onClick={() => act(c, "stop")}><IconPlayerStop size={14} /></Button>}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  )),
                ])}
              </Table.Tbody>
            </Table>
          </Panel>
          <UeControl state={state} />
        </Stack>
      </Grid.Col>

      <Grid.Col span={{ base: 12, xl: 4 }}>
        <Stack>
          {proc && (
            <Panel title="Procedure" right={<Badge color={proc.status === "done" ? "teal" : proc.status === "failed" ? "red" : "cyan"}>{proc.status}</Badge>}>
              <Timeline active={proc.step - 1} bulletSize={14} lineWidth={2}>
                {["UPFs", "SMF", "gNBs", "UEs"].map((s) => <Timeline.Item key={s} title={s} />)}
              </Timeline>
              <Code block mt="sm" style={{ fontSize: 11 }}>{proc.log.join("\n") || "starting…"}</Code>
            </Panel>
          )}
          <Panel title="Operator actions (audit log)">
            <ScrollArea h={520}>
              <Stack gap={6}>
                {(audit.data ?? []).map((a, i) => (
                  <Group key={i} gap={8} wrap="nowrap" align="flex-start">
                    <Text size="xs" className="mono" c="dimmed" style={{ whiteSpace: "nowrap" }}>{new Date(a.ts * 1000).toLocaleTimeString([], { hour12: false })}</Text>
                    <Text size="xs" style={{ flex: 1 }}>{a.action} <span className="dim">{a.target ?? ""}</span></Text>
                    <Badge size="xs" variant="light" color={a.result === "ok" ? "teal" : "red"}>{a.result}</Badge>
                  </Group>
                ))}
                {audit.data?.length === 0 && <Text size="xs" c="dimmed">No actions yet. Every button you press here is recorded.</Text>}
              </Stack>
            </ScrollArea>
          </Panel>
        </Stack>
      </Grid.Col>
    </Grid>
  );
}

function UeControl({ state }: { state: State }) {
  const groups = state.components.filter((c) => c.ueGroup);
  const [group, setGroup] = useState<string | null>(groups[0]?.id ?? null);
  const ues = usePoll<Ue[]>(group ? `/api/ran/ues/${group}` : null, 8000);
  const [out, setOut] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const run = async (label: string, fn: () => Promise<{ output: string }>) => {
    setBusy(true); setOut(`${label}…`);
    try { setOut((await fn()).output); ues.refresh(); }
    catch (e) { setOut(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Panel title="UE control (UERANSIM nr-cli)" right={
      <Group gap="xs">
        <Select size="xs" w={200} value={group} onChange={setGroup} data={groups.map((g) => ({ value: g.id, label: g.label }))} />
        <Button size="xs" variant="light" leftSection={<IconWaveSine size={14} />} loading={busy}
          onClick={() => run("traffic test", () => post(`/api/ran/traffic/${group}?count=20`))}>Traffic test</Button>
      </Group>}>
      {ues.error && <Text size="xs" c="red">{ues.error}</Text>}
      <Accordion variant="separated" chevronPosition="left">
        {(ues.data ?? []).map((u) => {
          const st = u.status as Record<string, string>;
          return (
            <Accordion.Item key={u.id} value={u.id}>
              <Accordion.Control>
                <Group gap="sm">
                  <Text size="sm" className="mono">{u.id}</Text>
                  <Badge size="xs" variant="light" color={String(st["rm-state"]).includes("REGISTERED") && !String(st["rm-state"]).includes("DE") ? "teal" : "yellow"}>{String(st["rm-state"] ?? "?")}</Badge>
                  <Badge size="xs" variant="outline" color="gray">{String(st["cm-state"] ?? "?")}</Badge>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Code block style={{ fontSize: 11 }}>{JSON.stringify({ status: u.status, sessions: u.sessions }, null, 2)}</Code>
                <Group mt="xs" gap="xs">
                  <Button size="xs" variant="default" disabled={busy}
                    onClick={() => run("release sessions", () => post(`/api/ran/ues/${group}/${u.id}`, { action: "ps-release-all" }))}>Release PDU sessions</Button>
                  <Button size="xs" variant="default" color="red" disabled={busy}
                    onClick={() => run("deregister", () => post(`/api/ran/ues/${group}/${u.id}`, { action: "deregister" }))}>Deregister</Button>
                </Group>
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
      {out && <Code block mt="sm" style={{ fontSize: 11, maxHeight: 220, overflow: "auto" }}>{out}</Code>}
    </Panel>
  );
}
