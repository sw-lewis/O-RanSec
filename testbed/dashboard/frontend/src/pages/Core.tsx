import { useCallback } from "react";
import { Badge, Grid, Group, ScrollArea, Stack, Table, Text } from "@mantine/core";
import { usePoll } from "../api";
import { Panel, StatusDot } from "../components/ui";
import { PromChart } from "../components/chart";
import type { State } from "../types";

type Subscriber = { imsi: string; msisdn: string[]; slices: { sst: number; sd?: string; dnn: string[] }[]; status?: number };

const SLICE_NAME: Record<string, string> = { "1-000001": "eMBB", "2-000002": "URLLC", "3-000003": "mMTC" };

export function Core({ state, onSelect }: { state: State; onSelect: (id: string) => void }) {
  const subs = usePoll<Subscriber[]>("/api/core/subscribers", 15000);
  const palette = Object.fromEntries(state.slices.map((s) => [s.label, s.color]));
  const bySlice = useCallback((m: Record<string, string>) => SLICE_NAME[m.snssai] ?? m.snssai, []);
  const nfs = state.components.filter((c) => c.layer === "core");

  return (
    <Grid>
      <Grid.Col span={{ base: 12, xl: 7 }}>
        <Stack>
          <Panel>
            <PromChart title="Registered UEs per slice (AMF)" palette={palette} name={bySlice}
              query="max by (snssai) (fivegs_amffunction_rm_registeredsubnbr)" height={200} />
          </Panel>
          <Panel>
            <PromChart title="PDU sessions per slice (SMF)" palette={palette} name={bySlice}
              query="max by (snssai) (fivegs_smffunction_sm_sessionnbr)" height={200} />
          </Panel>
          <Panel>
            {/* rate() drops __name__, so each counter is taken alone and labelled with label_replace; max, not sum, as the AMF is one pod (an old series lingers after a reboot) */}
            <PromChart title="Registration attempts (AMF, per minute)" name={(m) => m.kind ?? "?"}
              query={'label_replace(max(rate(fivegs_amffunction_rm_reginitreq[2m])) * 60, "kind", "requested", "", "")'
                + ' or label_replace(max(rate(fivegs_amffunction_rm_reginitsucc[2m])) * 60, "kind", "succeeded", "", "")'
                + ' or label_replace(max(rate(fivegs_amffunction_rm_reginitfail[2m])) * 60, "kind", "failed", "", "")'} height={180} />
          </Panel>
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, xl: 5 }}>
        <Stack>
          <Panel title="Network functions (Open5GS 2.7.5)">
            <Group gap={6}>
              {nfs.map((c) => (
                <Badge key={c.id} variant="default" size="lg" style={{ cursor: "pointer", textTransform: "none" }}
                       leftSection={<StatusDot status={c.status} size={7} />} onClick={() => onSelect(c.id)}>{c.label}</Badge>
              ))}
            </Group>
            <Text size="xs" c="dimmed" mt="sm">
              Subscriber provisioning UI: Open5GS WebUI on http://127.0.0.1:8662 (opened by the launcher tunnel).
            </Text>
          </Panel>
          <Panel title={`Subscribers in MongoDB (${subs.data?.length ?? "…"})`}>
            {subs.error && <Text size="xs" c="red">{subs.error}</Text>}
            <ScrollArea h={460}>
              <Table className="dense" striped withRowBorders={false}>
                <Table.Thead><Table.Tr><Table.Th>IMSI</Table.Th><Table.Th>Slice / DNN</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {(subs.data ?? []).map((s) => (
                    <Table.Tr key={s.imsi}>
                      <Table.Td className="mono">{s.imsi}</Table.Td>
                      <Table.Td>{s.slices.map((sl, i) => (
                        <Badge key={i} size="xs" variant="light" mr={4} style={{ textTransform: "none" }}>
                          SST {sl.sst}{sl.sd ? `/${sl.sd}` : ""} · {sl.dnn.join(", ")}
                        </Badge>))}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Panel>
        </Stack>
      </Grid.Col>
    </Grid>
  );
}
