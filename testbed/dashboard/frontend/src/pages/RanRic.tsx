import { Accordion, Badge, Code, Grid, Group, ScrollArea, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { usePoll } from "../api";
import { Panel, StatusBadge } from "../components/ui";
import { levelColor } from "../components/ComponentDrawer";
import { bps, clock, dur, num } from "../fmt";
import type { LogLine, State } from "../types";

type Srs = { connected: boolean; error: string | null; age: number | null; reports: Record<string, unknown> };
type SrsUe = Record<string, number>;
type SrsCell = { cell_metrics: Record<string, number>; ue_list: SrsUe[] };

function SrsRadio({ reports }: { reports: Record<string, unknown> }) {
  const cells = (reports.cells as SrsCell[] | undefined) ?? [];
  const ues = cells.flatMap((c) => c.ue_list ?? []);
  const cm = cells[0]?.cell_metrics ?? {};
  const bler = (ok: number, nok: number) => (ok + nok ? `${((100 * nok) / (ok + nok)).toFixed(1)}%` : "–");
  return (
    <Stack gap="sm">
      <Table className="dense" striped withRowBorders={false}>
        <Table.Thead><Table.Tr>
          <Table.Th>RNTI</Table.Th><Table.Th>CQI</Table.Th><Table.Th>DL MCS</Table.Th><Table.Th>UL MCS</Table.Th>
          <Table.Th>DL rate</Table.Th><Table.Th>UL rate</Table.Th><Table.Th>DL BLER</Table.Th><Table.Th>UL BLER</Table.Th><Table.Th>PUSCH SNR</Table.Th>
        </Table.Tr></Table.Thead>
        <Table.Tbody>
          {ues.length === 0 && <Table.Tr><Table.Td colSpan={9}><Text size="xs" c="dimmed">No UE attached to this cell.</Text></Table.Td></Table.Tr>}
          {ues.map((u) => (
            <Table.Tr key={u.rnti} className="mono">
              <Table.Td>{u.rnti}</Table.Td><Table.Td>{u.cqi}</Table.Td><Table.Td>{u.dl_mcs}</Table.Td><Table.Td>{u.ul_mcs}</Table.Td>
              <Table.Td>{bps(u.dl_brate)}</Table.Td><Table.Td>{bps(u.ul_brate)}</Table.Td>
              <Table.Td>{bler(u.dl_nof_ok, u.dl_nof_nok)}</Table.Td><Table.Td>{bler(u.ul_nof_ok, u.ul_nof_nok)}</Table.Td>
              <Table.Td>{num(u.pusch_snr_db, 1)} dB</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <SimpleGrid cols={4} spacing="xs">
        {([["PCI", cm.pci], ["Avg slot latency (µs)", cm.average_latency], ["Max slot latency (µs)", cm.max_latency],
           ["Late DL HARQs", cm.late_dl_harqs], ["Late UL HARQs", cm.late_ul_harqs], ["Msg3 OK / NOK", `${cm.msg3_nof_ok ?? "–"} / ${cm.msg3_nof_nok ?? "–"}`],
           ["Failed PDCCH allocs", cm.nof_failed_pdcch_allocs], ["Error indications", cm.error_indication_count]] as const).map(([k, v]) => (
          <div key={k}><Text size="10.5px" c="dimmed">{k}</Text><Text size="sm" className="mono">{v ?? "–"}</Text></div>
        ))}
      </SimpleGrid>
      <Accordion variant="contained">
        <Accordion.Item value="raw">
          <Accordion.Control><Text size="xs">Raw report ({Object.keys(reports).join(", ")})</Text></Accordion.Control>
          <Accordion.Panel><Code block style={{ fontSize: 11, maxHeight: 320, overflow: "auto" }}>{JSON.stringify(reports, null, 2)}</Code></Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}

function LogBox({ query, height = 260 }: { query: string; height?: number }) {
  const logs = usePoll<LogLine[]>(`/api/logs?query=${encodeURIComponent(query)}&minutes=30&limit=200`, 4000);
  return (
    <ScrollArea h={height} style={{ background: "#05080c", borderRadius: 8 }} p="xs">
      {logs.error && <Text size="xs" c="red">{logs.error}</Text>}
      {(logs.data ?? []).map((l, i) => (
        <div key={i} className="logline"><span className="dim">{clock(l.ts)} </span>
          <span style={{ color: levelColor(l.labels.level) }}>{l.line}</span></div>
      ))}
      {logs.data?.length === 0 && <Text size="xs" c="dimmed">No lines in the last 30 minutes.</Text>}
    </ScrollArea>
  );
}

export function RanRic({ state }: { state: State }) {
  const gnb = usePoll<Record<string, unknown>>("/api/ran/gnb/gnb1", 8000);
  const srs = usePoll<Srs>("/api/ran/srsgnb", 2000);
  const status = (id: string) => state.components.find((c) => c.id === id)?.status ?? "unknown";

  return (
    <Grid>
      <Grid.Col span={{ base: 12, xl: 6 }}>
        <Stack>
          <Panel title="UERANSIM gNB (nr-cli)" right={<StatusBadge status={status("gnb1")} />}>
            {gnb.error ? <Text size="xs" c="red">{gnb.error}</Text> :
              <Code block style={{ fontSize: 11, maxHeight: 330, overflow: "auto" }}>{JSON.stringify(gnb.data, null, 2)}</Code>}
          </Panel>
          <Panel title="srsRAN gNB live metrics (remote-control WebSocket)" right={
            <Group gap={6}>
              <Badge variant="dot" color={srs.data?.connected ? "teal" : "red"}>{srs.data?.connected ? "subscribed" : "not connected"}</Badge>
              <StatusBadge status={status("srsgnb")} />
            </Group>}>
            {srs.data?.error && <Text size="xs" c="dimmed">{srs.data.error}</Text>}
            <Text size="xs" c="dimmed" mb={6}>Per-UE MAC/PHY view of the ZMQ cell, pushed by the gNB every second. Last report {dur(srs.data?.age)} ago.</Text>
            <SrsRadio reports={srs.data?.reports ?? {}} />
          </Panel>
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, xl: 6 }}>
        <Stack>
          <Panel title="Near-RT RIC (FlexRIC) — E2 / E42 events" right={<StatusBadge status={status("near-rt-ric")} />}>
            <LogBox query={'{namespace="sixg-ric", container="ric"}'} />
          </Panel>
          <Panel title="KPM monitoring xApp — indications from the gNB" right={<StatusBadge status={status("xapp-kpm")} />}>
            <Text size="xs" c="dimmed" mb={4}>
              Subscribed: DRB.UEThpDl, DRB.UEThpUl, DRB.RlcSduTransmittedVolumeDL, DRB.RlcSduTransmittedVolumeUL (report style 1, every 1 s),
              printed in that order by FlexRIC's example monitor.
            </Text>
            <LogBox query={'{namespace="sixg-ric", container="xapp"} |~ "meas|subscribes|E42|E2 node"'} height={300} />
          </Panel>
        </Stack>
      </Grid.Col>
    </Grid>
  );
}
