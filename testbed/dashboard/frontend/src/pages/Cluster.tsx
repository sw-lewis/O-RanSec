import { useState } from "react";
import { Badge, Grid, Group, ScrollArea, SegmentedControl, Stack, Table, Text, TextInput } from "@mantine/core";
import { usePoll } from "../api";
import { Panel } from "../components/ui";
import { ago, dur } from "../fmt";
import type { KEvent } from "../types";

type Pod = { ns: string; name: string; workload: string; phase: string; ready: boolean; reason: string | null; ip: string | null;
             restarts: number; age: number | null; images: string[] };
type Workload = { ns: string; name: string; kind: string; desired: number; ready: number };
type Cluster = { node: Record<string, string | boolean>; pods: Pod[]; events: KEvent[]; workloads: Workload[] };
type Target = { job: string; instance: string; health: string; lastError: string };

export function ClusterPage() {
  const cl = usePoll<Cluster>("/api/cluster", 5000);
  const targets = usePoll<Target[]>("/api/metrics/targets", 10000);
  const [filter, setFilter] = useState("");
  const [scope, setScope] = useState("sixg");
  const pods = (cl.data?.pods ?? [])
    .filter((p) => scope === "all" || p.ns.startsWith("sixg-"))
    .filter((p) => !filter || p.name.includes(filter) || p.ns.includes(filter))
    .sort((a, b) => a.ns.localeCompare(b.ns) || a.name.localeCompare(b.name));

  return (
    <Grid>
      <Grid.Col span={{ base: 12, xl: 8 }}>
        <Panel title={`Pods (${pods.length})`} right={
          <Group gap="xs">
            <SegmentedControl size="xs" value={scope} onChange={setScope} data={[{ value: "sixg", label: "Testbed" }, { value: "all", label: "All" }]} />
            <TextInput size="xs" placeholder="filter" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} />
          </Group>}>
          <ScrollArea h="calc(100vh - 200px)">
            <Table className="dense" striped highlightOnHover stickyHeader>
              <Table.Thead><Table.Tr><Table.Th>Namespace</Table.Th><Table.Th>Pod</Table.Th><Table.Th>State</Table.Th>
                <Table.Th>IP</Table.Th><Table.Th>Restarts</Table.Th><Table.Th>Age</Table.Th><Table.Th>Image</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {pods.map((p) => (
                  <Table.Tr key={`${p.ns}/${p.name}`}>
                    <Table.Td c="dimmed">{p.ns}</Table.Td>
                    <Table.Td className="mono" style={{ fontSize: 11.5 }}>{p.name}</Table.Td>
                    <Table.Td><Badge size="xs" variant="light" color={p.ready ? "teal" : p.phase === "Succeeded" ? "gray" : "red"}>{p.ready ? "Ready" : p.reason ?? p.phase}</Badge></Table.Td>
                    <Table.Td className="mono">{p.ip ?? "–"}</Table.Td>
                    <Table.Td className="mono" c={p.restarts ? "yellow" : undefined}>{p.restarts}</Table.Td>
                    <Table.Td className="mono">{dur(p.age)}</Table.Td>
                    <Table.Td c="dimmed" style={{ fontSize: 11 }}>{p.images.join(", ")}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Panel>
      </Grid.Col>
      <Grid.Col span={{ base: 12, xl: 4 }}>
        <Stack>
          <Panel title="Node (k3s O-Cloud)">
            {cl.data && Object.entries(cl.data.node).map(([k, v]) => (
              <Group key={k} justify="space-between"><Text size="xs" c="dimmed">{k}</Text><Text size="xs" className="mono">{String(v)}</Text></Group>
            ))}
          </Panel>
          <Panel title="Prometheus scrape targets">
            <ScrollArea h={220}>
              {(targets.data ?? []).map((t) => (
                <Group key={`${t.job}${t.instance}`} justify="space-between" wrap="nowrap">
                  <Text size="xs" truncate>{t.job} <span className="dim">{t.instance}</span></Text>
                  <Badge size="xs" color={t.health === "up" ? "teal" : "red"} variant="light">{t.health}</Badge>
                </Group>
              ))}
            </ScrollArea>
          </Panel>
          <Panel title="Events">
            <ScrollArea h={320}>
              {(cl.data?.events ?? []).slice(0, 150).map((e, i) => (
                <Text key={i} size="xs" mb={4}>
                  <Badge size="xs" variant="light" color={e.type === "Warning" ? "yellow" : "gray"} mr={4}>{e.reason}</Badge>
                  {e.object} <span className="dim">· {e.message} · {ago(e.time)}</span>
                </Text>
              ))}
            </ScrollArea>
          </Panel>
        </Stack>
      </Grid.Col>
    </Grid>
  );
}
