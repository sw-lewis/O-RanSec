import { Button, Group, Modal, Text } from "@mantine/core";
import { useSyncExternalStore } from "react";

// Tiny confirm-dialog store (avoids an extra dependency).
type Req = { title: string; body: string; confirm: string; danger?: boolean; onConfirm: () => void };
let current: Req | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

export const modals = {
  confirm(r: Req) { current = r; emit(); },
};

export function ConfirmHost() {
  const req = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => current);
  const close = () => { current = null; emit(); };
  return (
    <Modal opened={!!req} onClose={close} title={<Text fw={700}>{req?.title}</Text>} centered>
      <Text size="sm" mb="lg">{req?.body}</Text>
      <Group justify="flex-end">
        <Button variant="default" onClick={close}>Cancel</Button>
        <Button color={req?.danger ? "red" : "cyan"} onClick={() => { const r = req; close(); r?.onConfirm(); }}>
          {req?.confirm ? req.confirm[0].toUpperCase() + req.confirm.slice(1) : "OK"}
        </Button>
      </Group>
    </Modal>
  );
}
