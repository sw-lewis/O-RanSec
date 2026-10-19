import { useState } from "react";
import {
  Badge, Button, Code, Grid, Group, List, Modal, NumberInput, Paper, SegmentedControl, SimpleGrid, Stack,
  Stepper, Table, Text, TextInput, ThemeIcon, UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCpu, IconDeviceLaptop, IconDeviceMobile, IconDrone, IconPlugConnected, IconRouter, IconTrash, IconWifi,
} from "@tabler/icons-react";
import { get, post, usePoll } from "../api";
import { Panel } from "../components/ui";
import { modals } from "../components/modals";
import { ago } from "../fmt";
import { DeviceDetail } from "./DeviceDetail";

type HostInfo = { addresses: { iface: string; ip: string; network: string | null }[]; online: boolean };
type Options = {
  types: Record<string, { label: string; slice: string }>;
  modes: Record<string, { label: string; real: boolean }>;
  networks: Record<string, string>;
  host: HostInfo;
  slices: Record<string, { sst: number; sd: string; label: string }>;
  wifiAdapters: string[];
};
type Device = {
  id: string; name: string; type: string; typeLabel: string; mode: string; imsi: string; slice: string;
  session: string | null; created: number; podReady: boolean; restarts: number;
  registered?: boolean; ip?: string | null; rmState?: string | null; deviceOnline: boolean | null;
};

const ICON: Record<string, typeof IconDrone> = { drone: IconDrone, phone: IconDeviceLaptop, iot: IconCpu, generic: IconRouter };

