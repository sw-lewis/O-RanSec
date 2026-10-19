import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Badge, Button, Code, Drawer, Group, Loader, Paper, SimpleGrid, Stack, Text, Timeline } from "@mantine/core";
import { IconChartDots3, IconCheck, IconClockHour4, IconFileText, IconPlugConnectedX, IconWaveSine } from "@tabler/icons-react";
import { get, post } from "../api";
import { bps, dur } from "../fmt";

type Step = { key: string; label: string; done: boolean; detail: string };
type Access = {
  network: string; networkLabel: string; port: number; addresses: { iface: string; ip: string; network: string | null }[];
  relayOnline: boolean; relayActive: boolean; relayPackets: number; dest: string | null; lastSeenSeconds: number | null;
  deviceTunnelIp?: string;
  wireguard?: string; wgRx?: number; wgTx?: number;
};
type Detail = {
  id: string; name: string; typeLabel: string; mode: string; imsi: string; slice: string; session: string | null;
  created: number; ip: string | null; registered: boolean; delivered: number; lost: number; linkBps: number;
  steps: Step[]; status: Record<string, unknown>; access: Access | null; deviceOnline: boolean | null; gatewayReady: boolean;
};
type TestResult = { kind?: "device" | "session"; target: string; sent: number; size: number; lossPct: number | null; rttMin: number | null; rttAvg: number | null; rttMax: number | null; output: string };

