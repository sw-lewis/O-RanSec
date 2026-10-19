import { useCallback } from "react";
import { Badge, Grid, Group, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { Panel, StatusBadge } from "../components/ui";
import { PromChart } from "../components/chart";
import { bps, num } from "../fmt";
import type { State } from "../types";

const UPF_SLICE: Record<string, string> = { "core-upf": "eMBB", "upf-urllc": "URLLC", "upf-mmtc": "mMTC" };

export function Slices({ state }: { state: State }) {
  const palette = Object.fromEntries(state.slices.map((s) => [s.label, s.color]));
  const byUpf = useCallback((m: Record<string, string>) => UPF_SLICE[m.dst] ?? UPF_SLICE[m.src] ?? `${m.src}→${m.dst}`, []);
  // slice-crossing traffic: any measured link between the UE pools / UPFs of different slices
  const cross = state.links.filter((l) => {
    const sa = UPF_SLICE[l.a], sb = UPF_SLICE[l.b];
    return sa && sb && sa !== sb;
  });

  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        {state.slices.map((s) => (
          <Panel key={s.id} title={`${s.label} · SST ${s.sst} · SD ${s.sd}`} right={<StatusBadge status={s.upfStatus ?? "unknown"} />}>
            <Table className="dense" withRowBorders={false}>
              <Table.Tbody>
                <Table.Tr><Table.Td c="dimmed">DNN</Table.Td><Table.Td className="mono">{s.dnn}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">UE IP pool</Table.Td><Table.Td className="mono">{s.pool}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">Dedicated UPF</Table.Td><Table.Td className="mono">{s.upf}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">Registered UEs</Table.Td><Table.Td className="mono">{num(s.registered)}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">PDU sessions</Table.Td><Table.Td className="mono">{num(s.sessions)}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">N3 now</Table.Td><Table.Td className="mono">{bps(s.n3_bps)}</Table.Td></Table.Tr>
                <Table.Tr><Table.Td c="dimmed">N6 now</Table.Td><Table.Td className="mono">{bps(s.n6_bps)}</Table.Td></Table.Tr>
              </Table.Tbody>
            </Table>
            <div style={{ height: 3, background: s.color, borderRadius: 2, marginTop: 8, opacity: 0.8 }} />
          </Panel>
        ))}
      </SimpleGrid>
      <Grid>
        <Grid.Col span={{ base: 12, xl: 6 }}>
          <Panel><PromChart title="N3 per slice (gNB ↔ UPF)" unit="bps" palette={palette} name={byUpf}
            query={'sum by (dst) (sixg_link_bits_per_second{iface="N3"})'} /></Panel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 6 }}>
          <Panel><PromChart title="N6 per slice (UPF ↔ data network)" unit="bps" palette={palette} name={byUpf}
            query={'sum by (src) (sixg_link_bits_per_second{iface="N6", src=~"core-upf|upf-urllc|upf-mmtc"})'} /></Panel>
        </Grid.Col>
      </Grid>
      <Panel title="Slice isolation check" right={
        <Badge color={cross.length ? "red" : "teal"} variant="light">{cross.length ? `${cross.length} cross-slice link(s)` : "no cross-slice traffic seen"}</Badge>}>
        <Text size="sm" c="dimmed">
          Measured continuously from kernel connection tracking: any link directly between the user planes of two
          different slices shows up here. It is the signal for the "slice isolation breach" scenario.
        </Text>
        {cross.map((l) => (
          <Group key={`${l.a}-${l.b}`} mt="xs"><Badge color="red">{l.iface}</Badge>
            <Text size="sm" className="mono">{l.a} ↔ {l.b} · {bps(l.bps)}</Text></Group>
        ))}
      </Panel>
    </Stack>
  );
}
