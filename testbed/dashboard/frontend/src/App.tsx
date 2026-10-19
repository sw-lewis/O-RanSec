import { useEffect, useState } from "react";
import { AppShell, Badge, Center, Group, Loader, NavLink, Stack, Text, Tooltip } from "@mantine/core";
import {
  IconAntenna, IconChartDots3, IconCloudComputing, IconExternalLink, IconFileText, IconLayoutDashboard,
  IconAdjustmentsHorizontal, IconServer, IconStack2, IconPlugConnected,
} from "@tabler/icons-react";
import { useLiveState } from "./api";
import { Architecture } from "./arch/Architecture";
import { ComponentDrawer } from "./components/ComponentDrawer";
import { ConfirmHost } from "./components/modals";
import { Overview } from "./pages/Overview";
import { Control } from "./pages/Control";
import { Core } from "./pages/Core";
import { RanRic } from "./pages/RanRic";
import { Slices } from "./pages/Slices";
import { Logs } from "./pages/Logs";
import { ClusterPage } from "./pages/Cluster";
import { Devices } from "./pages/Devices";
import { DeviceLive } from "./pages/DeviceLive";

const PAGES = [
  { id: "overview", label: "Overview", icon: IconLayoutDashboard },
  { id: "architecture", label: "Live Architecture", icon: IconChartDots3 },
  { id: "control", label: "Control Panel", icon: IconAdjustmentsHorizontal },
  { id: "devices", label: "Devices", icon: IconPlugConnected },
  { id: "core", label: "5G Core", icon: IconServer },
  { id: "ran", label: "RAN & RIC", icon: IconAntenna },
  { id: "slices", label: "Slices", icon: IconStack2 },
  { id: "logs", label: "Logs", icon: IconFileText },
  { id: "cluster", label: "Cluster", icon: IconCloudComputing },
] as const;

function useHashPage() {
  const read = () => (location.hash.replace("#/", "") || "overview");
  const [page, setPage] = useState(read);
  useEffect(() => {
    const f = () => setPage(read());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return [page, (p: string) => { location.hash = `#/${p}`; }] as const;
}

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  return <Text className="mono" size="sm" c="dimmed">{now.toLocaleTimeString([], { hour12: false })}</Text>;
}

export default function App() {
  const { state, connected } = useLiveState();
  const [page, go] = useHashPage();
  const [selected, setSelected] = useState<string | null>(null);

  const counts = state?.kpis.componentCounts ?? {};
  const total = state?.components.length ?? 0;
  const healthy = (counts.up ?? 0) + (counts.idle ?? 0);
  const problems = (counts.down ?? 0) + (counts.degraded ?? 0);
  const stale = state ? Date.now() / 1000 - state.ts > 10 : true;

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm" }} padding="md"
              styles={{ main: { background: "var(--bg)" }, header: { background: "#0a0f16", borderColor: "var(--line)" },
                        navbar: { background: "#0a0f16", borderColor: "var(--line)" } }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="#0b1220" />
              <path d="M8 22a11 11 0 0 1 16 0M11 18a7 7 0 0 1 10 0" stroke="#22d3ee" strokeWidth="2.4" fill="none" strokeLinecap="round" />
              <circle cx="16" cy="23" r="2.2" fill="#22d3ee" /></svg>
            <div>
              <Text fw={700} size="sm" lh={1.1}>6G Security Testbed</Text>
              <Text size="10.5px" c="dimmed" lh={1.1}>Control & observability · single-VM O-Cloud</Text>
            </div>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label="Components healthy / total"><Badge variant="light" color={problems ? "yellow" : "teal"} size="lg">{healthy}/{total} healthy</Badge></Tooltip>
            {problems > 0 && <Badge variant="light" color="red" size="lg">{problems} need attention</Badge>}
            <Badge variant="light" color="cyan" size="lg">{state?.kpis.registeredTotal ?? "–"} UEs</Badge>
            {!!state?.kpis.alerts && <Badge variant="light" color="orange" size="lg">{state.kpis.alerts} alerts</Badge>}
            <Badge variant="dot" color={connected && !stale ? "teal" : "red"} size="lg">{connected ? (stale ? "stale" : "live") : "offline"}</Badge>
            <Clock />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <Stack gap={2} style={{ flex: 1 }}>
          {PAGES.map((p) => (
            <NavLink key={p.id} label={p.label} leftSection={<p.icon size={17} stroke={1.6} />} active={page === p.id || (p.id === "devices" && page.startsWith("device/"))}
                     onClick={() => go(p.id)} variant="light" styles={{ root: { borderRadius: 8 } }} />
          ))}
          <NavLink label="Grafana" description="dashboards & Explore" leftSection={<IconExternalLink size={17} stroke={1.6} />}
                   href="http://127.0.0.1:8661/" target="_blank" styles={{ root: { borderRadius: 8 } }} />
        </Stack>
        <Text size="10px" c="dimmed" p="xs">All values are measured live from Kubernetes, Open5GS, srsRAN, FlexRIC, Prometheus, Loki and kernel conntrack.</Text>
      </AppShell.Navbar>

      <AppShell.Main>
        {!state ? (
          <Center h="70vh"><Stack align="center"><Loader /><Text c="dimmed">Connecting to the testbed…</Text></Stack></Center>
        ) : (
          <>
            {page === "overview" && <Overview state={state} onSelect={setSelected} />}
            {page === "architecture" && <Architecture state={state} onSelect={setSelected} selected={selected} />}
            {page === "control" && <Control state={state} onSelect={setSelected} />}
            {page === "devices" && <Devices />}
            {page.startsWith("device/") && <DeviceLive id={page.slice(7)} />}
            {page === "core" && <Core state={state} onSelect={setSelected} />}
            {page === "ran" && <RanRic state={state} />}
            {page === "slices" && <Slices state={state} />}
            {page === "logs" && <Logs />}
            {page === "cluster" && <ClusterPage />}
          </>
        )}
      </AppShell.Main>
      <ComponentDrawer id={selected} state={state} onClose={() => setSelected(null)} />
      <ConfirmHost />
    </AppShell>
  );
}
