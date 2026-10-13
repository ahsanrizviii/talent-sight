// The background of the whole site: a dusk sky over layered ridges that fade into haze,
// with film grain over the top. It is drawn in code (SVG + CSS), so there is no photograph to
// download, it stays sharp on any screen, and it is ours.
//
// The colours run from slate blue at the top of the sky, through grey, into the warm amber of
// the last light at the horizon. Each ridge is paler than the one in front of it: that is what
// makes the distance read as distance.

const SKY = ["#464f5c", "#555c67", "#6e6f71", "#8a7f74", "#a98a69", "#8d6f53"];
const GLOW = "#e8c097";
const RIDGE_FAR = ["#868783", "#71706f"];
const RIDGE_MID = ["#5a5c63", "#44464d", "#33343a"];
const RIDGE_NEAR = ["#2b2c31", "#1f2024"];
const GROUND = "#141519";
const HAZE = "#e6d2bd";

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
const GROUND_PATH = groundPath();
const TREES = forest(11);

export default function SkyScene() {
  const [sky0, sky1, sky2, sky3, sky4, sky5] = SKY;
  const [far0, far1] = RIDGE_FAR;
  const [main0, main1, main2] = RIDGE_MID;
  const [near0, near1] = RIDGE_NEAR;

  return (
    <div className="scene" aria-hidden="true">
      <svg className="scene-land" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMidYMax slice">
        <defs>
          <linearGradient id="ts-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={sky0} />
            <stop offset="0.3" stopColor={sky1} />
            <stop offset="0.52" stopColor={sky2} />
            <stop offset="0.66" stopColor={sky3} />
            <stop offset="0.76" stopColor={sky4} />
            <stop offset="1" stopColor={sky5} />
          </linearGradient>
          <radialGradient id="ts-glow" cx="0.5" cy="0.74" r="0.5">
            <stop offset="0" stopColor={GLOW} stopOpacity="0.5" />
            <stop offset="1" stopColor={GLOW} stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ts-far" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={far0} />
            <stop offset="1" stopColor={far1} />
          </linearGradient>
          <linearGradient id="ts-main" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={main0} />
            <stop offset="0.35" stopColor={main1} />
            <stop offset="1" stopColor={main2} />
          </linearGradient>
          <linearGradient id="ts-near" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={near0} />
            <stop offset="1" stopColor={near1} />
          </linearGradient>
          <filter id="ts-soft" x="-20%" y="-50%" width="140%" height="200%">
            <feGaussianBlur stdDeviation="26" />
          </filter>
        </defs>

        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-sky)" />
        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-glow)" />
        <path d={FAR} fill="url(#ts-far)" opacity="0.8" />
        <ellipse cx="800" cy="705" rx="860" ry="48" fill={HAZE} opacity="0.16" filter="url(#ts-soft)" />
        <path d={MAIN} fill="url(#ts-main)" />
        <ellipse cx="760" cy="790" rx="700" ry="40" fill={HAZE} opacity="0.12" filter="url(#ts-soft)" />
        <path d={NEAR} fill="url(#ts-near)" />
        <path d={GROUND_PATH} fill={GROUND} />
        <path d={TREES} fill={GROUND} />
      </svg>

      <div className="scene-grain" />
      <div className="scene-veil" />
    </div>
  );
}
