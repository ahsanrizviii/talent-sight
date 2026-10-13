// Someone's initials in a coloured circle.
// The colour comes from their name, so the same person is always the same colour, on every
// page, without anyone having to upload a photo.

const COLOURS = ["#5b8def", "#9a6cf5", "#f0789b", "#f08b4b", "#13a07a", "#0e9fb5", "#c2557e", "#5a62d8"];

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
