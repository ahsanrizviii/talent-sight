// Someone's initials in a circle.
// The colour comes from their name, so the same person is always the same colour, on every
// page, without anyone having to upload a photo. The tones are the dusk ones: sand, clay,
// amber, slate and moss, kept dark enough for white initials to read on top.

const COLOURS = [
  "#7d6a56",
  "#8a5f4b",
  "#6f6c5c",
  "#4f5a62",
  "#5d6b5c",
  "#8b6f4e",
  "#5a5560",
  "#746253",
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