export function Devices() {
  const opts = usePoll<Options>("/api/devices/options", 10000);
  const list = usePoll<Device[]>("/api/devices", 4000);
  const [step, setStep] = useState(0);
  const [type, setType] = useState("generic");
  const [method, setMethod] = useState("simulated");  // simulated | hotspot | router | adapter
  const [dest, setDest] = useState("");
  const real = method !== "simulated";
  const udpType = type === "drone";
  const mode = !real ? "simulated" : udpType ? "udp-relay" : "vpn";
  const [slice, setSlice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [interval, setIntervalS] = useState<number | string>(5);
  const [size, setSize] = useState<number | string>(200);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<{ id: string; text: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const o = opts.data;
  const hostAddrs = o?.host.addresses ?? [];
  const chosenSlice = slice ?? o?.types[type]?.slice ?? "embb";

  const connect = async () => {
    setBusy(true);
    try {
      const d = await post<{ id: string; imsi: number; slice: string }>("/api/devices", {
        name, type, mode, slice: chosenSlice, interval: Number(interval), size: Number(size),
        network: real ? method : "router", dest: mode === "udp-relay" && dest.trim() ? dest.trim() : null,
      });
      notifications.show({ color: "teal", title: "Device added", message: `${name}: IMSI ${d.imsi} on ${d.slice}. Follow its progress on the right.` });
      setStep(0); setName(""); list.refresh(); setOpen(d.id);
    } catch (e) {
      notifications.show({ color: "red", title: "Could not connect", message: String(e) });
    } finally { setBusy(false); }
  };

  const disconnect = (d: Device) => modals.confirm({
    title: `Disconnect ${d.name}?`,
    body: "The device deregisters from the network, its gateway is removed and its subscriber is deleted from the core.",
    confirm: "disconnect", danger: true,
    onConfirm: async () => {
      try { await fetch(`/api/devices/${d.id}`, { method: "DELETE" }); setOpen(null); list.refresh(); }
      catch (e) { notifications.show({ color: "red", message: String(e) }); }
    },
  });

  return (
    <Grid>
      <Grid.Col span={{ base: 12, xl: 5 }}>
        <Stack>
          <Panel title="Connect a device">
            <Stepper active={step} onStepClick={setStep} size="sm">
              <Stepper.Step label="Device">
                <SimpleGrid cols={2} mt="md">
                  {o && Object.entries(o.types).map(([k, t]) => {
                    const I = ICON[k] ?? IconRouter;
                    return (
                      <UnstyledButton key={k} onClick={() => { setType(k); setSlice(null); }}
                        style={{ padding: 12, borderRadius: 10, border: `1px solid ${type === k ? "var(--mantine-color-cyan-6)" : "var(--line)"}`,
                                 background: type === k ? "#22d3ee12" : "var(--panel-2)" }}>
                        <Group gap="sm" wrap="nowrap">
                          <ThemeIcon variant="light" size="lg"><I size={20} /></ThemeIcon>
                          <div><Text size="sm" fw={600}>{t.label}</Text>
                            <Text size="xs" c="dimmed">default slice: {o.slices[t.slice]?.label}</Text></div>
                        </Group>
                      </UnstyledButton>
                    );
                  })}
                </SimpleGrid>
                <Group justify="flex-end" mt="md"><Button onClick={() => setStep(1)}>Next</Button></Group>
              </Stepper.Step>

              <Stepper.Step label="How it connects">
                <Stack mt="md" gap="sm">
                  <SimpleGrid cols={3} spacing="xs">
                    {([
                      ["simulated", IconRouter, "Simulated in the testbed", "No hardware. The testbed generates the device's traffic."],
                      ["hotspot", IconDeviceMobile, "Phone hotspot", "This PC and the device join the same phone hotspot."],
                      ["router", IconWifi, "Personal or lab router", "This PC and the device are on the same Wi-Fi/LAN."],
                    ] as const).map(([k, I, title, sub]) => {
                      const disabled = false;
                      return (
                        <UnstyledButton key={k} disabled={disabled} onClick={() => setMethod(k)}
                          style={{ padding: 10, borderRadius: 10, opacity: disabled ? 0.45 : 1,
                                   border: `1px solid ${method === k ? "var(--mantine-color-cyan-6)" : "var(--line)"}`,
                                   background: method === k ? "#22d3ee12" : "var(--panel-2)" }}>
                          <Group gap="sm" wrap="nowrap" align="flex-start">
                            <ThemeIcon variant="light"><I size={18} /></ThemeIcon>
                            <div><Text size="sm" fw={600}>{title}</Text><Text size="xs" c="dimmed">{sub}</Text></div>
                          </Group>
                        </UnstyledButton>
                      );
                    })}
                  </SimpleGrid>
                  {real && (
                    <Paper p="sm" bg="var(--panel-2)">
                      {o?.host.online && hostAddrs.length ? (
                        <Text size="sm">This PC is reachable at{" "}
                          {hostAddrs.map((a) => <Badge key={a.ip} variant="light" mr={4} style={{ textTransform: "none" }}>{a.ip}{a.network ? ` (${a.network})` : ""}</Badge>)}
                        </Text>
                      ) : (
                        <Text size="sm" c="yellow">The PC relay is not reporting yet. Start the testbed from the "6G Testbed" launcher.</Text>
                      )}
                      <Text size="xs" c="dimmed" mt={6}>
                        {udpType
                          ? "The drone sends its telemetry (MAVLink) and camera (SRT) to this PC. Both travel through its own 5G session to the testbed's edge hub and appear live in the dashboard."
                          : "The device uses the free WireGuard app (QR code shown after connecting). All its traffic goes through its own 5G session; camera and sensor apps send to the testbed's edge hub and appear live."}
                      </Text>
                      {udpType && (
                        <TextInput mt="xs" label="Also send telemetry to your own ground station (optional)" placeholder="leave empty to use the testbed's live view"
                          description="host:port, e.g. a laptop running QGroundControl. Empty = built-in edge hub."
                          value={dest} onChange={(e) => setDest(e.currentTarget.value)} />
                      )}
                    </Paper>
                  )}
                  {mode === "simulated" && (
                    <Group grow>
                      <NumberInput label="Send every (seconds)" min={1} max={60} value={interval} onChange={setIntervalS} />
                      <NumberInput label="Packet size (bytes)" min={56} max={1400} value={size} onChange={setSize} />
                    </Group>
                  )}
                </Stack>
                <Group justify="space-between" mt="md">
                  <Button variant="default" onClick={() => setStep(0)}>Back</Button>
                  <Button onClick={() => setStep(2)} disabled={real && udpType && dest.trim() !== "" && !/^[\w.-]+:\d{1,5}$/.test(dest.trim())}>Next</Button>
                </Group>
              </Stepper.Step>

              <Stepper.Step label="Slice & name">
                <Stack mt="md" gap="sm">
                  <TextInput label="Device name" placeholder="e.g. Lab drone 1" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
                  <div>
                    <Text size="sm" fw={500} mb={4}>Network slice</Text>
                    <SegmentedControl value={chosenSlice} onChange={setSlice} fullWidth
                      data={o ? Object.entries(o.slices).map(([k, s]) => ({ value: k, label: `${s.label} (SST ${s.sst})` })) : []} />
                  </div>
                  <Paper p="sm" bg="var(--panel-2)">
                    <Text size="xs" c="dimmed">What happens when you press Connect</Text>
                    <List size="sm" mt={4} spacing={2}>
                      <List.Item>A new subscriber (IMSI + fresh secret keys) is added to the Open5GS core.</List.Item>
                      <List.Item>A 5G gateway (UERANSIM UE) starts and registers on the {o?.slices[chosenSlice]?.label} slice.</List.Item>
                      {real && <List.Item>Its gateway is opened on this PC's {method === "hotspot" ? "hotspot" : "router"} address; the next screen shows exactly how to connect the device.</List.Item>}
                      <List.Item>It appears live on the architecture view and in the logs. A running test records it.</List.Item>
                    </List>
                  </Paper>
                </Stack>
                <Group justify="space-between" mt="md">
                  <Button variant="default" onClick={() => setStep(1)}>Back</Button>
                  <Button leftSection={<IconPlugConnected size={16} />} loading={busy} disabled={!name.trim()} onClick={connect}>Connect</Button>
                </Group>
              </Stepper.Step>
            </Stepper>
          </Panel>

        </Stack>
      </Grid.Col>

      <Grid.Col span={{ base: 12, xl: 7 }}>
        <Panel title={`Connected devices (${list.data?.length ?? 0})`}>
          {list.error && <Text size="xs" c="red">{list.error}</Text>}
          <Table className="dense" highlightOnHover>
            <Table.Thead><Table.Tr>
              <Table.Th>Device</Table.Th><Table.Th>Slice</Table.Th><Table.Th>IMSI</Table.Th>
              <Table.Th>5G gateway</Table.Th><Table.Th>Device</Table.Th><Table.Th>UE IP</Table.Th><Table.Th>Mode</Table.Th><Table.Th />
            </Table.Tr></Table.Thead>
            <Table.Tbody>
              {(list.data ?? []).map((d) => (
                <Table.Tr key={d.id} style={{ cursor: "pointer" }} onClick={() => setOpen(d.id)}>
                  <Table.Td><Text size="sm" fw={600}>{d.name}</Text><Text size="xs" c="dimmed">{d.typeLabel} · {ago(new Date(d.created * 1000).toISOString())}</Text></Table.Td>
                  <Table.Td><Badge variant="light">{d.slice}</Badge></Table.Td>
                  <Table.Td className="mono">{d.imsi}</Table.Td>
                  <Table.Td>{!d.podReady ? <Badge color="yellow" variant="light">starting</Badge>
                    : d.registered ? <Badge color="teal" variant="light">registered</Badge>
                    : <Badge color="red" variant="light">{d.rmState ?? "not registered"}</Badge>}</Table.Td>
                  <Table.Td>{d.deviceOnline === null ? <Text size="xs" c="dimmed">simulated</Text>
                    : d.deviceOnline ? <Badge color="teal" variant="light">connected</Badge>
                    : <Badge color="red" variant="light">disconnected</Badge>}</Table.Td>
                  <Table.Td className="mono">{d.ip ?? "–"}</Table.Td>
                  <Table.Td><Text size="xs">{d.mode}</Text>{d.session && <Text size="xs" c="dimmed">test {d.session}</Text>}</Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                      <Button size="compact-xs" variant="light" onClick={() => { location.hash = `#/device/${d.id}`; }}>Live view</Button>
                      <Button size="compact-xs" variant="subtle" onClick={async () =>
                        setLogs({ id: d.name, text: (await get<{ log: string }>(`/api/devices/${d.id}/logs`)).log })}>Logs</Button>
                      <Button size="compact-xs" variant="subtle" color="red" onClick={() => disconnect(d)}><IconTrash size={14} /></Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {list.data?.length === 0 && <Text size="sm" c="dimmed" ta="center" py="lg">No devices yet. Connect one on the left.</Text>}
        </Panel>
      </Grid.Col>

      <DeviceDetail id={open} onClose={() => setOpen(null)}
        onDisconnect={(id) => { const d = list.data?.find((x) => x.id === id); if (d) disconnect(d); }} />
      <Modal opened={!!logs} onClose={() => setLogs(null)} title={`Gateway log: ${logs?.id}`} size="xl">
        <Code block style={{ fontSize: 11, maxHeight: 500, overflow: "auto" }}>{logs?.text || "(empty)"}</Code>
      </Modal>
    </Grid>
  );
}
