import { useEffect, useRef } from "react";

/*
  TransitionScene
  -----------------
  Boot-style animation shown for ~1.45s right after a successful login,
  before the Intro (lore) scene. Ported from #scene-transition /
  runBoot() in the original index.html — same timing, same 3-line
  sequence, same fill-bar behavior, same white flash-out at the end.

  Calls onDone() once the sequence finishes so the parent can advance
  to the Intro scene.
*/
export default function TransitionScene({ onDone }) {
  const fillRef = useRef(null);
  const line1Ref = useRef(null);
  const line2Ref = useRef(null);
  const line3Ref = useRef(null);
  const flashRef = useRef(null);

  useEffect(() => {
    const fill = fillRef.current;
    // Force a reflow before starting the width transition, matching the
    // original's `void fill.offsetWidth` reset-then-animate pattern.
    fill.style.transition = "none";
    fill.style.width = "0%";
    // eslint-disable-next-line no-unused-expressions
    fill.offsetWidth;
    fill.style.transition = "width 1.4s cubic-bezier(0.3,0.7,0.3,1)";
    fill.style.width = "100%";

    line1Ref.current.classList.add("show");
    const t1 = setTimeout(() => line2Ref.current.classList.add("show"), 380);
    const t2 = setTimeout(() => line3Ref.current.classList.add("show"), 780);
    const t3 = setTimeout(() => {
      const flash = flashRef.current;
      flash.style.transition = "opacity 0.08s ease";
      flash.style.opacity = "0.9";
      const t4 = setTimeout(() => {
        flash.style.transition = "opacity 0.5s ease";
        flash.style.opacity = "0";
      }, 90);
      onDone();
      return () => clearTimeout(t4);
    }, 1450);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [onDone]);

  return (
    <>
      <div className="scene active" id="scene-transition">
        <div className="boot-line" id="bl1" ref={line1Ref}>
          ◈ VERIFYING CREDENTIALS
        </div>
        <div className="boot-line" id="bl2" ref={line2Ref}>
          ◈ SYNCING TRAINER RECORD
        </div>
        <div className="boot-line" id="bl3" ref={line3Ref}>
          ◈ WELCOME BACK
        </div>
        <div className="boot-bar-track">
          <div className="boot-bar-fill" ref={fillRef} />
        </div>
      </div>
      <div className="flash-white" ref={flashRef} />
    </>
  );
}

