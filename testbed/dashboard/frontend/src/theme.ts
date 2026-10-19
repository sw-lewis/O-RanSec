import { createTheme, type MantineColorsTuple } from "@mantine/core";

const cyan: MantineColorsTuple = ["#e3fbff", "#cdf2fd", "#9ce3f9", "#67d4f5", "#3fc7f2", "#26bff0", "#12bbf0", "#00a4d6", "#0092c0", "#007faa"];

export const theme = createTheme({
  primaryColor: "cyan",
  colors: { cyan },
  fontFamily: "'Inter Variable', Inter, system-ui, sans-serif",
  fontFamilyMonospace: "'JetBrains Mono', ui-monospace, monospace",
  headings: { fontFamily: "'Inter Variable', Inter, system-ui, sans-serif", fontWeight: "600" },
  defaultRadius: "md",
  components: {
    Paper: { defaultProps: { bg: "var(--panel)", withBorder: true } },
    Card: { defaultProps: { bg: "var(--panel)", withBorder: true } },
  },
});

/** One place for status semantics: colour + words. */
export const STATUS = {
  up:       { color: "var(--ok)",    label: "Healthy" },
  degraded: { color: "var(--warn)",  label: "Degraded" },
  down:     { color: "var(--bad)",   label: "Down" },
  stopped:  { color: "var(--muted)", label: "Stopped" },
  absent:   { color: "var(--muted)", label: "Not deployed" },
  idle:     { color: "var(--info)",  label: "Idle" },
  unknown:  { color: "var(--muted)", label: "Unknown" },
} as const;

/** 3GPP / O-RAN interface colours used on the live architecture. */
export const IFACE: Record<string, { color: string; label: string }> = {
  Uu:   { color: "#a78bfa", label: "Uu · radio" },
  N2:   { color: "#fbbf24", label: "N2 · NGAP (control)" },
  N3:   { color: "#22d3ee", label: "N3 · GTP-U (user data)" },
  N4:   { color: "#f472b6", label: "N4 · PFCP (session rules)" },
  N6:   { color: "#34d399", label: "N6 · data network" },
  SBI:  { color: "#60a5fa", label: "SBI · HTTP/2 core bus" },
  E2:   { color: "#fb923c", label: "E2 · RAN ↔ RIC" },
  E42:  { color: "#f97316", label: "E42 · xApp ↔ RIC" },
  DB:   { color: "#94a3b8", label: "DB · subscriber store" },
  other:{ color: "#ef4444", label: "Unexpected traffic" },
};
