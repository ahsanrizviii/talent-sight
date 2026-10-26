// The background of the whole site: a clear morning over snowy mountains, with a warm glow low on
// the left, pine woods on the right and mist rising from the valley at the bottom. It is drawn in
// code (SVG + CSS), so there is no photograph to download, it stays sharp on any screen, and it is ours.
//
// The light comes from the left (the glow), so every mountain is lit on its left face and in
// shadow on its right. Each range is paler and bluer than the one in front of it: that is what
// makes the distance read as distance.

const WIDTH = 1600;
const HEIGHT = 900;

const SKY = ["#7eaedb", "#9cc2e5", "#bfd7ec", "#dbe7f1", "#eef2f6"];
const GLOW = "#ffd2b0";
const CLOUD = "#ffffff";
const FAR = ["#c3d3e2", "#d3dfea"];
const SNOW = "#f9fbfd";
const ROCK = ["#a3b9d0", "#7f99b6", "#6c87a6"];
const SHADOW = "#3f5d82";
const TREES_FAR = "#93abbd";
const TREES_MID = "#58768a";
const TREES_NEAR = "#24404d";
const MIST = "#f3f6f9";

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
type Point = [number, number];

// One mountain range as a list of points along its top edge: a rough line (midpoint displacement)
// plus a few peaks on top. The roughness grows towards the peaks, so summits look rocky and the
// valleys stay smooth.
function ridge(seed: number, base: number, roughness: number, peaks: Peak[]): Point[] {
  const random = seeded(seed);
  const steps = 256;
  const noise = new Array<number>(steps + 1).fill(0);
  for (let size = steps, spread = roughness; size > 1; size /= 2, spread *= 0.58) {
    const half = size / 2;
    for (let i = half; i < steps; i += size) {
      noise[i] = (noise[i - half] + noise[i + half]) / 2 + (random() - 0.5) * spread;
    }
  }
  const tallest = Math.max(...peaks.map((p) => p.height));
  return noise.map((n, i) => {
    const x = (i / steps) * WIDTH;
    const lift = peaks.reduce(
      (sum, p) => sum + p.height * Math.max(0, 1 - Math.abs(x - p.x) / p.width) ** 1.25,
      0,
    );
    const rocky = n * (0.5 + 1.6 * (lift / tallest));
    return [x, base - rocky - lift];
  });
}

const fixed = (n: number) => n.toFixed(1);

// The ridge closed down to the bottom of the picture, so it can be filled.
function fill(points: Point[]): string {
  return `M0,${HEIGHT} L${points.map(([x, y]) => `${fixed(x)},${fixed(y)}`).join(" L")} L${WIDTH},${HEIGHT} Z`;
}

// The shaded right-hand face of one peak: from the summit along the ridge down to the next
// valley, down the slope to the foot, and back up to the summit along the arete, a broken line
// leaning left (a real shadow edge is never straight).
function shadowFace(points: Point[], peak: Peak, base: number, seed: number): string {
  const random = seeded(seed);
  const near = points.filter(([x]) => Math.abs(x - peak.x) < peak.width * 0.3);
  const [sx, sy] = near.reduce((top, p) => (p[1] < top[1] ? p : top));
  const right = points.filter(([x]) => x > sx && x <= sx + peak.width * 0.85);
  const valley = right.reduce((low, p) => (p[1] > low[1] ? p : low), [sx, sy] as Point);
  const along = right.filter(([x]) => x <= valley[0]);
  const footRight: Point = [valley[0] + peak.width * 0.2, base + 40];
  const footLeft: Point = [sx - peak.width * 0.42, base + 40];
  const arete: Point[] = [];
  for (let i = 1; i < 16; i++) {
    const t = i / 16;
    const wobble = (random() - 0.5) * 22 * Math.sin(Math.PI * t);
    arete.push([footLeft[0] + (sx - footLeft[0]) * t ** 0.8 + wobble, footLeft[1] + (sy - footLeft[1]) * t]);
  }
  const line: Point[] = [[sx, sy], ...along, footRight, footLeft, ...arete];
  return `M${line.map(([x, y]) => `${fixed(x)},${fixed(y)}`).join(" L")} Z`;
}

