import { useMemo } from "react";

/*
  Snow
  -----
  Drifting snow particles for scene backgrounds. Ported from
  seedSnow() in the original index.html — same count (24), same
  randomized size/position/duration/delay ranges. Generated once per
  mount via useMemo rather than DOM manipulation, since this is React.
*/
export default function Snow({ count = 24 }) {
  const flakes = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        id: i,
        size: 2 + Math.random() * 3,
        left: Math.random() * 100,
        duration: 8 + Math.random() * 10,
        delay: Math.random() * 10,
      })),
    [count]
  );

  return (
    <div className="snow">
      {flakes.map((f) => (
        <div
          key={f.id}
          className="flake"
          style={{
            width: `${f.size}px`,
            height: `${f.size}px`,
            left: `${f.left}%`,
            animationDuration: `${f.duration}s`,
            animationDelay: `${f.delay}s`,
          }}
        />
      ))}
    </div>
  );
}
