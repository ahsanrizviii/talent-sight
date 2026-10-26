// Someone's initials in a circle.
// The colour comes from their name, so the same person is always the same colour, on every
// page, without anyone having to upload a photo. The tones come from the mountain scene: lake
// blue, slate, pine, moss, heather and a warm rose for the morning light, all dark enough for
// white initials to read on top.

const COLOURS = [
  "#3f6f9e",
  "#56677d",
  "#3d6a5f",
  "#5d7448",
  "#6c5f8f",
  "#9a5f6c",
  "#2f5d7c",
  "#7a6656",
];

function pick(name: string): string {
  let total = 0;
  for (const letter of name) total = (total * 31 + letter.charCodeAt(0)) % 100000;
  return COLOURS[total % COLOURS.length];
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

export default function Avatar({ name, big = false }: { name: string; big?: boolean }) {
  return (
    <span className={big ? "avatar big" : "avatar"} style={{ background: pick(name) }} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
