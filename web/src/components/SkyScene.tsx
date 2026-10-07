// The animated background: a dusk sky, layered mountains, a forest edge and birds.
// Everything is drawn in code (SVG + CSS), so there is no image or video to download.
// "hero" is the full-strength scene for public pages; "calm" darkens it for the app pages.

type Props = { variant?: "hero" | "calm" };

const WIDTH = 1600;
const HEIGHT = 900;

// A small random-number generator with a fixed seed: the mountains look the same on every visit.
function seeded(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Peak = { x: number; height: number; width: number };

// One mountain range: a rough line (midpoint displacement) plus a few peaks on top.
// The roughness grows towards the peaks, so summits look rocky and the valleys stay smooth.
function range(seed: number, base: number, roughness: number, peaks: Peak[]): string {
  const random = seeded(seed);
  const steps = 256;
  const noise = new Array<number>(steps + 1).fill(0);
  for (let size = steps, spread = roughness; size > 1; size /= 2, spread *= 0.6) {
    const half = size / 2;
    for (let i = half; i < steps; i += size) {
      noise[i] = (noise[i - half] + noise[i + half]) / 2 + (random() - 0.5) * spread;
    }
  }
  const tallest = Math.max(...peaks.map((p) => p.height));
  const points = noise.map((n, i) => {
    const x = (i / steps) * WIDTH;
    const lift = peaks.reduce(
      (sum, p) => sum + p.height * Math.max(0, 1 - Math.abs(x - p.x) / p.width) ** 1.3,
      0,
    );
    const rocky = n * (1 + 1.8 * (lift / tallest));
    return `${x.toFixed(1)},${(base - rocky - lift).toFixed(1)}`;
  });
  return `M0,${HEIGHT} L${points.join(" L")} L${WIDTH},${HEIGHT} Z`;
}

// The dark foreground: high on both sides, low in the middle.
const leftSide = (x: number) => Math.max(0, 1 - x / 640) ** 1.3;
const rightSide = (x: number) => Math.max(0, (x - 1020) / 580) ** 1.25;
const ground = (x: number) => 900 - 330 * leftSide(x) - 250 * rightSide(x);

function groundPath(): string {
  const points = [];
  for (let x = 0; x <= WIDTH; x += 20) points.push(`${x},${ground(x).toFixed(1)}`);
  return `M0,${HEIGHT} L${points.join(" L")} L${WIDTH},${HEIGHT} Z`;
}

// Pine trees along the foreground slopes: taller where the slope is closer to us.
function forest(seed: number): string {
  const random = seeded(seed);
  let path = "";
  for (let x = -10; x < WIDTH + 10; x += 5 + random() * 7) {
    const nearness = Math.max(leftSide(x), rightSide(x));
    if (nearness < 0.04) continue;
    const height = (14 + random() * 22) * (0.6 + nearness * 3.2);
    const width = height * (0.14 + random() * 0.05);
    const y = ground(x) + 6;
    path += `M${(x - width).toFixed(1)},${y.toFixed(1)} L${x.toFixed(1)},${(y - height).toFixed(1)} L${(x + width).toFixed(1)},${y.toFixed(1)} Z `;
    path += `M${(x - width * 1.6).toFixed(1)},${y.toFixed(1)} L${x.toFixed(1)},${(y - height * 0.55).toFixed(1)} L${(x + width * 1.6).toFixed(1)},${y.toFixed(1)} Z `;
  }
  return path;
}

// Worked out once when the file loads, not on every render.
const FAR = range(7, 664, 120, [
  { x: 250, height: 80, width: 300 },
  { x: 1230, height: 110, width: 340 },
  { x: 900, height: 40, width: 200 },
]);
const MAIN = range(21, 748, 110, [
  { x: 610, height: 250, width: 360 },
  { x: 1060, height: 110, width: 280 },
  { x: 260, height: 60, width: 240 },
]);
const NEAR = range(5, 816, 80, [
  { x: 1370, height: 80, width: 330 },
  { x: 170, height: 50, width: 260 },
]);
const GROUND = groundPath();
const TREES = forest(11);

export default function SkyScene({ variant = "hero" }: Props) {
  return (
    <div className={`scene scene-${variant}`} aria-hidden="true">
      <svg className="scene-land" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMidYMax slice">
        <defs>
          <linearGradient id="ts-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#3d454f" />
            <stop offset="0.3" stopColor="#59616c" />
            <stop offset="0.52" stopColor="#7d8189" />
            <stop offset="0.66" stopColor="#9b8a84" />
            <stop offset="0.76" stopColor="#a47f6b" />
            <stop offset="1" stopColor="#6a4c42" />
          </linearGradient>
          <radialGradient id="ts-glow" cx="0.5" cy="0.74" r="0.5">
            <stop offset="0" stopColor="#e6b493" stopOpacity="0.42" />
            <stop offset="1" stopColor="#e6b493" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ts-far" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#8c7068" />
            <stop offset="1" stopColor="#5d4a46" />
          </linearGradient>
          <linearGradient id="ts-main" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#6b4a40" />
            <stop offset="0.35" stopColor="#4a3530" />
            <stop offset="1" stopColor="#241d1f" />
          </linearGradient>
          <linearGradient id="ts-near" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#2e2628" />
            <stop offset="1" stopColor="#18171a" />
          </linearGradient>
          <filter id="ts-soft" x="-20%" y="-50%" width="140%" height="200%">
            <feGaussianBlur stdDeviation="26" />
          </filter>
        </defs>

        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-sky)" />
        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-glow)" />
        <path d={FAR} fill="url(#ts-far)" opacity="0.8" />
        <ellipse cx="800" cy="705" rx="860" ry="48" fill="#e9d6c8" opacity="0.08" filter="url(#ts-soft)" />
        <path d={MAIN} fill="url(#ts-main)" />
        <ellipse cx="760" cy="790" rx="700" ry="40" fill="#d9c2b3" opacity="0.05" filter="url(#ts-soft)" />
        <path d={NEAR} fill="url(#ts-near)" />
        <path d={GROUND} fill="#111214" />
        <path d={TREES} fill="#111214" />
      </svg>

      <div className="scene-grain" />
      <div className="scene-veil" />
    </div>
  );
}
