// Fixed positions so the picture reads like a 3GPP architecture diagram:
// devices -> RAN -> core (control plane on top, user plane below) -> data network,
// with the O-RAN RIC under the RAN. Unknown endpoints (e.g. attackers) go in a bottom row.
export const POS: Record<string, { x: number; y: number }> = {
  "ue-embb-phones": { x: 0, y: 330 },
  "ue-urllc-ctrl": { x: 0, y: 450 },
  "ue-mmtc-sensors": { x: 0, y: 570 },
  srsue: { x: 0, y: 760 },
  gnb1: { x: 290, y: 450 },
  srsgnb: { x: 290, y: 760 },
  "near-rt-ric": { x: 580, y: 880 },
  "xapp-kpm": { x: 870, y: 880 },
  "core-amf": { x: 580, y: 330 },
  "core-smf": { x: 870, y: 330 },
  "core-scp": { x: 870, y: 30 },
  "core-nrf": { x: 1160, y: 30 },
  "core-nssf": { x: 1450, y: 30 },
  "core-ausf": { x: 870, y: 140 },
  "core-udm": { x: 1160, y: 140 },
  "core-udr": { x: 1450, y: 140 },
  "core-pcf": { x: 580, y: 140 },
  "core-bsf": { x: 1160, y: 240 },
  "core-mongodb": { x: 1450, y: 240 },
  "core-webui": { x: 1740, y: 240 },
  "core-upf": { x: 1160, y: 450 },
  "upf-urllc": { x: 1160, y: 570 },
  "upf-mmtc": { x: 1160, y: 690 },
  internet: { x: 1500, y: 570 },
  "device-hub": { x: 1500, y: 720 },
};

export const ZONES = [
  { id: "z-ue", label: "User devices (UE)", x: -30, y: 290, w: 250, h: 610, color: "#a78bfa" },
  { id: "z-ran", label: "Radio access (RAN)", x: 260, y: 290, w: 250, h: 610, color: "#fbbf24" },
  { id: "z-cp", label: "5G core · control plane (SBA)", x: 550, y: -10, w: 1450, h: 430, color: "#60a5fa" },
  { id: "z-up", label: "User plane · one UPF per slice", x: 1130, y: 420, w: 260, h: 380, color: "#22d3ee" },
  { id: "z-ric", label: "O-RAN near-RT RIC", x: 550, y: 840, w: 590, h: 140, color: "#fb923c" },
  { id: "z-dn", label: "Data network", x: 1470, y: 530, w: 250, h: 130, color: "#34d399" },
  { id: "z-edge", label: "Edge (MEC)", x: 1470, y: 680, w: 250, h: 130, color: "#e879f9" },
];

export const NODE_W = 220;
export const NODE_H = 78;

export function fallbackPos(i: number) {
  return { x: 290 + i * 250, y: 1060 };
}

/** Connected devices stack under the simulated UEs. */
export function devicePos(i: number) {
  return { x: 0, y: 900 + i * 100 };
}