export function DeviceDetail({ id, onClose, onDisconnect }: { id: string | null; onClose: () => void; onDisconnect: (id: string) => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState<"device" | "session" | null>(null);
  const [log, setLog] = useState<string | null>(null);

  useEffect(() => {
    setD(null); setTest(null); setLog(null);
    if (!id) return;
    let alive = true;
    const load = () => get<Detail>(`/api/devices/${id}`).then((x) => alive && setD(x)).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [id]);

  const runTest = async (kind: "device" | "session") => {
    setTesting(kind); setTest(null);
    const url = kind === "device" ? `/api/devices/${id}/device-test` : `/api/devices/${id}/test?count=10&size=500`;
    try { setTest({ ...(await post<TestResult>(url)), kind }); }
    catch (e) { setTest({ kind, target: "", sent: 0, size: 0, lossPct: null, rttMin: null, rttAvg: null, rttMax: null, output: String(e) }); }
    finally { setTesting(null); }
  };

  const doneCount = d?.steps.filter((s) => s.done).length ?? 0;
  const ready = d?.steps.every((s) => s.done);

  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={600} title={
      <Group gap="sm"><Text fw={700}>{d?.name ?? "Device"}</Text>
        {d && (d.deviceOnline === null
          ? <Badge color={ready ? "teal" : "yellow"} variant="light">{ready ? "online (simulated)" : `connecting ${doneCount}/5`}</Badge>
          : d.deviceOnline ? <Badge color="teal" variant="light">device connected</Badge>
          : <Badge color="red" variant="light">{d.gatewayReady ? "device disconnected · gateway ready" : `gateway starting ${doneCount}/4`}</Badge>)}</Group>}>
      {!d ? <Loader size="sm" /> : (
        <Stack gap="md">
          <SimpleGrid cols={3} spacing="xs">
            <Fact k="Type" v={d.typeLabel} />
            <Fact k="Slice" v={d.slice} />
            <Fact k="Mode" v={d.mode} />
            <Fact k="IMSI" v={d.imsi} mono />
            <Fact k="UE IP" v={d.ip ?? "–"} mono />
            <Fact k="Connected for" v={dur(Date.now() / 1000 - d.created)} />
          </SimpleGrid>

          <Paper p="sm" bg="var(--panel-2)">
            <Text className="section-title" mb="xs">Connection progress</Text>
            <Timeline active={doneCount - 1} bulletSize={20} lineWidth={2}>
              {d.steps.map((s) => (
                <Timeline.Item key={s.key} title={s.label}
                  bullet={s.done ? <IconCheck size={12} /> : <IconClockHour4 size={12} />}
                  color={s.done ? "teal" : "gray"}>
                  <Text size="xs" c="dimmed">{s.detail}</Text>
                </Timeline.Item>
              ))}
            </Timeline>
          </Paper>

          {d.access && <HowToConnect a={d.access} name={d.name} />}

          <SimpleGrid cols={3} spacing="xs">
            <Paper p="sm" bg="var(--panel-2)"><Text size="xs" c="dimmed">Traffic now (radio link)</Text><Text className="mono" fw={600}>{bps(d.linkBps)}</Text></Paper>
            <Paper p="sm" bg="var(--panel-2)"><Text size="xs" c="dimmed">Packets delivered</Text><Text className="mono" fw={600} c="teal">{d.delivered}</Text></Paper>
            <Paper p="sm" bg="var(--panel-2)"><Text size="xs" c="dimmed">Packets lost</Text><Text className="mono" fw={600} c={d.lost ? "red" : undefined}>{d.lost}</Text></Paper>
          </SimpleGrid>

          {d.access?.wireguard && (
            <Paper p="sm" bg="var(--panel-2)">
              <Group justify="space-between">
                <div><Text size="sm" fw={600}>Test device</Text>
                  <Text size="xs" c="dimmed">Pings the device itself ({d.access.deviceTunnelIp}) through its WireGuard tunnel. Fails if the device is off or the tunnel is down.</Text></div>
                <Button size="xs" leftSection={<IconWaveSine size={14} />} loading={testing === "device"} onClick={() => runTest("device")}>Test device</Button>
              </Group>
              {test?.kind === "device" && <TestRow t={test} />}
            </Paper>
          )}
          {d.access && !d.access.wireguard && (
            <Paper p="sm" bg="var(--panel-2)">
              <Text size="sm" fw={600}>Device activity</Text>
              <Text size="xs" c={d.deviceOnline ? "teal" : "dimmed"}>
                {d.access.lastSeenSeconds == null ? "No packet from the device yet." : `Last packet from the device ${Math.round(d.access.lastSeenSeconds)} s ago (${d.access.relayPackets} in total).`}
              </Text>
            </Paper>
          )}
          <Paper p="sm" bg="var(--panel-2)">
            <Group justify="space-between">
              <div><Text size="sm" fw={600}>Test 5G session</Text>
                <Text size="xs" c="dimmed">10 packets from this device's gateway through its own 5G session to the Internet (network side only).</Text></div>
              <Button size="xs" variant="light" leftSection={<IconWaveSine size={14} />} loading={testing === "session"} disabled={!d.ip} onClick={() => runTest("session")}>Test 5G session</Button>
            </Group>
            {test?.kind === "session" && <TestRow t={test} />}
          </Paper>

          <Group gap="xs">
            <Button size="xs" leftSection={<IconChartDots3 size={14} />}
              onClick={() => { location.hash = `#/device/${d.id}`; onClose(); }}>Open live view</Button>
            <Button size="xs" variant="light" leftSection={<IconChartDots3 size={14} />}
              onClick={() => { location.hash = "#/architecture"; onClose(); }}>See it on the architecture</Button>
            <Button size="xs" variant="light" leftSection={<IconFileText size={14} />}
              onClick={async () => setLog((await get<{ log: string }>(`/api/devices/${d.id}/logs`)).log)}>Gateway log</Button>
            <Button size="xs" variant="light" color="red" leftSection={<IconPlugConnectedX size={14} />}
              onClick={() => onDisconnect(d.id)}>Disconnect</Button>
          </Group>
          {d.session && <Text size="xs" c="dimmed">Recorded in test {d.session}.</Text>}
          {log !== null && <Code block style={{ fontSize: 11, maxHeight: 260, overflow: "auto" }}>{log || "(empty)"}</Code>}
        </Stack>
      )}
    </Drawer>
  );
}

function Fact({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <Text size="10.5px" c="dimmed" tt="uppercase" style={{ letterSpacing: ".06em" }}>{k}</Text>
      <Text size="sm" className={mono ? "mono" : undefined} truncate>{v}</Text>
    </div>
  );
}

function HowToConnect({ a, name }: { a: Access; name: string }) {
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    if (a.wireguard) QRCode.toDataURL(a.wireguard, { margin: 1, width: 220 }).then(setQr).catch(() => setQr(null));
  }, [a.wireguard]);
  const addrs = a.addresses.length ? a.addresses : [{ iface: "", ip: "<this PC>", network: null }];
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([a.wireguard ?? ""], { type: "text/plain" }));
    el.download = `${name.replace(/[^\w-]+/g, "_")}.conf`;
    el.click();
  };
  return (
    <Paper p="sm" bg="var(--panel-2)" style={{ border: "1px solid var(--mantine-color-cyan-8)" }}>
      <Group justify="space-between" mb={6}>
        <Text size="sm" fw={600}>How to connect this device</Text>
        <Badge variant="dot" color={a.relayOnline ? "teal" : "red"}>PC relay {a.relayOnline ? "online" : "offline"}</Badge>
      </Group>
      <Text size="xs" c="dimmed" mb="xs">Network: {a.networkLabel}</Text>
      {a.wireguard ? (
        <Group align="flex-start" wrap="nowrap" gap="md">
          {qr && <img src={qr} width={150} height={150} alt="WireGuard configuration" style={{ borderRadius: 8, background: "#fff" }} />}
          <div>
            <Text size="sm">1. Join the device to the same {a.network === "hotspot" ? "phone hotspot" : "Wi-Fi/LAN"} as this PC.</Text>
            <Text size="sm">2. Install the WireGuard app (Android, iOS, Windows, macOS, Linux).</Text>
            <Text size="sm">3. Add a tunnel by scanning this QR code, or import the file.</Text>
            <Text size="sm">4. Switch the tunnel on. Its traffic now uses its own 5G session.</Text>
            <Group gap="xs" mt="xs">
              <Button size="compact-xs" variant="light" onClick={download}>Download .conf</Button>
              {a.wgRx !== undefined && <Badge variant="light" color="teal">received {a.wgRx} B · sent {a.wgTx} B</Badge>}
            </Group>
          </div>
        </Group>
      ) : (
        <Stack gap={4}>
          <Text size="sm">1. Join the device to the same {a.network === "hotspot" ? "phone hotspot" : "Wi-Fi/LAN"} as this PC.</Text>
          <Text size="sm">2. In the device's settings (for a drone: telemetry / ground-station output), send UDP to:</Text>
          <Group gap={6}>{addrs.map((x) => <Code key={x.ip} style={{ fontSize: 13 }}>{x.ip}:{a.port}</Code>)}</Group>
          <Text size="sm">3. The data is carried through the device's 5G session to <Code>{a.dest}</Code>.</Text>
          <Text size="xs" c={a.relayPackets ? "teal" : "dimmed"} mt={4}>
            {a.relayPackets ? `${a.relayPackets} packets received from the device so far` : "No packets from the device yet"}
          </Text>
        </Stack>
      )}
    </Paper>
  );
}

function TestRow({ t }: { t: TestResult }) {
  const failed = t.lossPct == null || t.lossPct >= 100;
  return (
    <SimpleGrid cols={4} mt="sm" spacing="xs">
      <Fact k="Result" v={failed ? "no reply" : t.lossPct ? `${t.lossPct}% loss` : "all replies"} />
      <Fact k="RTT min" v={t.rttMin == null ? "–" : `${t.rttMin} ms`} mono />
      <Fact k="RTT avg" v={t.rttAvg == null ? "–" : `${t.rttAvg} ms`} mono />
      <Fact k="RTT max" v={t.rttMax == null ? "–" : `${t.rttMax} ms`} mono />
    </SimpleGrid>
  );
}
