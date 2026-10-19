import { Badge, Group, Paper, Stack, Text, Tooltip } from "@mantine/core";
import type { ReactNode } from "react";
import { STATUS } from "../theme";
import type { Status } from "../types";

export function StatusDot({ status, size = 9 }: { status: Status; size?: number }) {
  const s = STATUS[status] ?? STATUS.unknown;
  return (
    <Tooltip label={s.label} withArrow>
      <span
        className={status === "down" ? "pulse" : undefined}
        style={{ display: "inline-block", width: size, height: size, borderRadius: size, background: s.color,
                 boxShadow: status === "up" ? `0 0 8px ${s.color}` : undefined, flex: "none" }}
      />
    </Tooltip>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  const s = STATUS[status] ?? STATUS.unknown;
  return (
    <Badge variant="light" radius="sm" leftSection={<StatusDot status={status} size={7} />}
           styles={{ root: { color: s.color, background: "#ffffff0a", textTransform: "none" } }}>
      {s.label}
    </Badge>
  );
}

export function Kpi({ label, value, sub, color, icon }: { label: string; value: ReactNode; sub?: ReactNode; color?: string; icon?: ReactNode }) {
  return (
    <Paper p="md" radius="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={6}>
          <Text className="section-title">{label}</Text>
          <Text className="kpi-value" style={{ color }}>{value}</Text>
          {sub && <Text size="xs" c="dimmed">{sub}</Text>}
        </Stack>
        {icon && <div style={{ opacity: 0.6 }}>{icon}</div>}
      </Group>
    </Paper>
  );
}

export function Panel({ title, right, children, p = "md" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; p?: string }) {
  return (
    <Paper p={p} radius="md">
      {(title || right) && (
        <Group justify="space-between" mb="sm">
          <Text className="section-title">{title}</Text>
          {right}
        </Group>
      )}
      {children}
    </Paper>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <Text c="dimmed" size="sm" ta="center" py="lg">{children}</Text>;
}
