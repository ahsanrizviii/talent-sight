// The small dark square with a chevron that sits at the end of a pill button.
export default function Arrow() {
  return (
    <span className="arrow-box" aria-hidden="true">
      <svg viewBox="0 0 16 16">
        <path d="M6 3.5 10.5 8 6 12.5" />
      </svg>
    </span>
  );
}
