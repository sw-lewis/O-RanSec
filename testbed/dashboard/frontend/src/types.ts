export type Status = "up" | "degraded" | "down" | "stopped" | "absent" | "idle" | "unknown";
export type LinkStatus = "active" | "connected" | "idle" | "down";

export interface PodInfo {
  name: string; ready: boolean; phase: string; ip: string | null;
  restarts: number; age: number | null; reason: string | null;
}

export interface Component {
  id: string; label: string; layer: string; ns?: string; kind?: string; software?: string;
  slice?: string; virtual?: boolean; ueGroup?: boolean; device?: boolean; workload?: string; container?: string;
  status: Status; notes: string[]; pods: PodInfo[]; cpu: number; mem: number; desired?: number | null;
}

export interface Link {
  a: string; b: string; iface: string; bps: number; pps: number; flows: number;
  status: LinkStatus; expected: boolean; ns?: string[];
}

export interface Slice {
  id: string; label: string; sst: number; sd: string; dnn: string; pool: string; color: string;
  upf: string; registered: number | null; sessions: number | null; n3_bps: number; n6_bps: number; upfStatus?: Status;
}

export interface KEvent { ns: string; type: string; reason: string; object: string; message: string; count: number; time: string | null }

export interface State {
  ts: number;
  sources: Record<string, { ok: boolean; age?: number | null }>;
  node: { name?: string; ready?: boolean; kubelet?: string; os?: string; kernel?: string; runtime?: string;
          cpu?: string; memory?: string; cpuUsed: number | null; memUsed: number | null; diskUsed: number | null };
  kpis: {
    gnbs: number | null; ranUes: number | null; amfSessions: number | null;
    registeredTotal: number | null; sessionsTotal: number | null; n3Bps: number; n6Bps: number;
    alerts: number; logErrors5m: number | null; logLines5m: number | null;
    logErrorsByNs: Record<string, number> | null; componentCounts: Record<string, number>;
    scrapeTargets: Record<string, { up: number; total: number }>;
  };
  components: Component[];
  links: Link[];
  slices: Slice[];
  alerts: { name: string; severity: string; summary: string; since: string }[];
  events: KEvent[];
}

export interface Catalog {
  layers: { id: string; label: string; order: number }[];
  slices: { id: string; label: string; color: string }[];
  components: { id: string; label: string; layer: string }[];
  links: { a: string; b: string; iface: string }[];
}

export interface LogLine { ts: number; line: string; labels: Record<string, string> }
