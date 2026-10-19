import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { Text } from "@mantine/core";

/** Plays a device's live stream (HLS from the edge hub's MediaMTX, via the dashboard). */
export function VideoPlayer({ src, live }: { src: string; live: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v || !live) return;
    setErr(null);
    if (Hls.isSupported()) {
      const hls = new Hls({ lowLatencyMode: true, liveSyncDurationCount: 2, maxLiveSyncPlaybackRate: 1.5 });
      hls.loadSource(src);
      hls.attachMedia(v);
      hls.on(Hls.Events.MANIFEST_PARSED, () => v.play().catch(() => {}));
      hls.on(Hls.Events.ERROR, (_, d) => { if (d.fatal) { setErr(d.details); hls.recoverMediaError(); } });
      return () => hls.destroy();
    }
    v.src = src;
    v.play().catch(() => {});
  }, [src, live]);
  return (
    <div style={{ position: "relative", aspectRatio: "16 / 9", background: "#000", borderRadius: 10, overflow: "hidden" }}>
      <video ref={ref} muted playsInline controls={live} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
      {!live && (
        <Text c="dimmed" size="sm" style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          No video stream from this device
        </Text>
      )}
      {err && <Text size="xs" c="yellow" style={{ position: "absolute", left: 8, bottom: 8 }}>{err}</Text>}
    </div>
  );
}
