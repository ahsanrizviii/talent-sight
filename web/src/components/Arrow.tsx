
// The small dark square with an arrow that sits at the end of a white pill button.
export default function Arrow() {
  return (
    <span className="arrow-box" aria-hidden="true">
      <svg viewBox="0 0 16 16">
        <path d="M3.5 8h9M8.6 4.1 12.5 8l-3.9 3.9" />
      </svg>
    </span>
  );
}
