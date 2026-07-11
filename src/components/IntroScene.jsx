/*
  IntroScene
  -----------
  One-time lore screen shown after the boot transition, before Home.
  Ported verbatim from #scene-intro in the original index.html —
  same copy, same structure. Calls onEnter() when the player taps
  through to Home.
*/
import Snow from "./Snow";

export default function IntroScene({ onEnter }) {
  return (
    <div className="scene active" id="scene-intro">
      <Snow />
      <div className="intro-wordmark glitch-in">
        NIFL<span>HEIM</span>
      </div>
      <div className="intro-sub">Welcome to Niflheim</div>
      <div className="lore-panel glitch-in">
        <p>
          Niflheim is a realm carved from ice — <b>frost-bound towns</b>, wild
          frontier routes, and waters that never fully thaw. Trainers arrive
          at Oak Town with nothing but a starter and an objective, and build
          their name from there.
        </p>
        <p>
          Every battle, every catch, every badge earned carries you further
          from the lab and deeper into the frozen wild. <b>Gyms guard their
          routes.</b> Legends sleep beneath the ice. What you become is yours
          to decide.
        </p>
        <p>This is your status window now — <b>check it often.</b></p>
      </div>
      <button className="intro-enter-btn" onClick={onEnter}>
        Welcome to Niflheim
      </button>
    </div>
  );
}
