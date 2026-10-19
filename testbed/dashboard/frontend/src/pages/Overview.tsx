import { Badge, Grid, Group, Progress, ScrollArea, SimpleGrid, Stack, Text, UnstyledButton } from "@mantine/core";
import { Kpi, Panel, StatusDot } from "../components/ui";
import { PromChart } from "../components/chart";
import { ago, bps, num, pct } from "../fmt";
import type { State } from "../types";

const LAYER_NAMES: Record<string, string> = {
  ue: "User devices", ran: "Radio access", ric: "O-RAN RIC", core: "5G core", dn: "Data network", cloud: "Cloud & observability",
};

const sliceLegend = (m: Record<string, string>) => ({ "core-upf": "eMBB", "upf-urllc": "URLLC", "upf-mmtc": "mMTC" }[m.dst] ?? m.dst);

export function Overview({ state, onSelect }: { state: State; onSelect: (id: string) => void }) {
  const k = state.kpis;
  const palette = Object.fromEntries(state.slices.map((s) => [s.label, s.color]));

  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }}>
        <Kpi label="gNBs connected" value={num(k.gnbs)} sub="NG Setup with the AMF" />
        <Kpi label="Registered UEs" value={num(k.registeredTotal)} sub={`${num(k.ranUes)} UE contexts in RAN`} />
        <Kpi label="PDU sessions" value={num(k.sessionsTotal)} sub="held by the SMF" />
        <Kpi label="N3 user plane" value={bps(k.n3Bps)} sub={`N6 Internet: ${bps(k.n6Bps)}`} />
        <Kpi label="Firing alerts" value={k.alerts} color={k.alerts ? "var(--warn)" : undefined} sub="from Alertmanager" />
        <Kpi label="Error log lines" value={num(k.logErrors5m)} color={k.logErrors5m ? "var(--warn)" : undefined}
             sub={`last 5 min, of ${num(k.logLines5m)} lines`} />
      </SimpleGrid>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <Panel title="Components">
            <Stack gap="sm">
              {Object.entries(LAYER_NAMES).map(([layer, title]) => {
                const list = state.components.filter((c) => c.layer === layer);
                if (!list.length) return null;
                return (
                  <div key={layer}>
                    <Text size="xs" c="dimmed" mb={4}>{title}</Text>
                    <Group gap={6}>
                      {list.map((c) => (
                        <UnstyledButton key={c.id} onClick={() => onSelect(c.id)}
                          style={{ padding: "5px 10px", borderRadius: 8, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
                          <Group gap={6} wrap="nowrap">
                            <StatusDot status={c.status} size={8} />
                            <Text size="xs" fw={500}>{c.label}</Text>
                          </Group>
                        </UnstyledButton>
                      ))}
                    </Group>
                  </div>
                );
              })}
            </Stack>
          </Panel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Panel title="VM resources">
            <Stack gap="sm">
              {([["CPU", state.node.cpuUsed], ["Memory", state.node.memUsed], ["Disk /", state.node.diskUsed]] as const).map(([label, v]) => (
                <div key={label}>
                  <Group justify="space-between"><Text size="xs">{label}</Text><Text size="xs" className="mono">{pct(v)}</Text></Group>
                  <Progress value={(v ?? 0) * 100} color={(v ?? 0) > 0.85 ? "red" : (v ?? 0) > 0.65 ? "yellow" : "cyan"} size="sm" />
                </div>
              ))}
              <Text size="xs" c="dimmed">{state.node.os} · kernel {state.node.kernel} · {state.node.kubelet} · {state.node.cpu} vCPU</Text>
              <Text className="section-title" mt="xs">Data sources</Text>
              <Group gap={6}>
                {Object.entries(state.sources).map(([name, s]) => (
                  <Badge key={name} variant="dot" color={s.ok ? "teal" : "red"} size="sm">{name}</Badge>
                ))}
              </Group>
            </Stack>
          </Panel>
        </Grid.Col>
      </Grid>

      <SimpleGrid cols={{ base: 1, md: 3 }}>
        {state.slices.map((s) => (
          <Panel key={s.id} title={`${s.label} slice`} right={<Badge variant="light" style={{ color: s.color }}>SST {s.sst} · SD {s.sd}</Badge>}>
            <SimpleGrid cols={3}>
              <div><Text size="xs" c="dimmed">UEs</Text><Text className="kpi-value" style={{ fontSize: 20 }}>{num(s.registered)}</Text></div>
              <div><Text size="xs" c="dimmed">Sessions</Text><Text className="kpi-value" style={{ fontSize: 20 }}>{num(s.sessions)}</Text></div>
              <div><Text size="xs" c="dimmed">N3</Text><Text className="mono" size="sm" mt={4}>{bps(s.n3_bps)}</Text></div>
            </SimpleGrid>
            <Text size="xs" c="dimmed" mt="xs">DNN {s.dnn} · pool {s.pool} · UPF {s.upf}</Text>
          </Panel>
        ))}
      </SimpleGrid>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 7 }}>
          <Panel>
            <PromChart title="N3 throughput per slice (gNB ↔ UPF, measured)" unit="bps" palette={palette} name={sliceLegend}
              query={'sum by (dst) (sixg_link_bits_per_second{iface="N3"})'} />
          </Panel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 5 }}>
          <Panel title="Kubernetes events">
            <ScrollArea h={250}>
              <Stack gap={6}>
                {state.events.slice(0, 40).map((e, i) => (
                  <Group key={i} gap={8} wrap="nowrap" align="flex-start">
                    <Badge size="xs" variant="light" color={e.type === "Warning" ? "yellow" : "gray"} w={64}>{e.reason}</Badge>
                    <div style={{ minWidth: 0 }}>
                      <Text size="xs" truncate>{e.object} <span className="dim">· {e.ns}</span></Text>
                      <Text size="xs" c="dimmed" lineClamp={2}>{e.message}</Text>
                    </div>
                    <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap", marginLeft: "auto" }}>{ago(e.time)}</Text>
                  </Group>
                ))}
              </Stack>
            </ScrollArea>
          </Panel>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