// Gullies of bare rock running down the lit faces, so the snow reads as lying on a mountain
// rather than as a white band painted across it.
function gullies(points: Point[], peaks: Peak[], seed: number): string {
  const random = seeded(seed);
  let path = "";
  for (const peak of peaks.filter((p) => p.height > 100)) {
    for (let k = 0; k < 9; k++) {
      const x0 = peak.x - peak.width * (0.04 + random() * 0.55);
      const top = points.reduce((best, p) => (Math.abs(p[0] - x0) < Math.abs(best[0] - x0) ? p : best));
      let [x, y] = [top[0], top[1] + 6];
      const length = 40 + random() * (peak.height * 0.55);
      const steps = 8;
      const left: Point[] = [];
      const rightSide: Point[] = [];
      for (let i = 0; i <= steps; i++) {
        const t = i / steps;
        const half = 0.4 + 1.6 * Math.sin(Math.PI * t) * (0.5 + random());
        left.push([x - half, y]);
        rightSide.push([x + half, y]);
        x += -4 + (random() - 0.5) * 5;
        y += length / steps;
      }
      const shape = [...left, ...rightSide.reverse()];
      path += `M${shape.map(([px, py]) => `${fixed(px)},${fixed(py)}`).join(" L")} Z `;
    }
  }
  return path;
}

// A pine: four tiers stacked from the top, each wider than the one above it.
function pine(x: number, base: number, height: number, width: number): string {
  const tiers = [
    [1.0, 0.56, 0.32],
    [0.8, 0.34, 0.48],
    [0.6, 0.13, 0.64],
    [0.4, -0.02, 0.8],
  ];
  return tiers
    .map(([top, bottom, half]) => {
      const apex = base - height * top;
      const foot = base - height * bottom;
      const left = x - width * half;
      const right = x + width * half;
      return `M${fixed(left)},${fixed(foot)} Q${fixed(x)},${fixed(foot - height * 0.05)} ${fixed(right)},${fixed(foot)} L${fixed(x)},${fixed(apex)} Z`;
    })
    .join(" ");
}

// A line of pines standing on a slope. `ground` gives the height of the slope at each x,
// `size` how tall the trees are there (0 means no tree).
function forest(seed: number, from: number, to: number, gap: number, ground: (x: number) => number, size: (x: number) => number): string {
  const random = seeded(seed);
  let path = "";
  for (let x = from; x < to; x += gap * (0.55 + random() * 0.9)) {
    const tall = size(x) * (0.7 + random() * 0.55);
    if (tall < 4) continue;
    path += pine(x, ground(x) + random() * 6, tall, tall * (0.34 + random() * 0.08)) + " ";
  }
  return path;
}

// The wooded hill in the right foreground, rising towards the edge of the picture.
const rise = (x: number) => Math.max(0, (x - 1000) / 600) ** 1.4;
const hill = (x: number) => 896 - 320 * rise(x);

function hillPath(): string {
  const points: Point[] = [];
  for (let x = 900; x <= WIDTH; x += 20) points.push([x, hill(x)]);
  return `M900,${HEIGHT} L${points.map(([x, y]) => `${x},${fixed(y)}`).join(" L")} L${WIDTH},${HEIGHT} Z`;
}

// Clouds: each one a few soft puffs leaning on each other. [x, y, width, height, strength]
const CLOUDS = [
  [250, 210, 190, 26, 0.5], [400, 196, 130, 30, 0.42], [120, 224, 120, 18, 0.36],
  [1120, 150, 220, 22, 0.42], [1290, 138, 150, 26, 0.36], [1010, 162, 110, 16, 0.3],
  [760, 300, 170, 16, 0.32], [880, 292, 90, 14, 0.26],
  [1460, 340, 150, 15, 0.3], [140, 430, 180, 22, 0.36], [300, 440, 110, 14, 0.3],
];

// Worked out once when the file loads, not on every render.
const FAR_RIDGE = ridge(7, 650, 70, [
  { x: 260, height: 70, width: 300 },
  { x: 700, height: 120, width: 260 },
  { x: 1500, height: 90, width: 280 },
]);

const MAIN_PEAKS: Peak[] = [
  { x: 1170, height: 320, width: 360 },
  { x: 900, height: 190, width: 250 },
  { x: 1470, height: 230, width: 250 },
  { x: 480, height: 60, width: 260 },
];
const MAIN_RIDGE = ridge(21, 712, 90, MAIN_PEAKS);
const MAIN_PATH = fill(MAIN_RIDGE);
const SHADOWS = MAIN_PEAKS.filter((p) => p.height > 100)
  .map((p, i) => shadowFace(MAIN_RIDGE, p, 712, 40 + i))
  .join(" ");
