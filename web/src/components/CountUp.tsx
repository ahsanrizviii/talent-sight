import { useEffect, useRef, useState } from "react";

// A number that counts up to its value when the page arrives, so the dashboard reads as live
// rather than printed. It respects the computer's reduced-motion setting: anyone who has asked
// for less movement sees the final number straight away.
export default function CountUp({ value, decimals = 0 }: { value: number | null; decimals?: number }) {
  const [shown, setShown] = useState(value ?? 0);
  const frame = useRef(0);

  useEffect(() => {
    if (value === null) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (calm || value === 0) {
      setShown(value);
      return;
    }

    const started = performance.now();
    const run = (now: number) => {
      const part = Math.min(1, (now - started) / 750);
      const eased = 1 - (1 - part) ** 3; // fast at first, settling at the end
      setShown(value * eased);
      if (part < 1) frame.current = requestAnimationFrame(run);
    };
    frame.current = requestAnimationFrame(run);
    return () => cancelAnimationFrame(frame.current);
  }, [value]);

  if (value === null) return <>—</>;
  return <>{shown.toFixed(decimals)}</>;
}
