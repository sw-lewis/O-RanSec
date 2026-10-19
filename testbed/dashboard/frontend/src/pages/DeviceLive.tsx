import { useCallback, useMemo } from "react";
import { Badge, Button, Code, Grid, Group, Paper, ScrollArea, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { usePoll } from "../api";
import { Panel } from "../components/ui";
import { PathFlow, PathLegend, type Hop, type Leg } from "../components/PathFlow";
import { VideoPlayer } from "../components/VideoPlayer";
import { LiveMap } from "../components/LiveMap";
import { PromChart } from "../components/chart";
import { dur, num } from "../fmt";

type Telemetry = { sysid: number; source: string; ageSeconds: number; state: Record<string, number | string | boolean | null>;
                   messages: Record<string, number> };
type Live = {
  id: string; name: string; type: string; mode: string; slice: string; hubOnline: boolean;
  telemetry: Telemetry | null; track: { lat: number; lon: number; alt: number }[];
  mqtt: { latest: Record<string, { value: unknown; t: number }>; feed: { t: number; topic: string; value: unknown }[] } | null;
  video: { ready: boolean; tracks: string[]; bytesReceived: number; source: string | null; hls: string } | null;
  path: { upf: string | null; hops: { radio: number; n3: number; n6hub: number } };
};
type Detail = { deviceOnline: boolean | null; gatewayReady: boolean; ip: string | null; imsi: string;
                access: { addresses: { ip: string }[] } | null };

const SLICE_COLOR: Record<string, string> = { embb: "#4dabf7", urllc: "#f783ac", mmtc: "#69db7c" };

export function DeviceLive({ id }: { id: string }) {
  const live = usePoll<Live>(`/api/devices/${id}/live`, 1500);
  const det = usePoll<Detail>(`/api/devices/${id}`, 4000);
  const L = live.data, D = det.data;
  const real = D?.deviceOnline !== null && D?.deviceOnline !== undefined;
  const devUp = real ? !!D?.deviceOnline : !!D?.gatewayReady;
  const color = SLICE_COLOR[L?.slice ?? ""] ?? "#22d3ee";

  const hops: Hop[] = useMemo(() => [
    { id: "dev", label: L?.name ?? "Device", sub: real ? "real device" : "simulated device", up: devUp },
    ...(real ? [{ id: "pc", label: "PC relay", sub: D?.access?.addresses[0]?.ip ?? "hotspot / router", up: devUp }] : []),
    { id: "ue", label: "5G gateway (UE)", sub: D?.ip ? `IP ${D.ip}` : "registering", up: !!D?.gatewayReady },
    { id: "gnb", label: "gNB", sub: "radio access", up: !!D?.gatewayReady },
    { id: "upf", label: `UPF ${L?.slice?.toUpperCase() ?? ""}`, sub: "user plane", up: !!D?.gatewayReady },
    { id: "hub", label: "Edge hub", sub: "MEC · live data", up: !!L?.hubOnline },
    { id: "you", label: "This dashboard", sub: "you", up: true },
  ], [L, D, real, devUp]);

  const h = L?.path.hops;
  const legs: Leg[] = [
    ...(real ? [{ label: "Wi-Fi / LAN", bps: null, color: "#a78bfa", active: devUp }] : [{ label: "inside the pod", bps: null, color: "#a78bfa", active: devUp }]),
    ...(real ? [{ label: "PC → VM", bps: null, color: "#a78bfa", active: devUp }] : []),
    { label: "Uu radio", bps: h?.radio ?? 0, color: "#a78bfa", active: (h?.radio ?? 0) > 1 },
    { label: "N3 GTP-U", bps: h?.n3 ?? 0, color, active: (h?.n3 ?? 0) > 1 },
    { label: "N6 to edge", bps: h?.n6hub ?? 0, color: "#34d399", active: (h?.n6hub ?? 0) > 1 },
    { label: "live view", bps: null, color: "#e879f9", active: !!(L?.video?.ready || L?.telemetry || L?.mqtt?.feed.length) },
  ];

  const s = L?.telemetry?.state ?? {};
  const pos = typeof s.lat === "number" && typeof s.lon === "number" && s.lat !== 0 ? [s.lat, s.lon] as [number, number]
    : (() => { const m = L?.mqtt?.latest?.telemetry?.value as Record<string, number> | undefined;
               return m && typeof m.lat === "number" ? [m.lat, m.lon] as [number, number] : null; })();
  const track = useMemo(() => (L?.track ?? []).map((p) => [p.lat, p.lon] as [number, number]), [L?.track]);
  const mqttNumbers = useMemo(() => {
    const v = L?.mqtt?.latest?.telemetry?.value;
    return v && typeof v === "object" ? Object.entries(v as Record<string, unknown>).filter(([, x]) => typeof x === "number") : [];
  }, [L?.mqtt]);
  const name = useCallback((m: Record<string, string>) => m.__name__ ?? "rate", []);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="sm">
          <Button size="xs" variant="subtle" leftSection={<IconArrowLeft size={14} />} onClick={() => { location.hash = "#/devices"; }}>Devices</Button>
          <Text fw={700} size="lg">{L?.name ?? id}</Text>
          {L && <Badge variant="light" style={{ color }}>{L.slice?.toUpperCase()} slice</Badge>}
          {D && (real
            ? <Badge color={devUp ? "teal" : "red"} variant="light">{devUp ? "device connected" : "device disconnected"}</Badge>
            : <Badge color={devUp ? "teal" : "yellow"} variant="light">{devUp ? "simulated device online" : "starting"}</Badge>)}
          {D && <Text size="xs" c="dimmed" className="mono">IMSI {D.imsi}</Text>}
        </Group>
      </Group>

      <Paper p="md">
        <Text className="section-title" mb={4}>Live path through the network</Text>
        <PathFlow hops={hops} legs={legs} />
        <PathLegend />
      </Paper>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 7 }}>
          <Panel title="Live video" right={L?.video?.ready
            ? <Badge color="teal" variant="dot">{L.video.tracks?.join(" + ")} · {num((L.video.bytesReceived ?? 0) / 1e6, 1)} MB received</Badge>
            : <Badge color="gray" variant="dot">no stream</Badge>}>
            <VideoPlayer src={`/api/video/${id}/index.m3u8`} live={!!L?.video?.ready} />
          </Panel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 5 }}>
          <Panel title="Location">
            {pos ? <LiveMap lat={pos[0]} lon={pos[1]} track={track} /> : <Text size="sm" c="dimmed" py="xl" ta="center">This device does not report a position.</Text>}
          </Panel>
        </Grid.Col>
      </Grid>

      {L?.telemetry && (
        <Panel title={`Flight telemetry (MAVLink, system ${L.telemetry.sysid})`} right={
          <Text size="xs" c="dimmed">{Object.values(L.telemetry.messages).reduce((a, b) => a + b, 0)} messages · last {dur(L.telemetry.ageSeconds)} ago</Text>}>
          <SimpleGrid cols={{ base: 2, md: 4, xl: 8 }}>
            {([["Mode", s.mode], ["Armed", s.armed ? "yes" : "no"], ["Altitude", `${num(s.altRel as number, 1)} m`],
               ["Ground speed", `${num(s.groundSpeed as number, 1)} m/s`], ["Heading", `${num(s.heading as number)}°`],
               ["Battery", `${num(s.batteryPct as number)} %`], ["GPS", `${s.satellites ?? "–"} sats (fix ${s.gpsFix ?? "–"})`],
               ["Attitude", `${num(s.roll as number)}° / ${num(s.pitch as number)}°`]] as const).map(([k, v]) => (
              <div key={k}><Text size="10.5px" c="dimmed" tt="uppercase">{k}</Text><Text className="mono" fw={600}>{String(v ?? "–")}</Text></div>
            ))}
          </SimpleGrid>
        </Panel>
      )}

      {L?.mqtt && (L.mqtt.feed.length > 0 || Object.keys(L.mqtt.latest).length > 0) && (
        <Grid>
          <Grid.Col span={{ base: 12, xl: 5 }}>
            <Panel title="Sensor values (MQTT)">
              <Table className="dense" withRowBorders={false}>
                <Table.Tbody>
                  {mqttNumbers.map(([k, v]) => (
                    <Table.Tr key={k}><Table.Td c="dimmed">{k}</Table.Td><Table.Td className="mono" fw={600}>{String(v)}</Table.Td></Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Panel>
          </Grid.Col>
          <Grid.Col span={{ base: 12, xl: 7 }}>
            <Panel title="Message feed">
              <ScrollArea h={220}>
                {[...L.mqtt.feed].reverse().map((m, i) => (
                  <div key={i} className="logline"><span className="dim">{new Date(m.t * 1000).toLocaleTimeString([], { hour12: false })} </span>
                    <span style={{ color: "#7dd3fc" }}>{m.topic} </span>{typeof m.value === "string" ? m.value : JSON.stringify(m.value)}</div>
                ))}
              </ScrollArea>
            </Panel>
          </Grid.Col>
        </Grid>
      )}

      <Panel>
        <PromChart title="This device's radio link (measured)" unit="bps" name={name}
          query={`sum(sixg_link_bits_per_second{src="${id}"} or sixg_link_bits_per_second{dst="${id}"})`} height={180} />
      </Panel>
      {!L?.hubOnline && L && <Code>Edge hub not reachable: the live data will appear when it is back.</Code>}
    </Stack>
  );
}
