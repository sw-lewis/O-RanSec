import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Code, Group, MultiSelect, Paper, ScrollArea, Select, Switch, Text, TextInput } from "@mantine/core";
import { IconDownload, IconSearch } from "@tabler/icons-react";
import { get, openSocket } from "../api";
import { levelColor } from "../components/ComponentDrawer";
import { clock } from "../fmt";
import type { LogLine } from "../types";

const MAX = 3000;

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\"]/g, "\\$&");
}

export function Logs() {
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [ns, setNs] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [pod, setPod] = useState("");
  const [text, setText] = useState("");
  const [minutes, setMinutes] = useState("15");
  const [live, setLive] = useState(true);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [status, setStatus] = useState("");
  const viewport = useRef<HTMLDivElement>(null);

  useEffect(() => { get<string[]>("/api/logs/labels/namespace").then(setNamespaces).catch(() => {}); }, []);

  // LogQL built from the filters; shown to the user so they can reuse it in Grafana.
  const query = useMemo(() => {
    const sel = [ns.length ? `namespace=~"${ns.map(escapeRe).join("|")}"` : `namespace=~".+"`];
    if (pod) sel.push(`pod=~".*${escapeRe(pod)}.*"`);
    if (levels.length) sel.push(`level=~"${levels.join("|")}"`);
    return `{${sel.join(", ")}}${text ? ` |~ "(?i)${escapeRe(text)}"` : ""}`;
  }, [ns, pod, levels, text]);

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    setStatus("loading…");
    get<LogLine[]>(`/api/logs?query=${encodeURIComponent(query)}&minutes=${minutes}&limit=1000`)
      .then((d) => {
        if (cancelled) return;
        setLines(d);
        setStatus(`${d.length} lines from the last ${minutes} min`);
        if (live) {
          ws = openSocket(`/ws/logs?query=${encodeURIComponent(query)}`, (msg) => {
            if (!Array.isArray(msg)) { setStatus(`live tail error: ${JSON.stringify(msg)}`); return; }
            setLines((prev) => [...(msg as LogLine[]).sort((a, b) => b.ts - a.ts), ...prev].slice(0, MAX));
          }, (open) => setStatus((s) => (open ? `${s.split(" ·")[0]} · live` : `${s.split(" ·")[0]} · tail closed`)));
        }
      })
      .catch((e) => !cancelled && setStatus(String(e)));
    return () => { cancelled = true; ws?.close(); };
  }, [query, minutes, live]);

  const download = (fmt: "log" | "json") => {
    const body = fmt === "json"
      ? JSON.stringify(lines.map((l) => ({ time: new Date(l.ts / 1e6).toISOString(), ...l.labels, line: l.line })), null, 1)
      : lines.map((l) => `${new Date(l.ts / 1e6).toISOString()} [${l.labels.namespace}/${l.labels.pod ?? l.labels.job ?? ""}] ${l.line}`).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
    a.download = `sixg-logs-${new Date().toISOString().replace(/[:.]/g, "-")}.${fmt}`;
    a.click();
  };

  return (
    <Paper p="md" style={{ height: "calc(100vh - 110px)", display: "flex", flexDirection: "column" }}>
      <Group gap="sm" align="flex-end" mb="sm">
        <MultiSelect label="Namespace" data={namespaces} value={ns} onChange={setNs} w={260} size="xs" clearable searchable placeholder="all testbed" />
        <TextInput label="Pod contains" value={pod} onChange={(e) => setPod(e.currentTarget.value)} w={160} size="xs" />
        <MultiSelect label="Level" data={["error", "warning", "warn", "info", "debug"]} value={levels} onChange={setLevels} w={200} size="xs" clearable />
        <TextInput label="Text (regex, case-insensitive)" value={text} onChange={(e) => setText(e.currentTarget.value)} w={240} size="xs" leftSection={<IconSearch size={14} />} />
        <Select label="History" data={[{ value: "5", label: "5 min" }, { value: "15", label: "15 min" }, { value: "60", label: "1 hour" }, { value: "360", label: "6 hours" }, { value: "1440", label: "24 hours" }]}
                value={minutes} onChange={(v) => setMinutes(v ?? "15")} w={110} size="xs" />
        <Switch label="Live tail" checked={live} onChange={(e) => setLive(e.currentTarget.checked)} size="sm" mb={4} />
        <Group gap={4} ml="auto">
          <Button size="xs" variant="default" leftSection={<IconDownload size={14} />} onClick={() => download("log")}>.log</Button>
          <Button size="xs" variant="default" leftSection={<IconDownload size={14} />} onClick={() => download("json")}>.json</Button>
        </Group>
      </Group>
      <Group gap="xs" mb="xs">
        <Code style={{ fontSize: 11 }}>{query}</Code>
        <Badge size="xs" variant="dot" color={status.includes("live") ? "teal" : "gray"}>{status}</Badge>
      </Group>
      <ScrollArea style={{ flex: 1, background: "#05080c", borderRadius: 8 }} viewportRef={viewport} p="xs">
        {lines.length === 0 && <Text size="xs" c="dimmed">No lines match.</Text>}
        {lines.map((l, i) => (
          <div key={`${l.ts}-${i}`} className="logline">
            <span className="dim">{clock(l.ts)} </span>
            <span style={{ color: "#7dd3fc" }}>{l.labels.pod ?? l.labels.unit ?? l.labels.job ?? l.labels.namespace} </span>
            <span style={{ color: levelColor(l.labels.level) }}>{l.line}</span>
          </div>
        ))}
      </ScrollArea>
    </Paper>
  );
}
