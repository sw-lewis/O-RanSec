import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/** Position and recent track of a device (OpenStreetMap tiles). */
export function LiveMap({ lat, lon, track, height = 320 }: { lat: number; lon: number; track: [number, number][]; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const line = useRef<L.Polyline | null>(null);
  const followed = useRef(false);

  useEffect(() => {
    const m = L.map(el.current!, { zoomControl: true, attributionControl: true }).setView([lat, lon], 17);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    line.current = L.polyline([], { color: "#22d3ee", weight: 3, opacity: 0.8 }).addTo(m);
    marker.current = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2, fillColor: "#22d3ee", fillOpacity: 1 }).addTo(m);
    map.current = m;
    return () => { m.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    marker.current?.setLatLng([lat, lon]);
    line.current?.setLatLngs(track);
    if (!followed.current && map.current) { map.current.setView([lat, lon], 17); followed.current = true; }
    else if (map.current && !map.current.getBounds().pad(-0.2).contains([lat, lon])) map.current.panTo([lat, lon]);
  }, [lat, lon, track]);

  return <div ref={el} style={{ height, borderRadius: 10, overflow: "hidden" }} />;
}