const GULLIES = gullies(MAIN_RIDGE, MAIN_PEAKS, 77);

const TREES_BACK = forest(3, 640, 1640, 9, (x) => 728 + 10 * Math.sin(x / 90), (x) => (x < 700 ? 0 : 16 + 10 * rise(x)));
const TREES_MIDDLE = forest(9, 960, 1640, 9, (x) => hill(x) + 46, (x) => 20 + 80 * rise(x));
const TREES_FRONT = forest(11, 1130, 1640, 12, (x) => hill(x) + 14, (x) => (x < 1150 ? 0 : 46 + 170 * rise(x)));
const HILL_PATH = hillPath();

export default function SkyScene() {
  const [sky0, sky1, sky2, sky3, sky4] = SKY;
  const [far0, far1] = FAR;
  const [rock0, rock1, rock2] = ROCK;

  return (
    <div className="scene" aria-hidden="true">
      <svg className="scene-land" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMidYMax slice">
        <defs>
          <linearGradient id="ts-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={sky0} />
            <stop offset="0.32" stopColor={sky1} />
            <stop offset="0.56" stopColor={sky2} />
            <stop offset="0.72" stopColor={sky3} />
            <stop offset="1" stopColor={sky4} />
          </linearGradient>
          <radialGradient id="ts-glow" cx="0.14" cy="0.7" r="0.62">
            <stop offset="0" stopColor={GLOW} stopOpacity="0.95" />
            <stop offset="0.4" stopColor={GLOW} stopOpacity="0.42" />
            <stop offset="1" stopColor={GLOW} stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ts-far" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={far0} />
            <stop offset="1" stopColor={far1} />
          </linearGradient>
          {/* Snow down to about two thirds of the way from the summit, then bare rock below it. */}
          <linearGradient id="ts-rock" gradientUnits="userSpaceOnUse" x1="0" y1="380" x2="0" y2="712">
            <stop offset="0" stopColor={SNOW} />
            <stop offset="0.28" stopColor="#eef3f8" />
            <stop offset="0.46" stopColor={rock0} />
            <stop offset="0.74" stopColor={rock1} />
            <stop offset="1" stopColor={rock2} />
          </linearGradient>
          <linearGradient id="ts-mist" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={MIST} stopOpacity="0" />
            <stop offset="0.5" stopColor={MIST} stopOpacity="0.55" />
            <stop offset="1" stopColor={MIST} stopOpacity="0.98" />
          </linearGradient>
          <clipPath id="ts-main-clip">
            <path d={MAIN_PATH} />
          </clipPath>
          <filter id="ts-cloud" x="-30%" y="-60%" width="160%" height="220%">
            <feGaussianBlur stdDeviation="16" />
          </filter>
          <filter id="ts-haze" x="-20%" y="-300%" width="140%" height="700%">
            <feGaussianBlur stdDeviation="30" />
          </filter>
        </defs>

        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-sky)" />
        <rect width={WIDTH} height={HEIGHT} fill="url(#ts-glow)" />

        {/* Soft clouds, brushed thin and wide. */}
        <g fill={CLOUD} filter="url(#ts-cloud)">
          {CLOUDS.map(([cx, cy, rx, ry, opacity], i) => (
            <ellipse key={i} cx={cx} cy={cy} rx={rx} ry={ry} opacity={opacity} />
          ))}
        </g>

        <path d={fill(FAR_RIDGE)} fill="url(#ts-far)" />
        <ellipse cx="800" cy="660" rx="900" ry="40" fill={MIST} opacity="0.55" filter="url(#ts-haze)" />

        <path d={MAIN_PATH} fill="url(#ts-rock)" />
        <g clipPath="url(#ts-main-clip)">
          <path d={GULLIES} fill={ROCK[1]} opacity="0.3" />
          <path d={SHADOWS} fill={SHADOW} opacity="0.26" />
        </g>

        <ellipse cx="900" cy="730" rx="820" ry="34" fill={MIST} opacity="0.7" filter="url(#ts-haze)" />
        <path d={TREES_BACK} fill={TREES_FAR} opacity="0.75" />
        <path d={TREES_MIDDLE} fill={TREES_MID} />
        <path d={HILL_PATH} fill={TREES_MID} />
        <path d={TREES_FRONT} fill={TREES_NEAR} />

        <rect y="640" width={WIDTH} height="260" fill="url(#ts-mist)" />
      </svg>

      <div className="scene-grain" />
      <div className="scene-veil" />
    </div>
  );
}
