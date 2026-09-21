import { useEffect, useState } from "react";

/**
 * Delayed-unmount presence for smooth opacity fade in/out.
 *
 * Fade-IN is painted by the `eez-fade-in` entrance keyframe animation (see
 * index.css), which runs 0 → 1 from the element's very first frame however
 * React batches the mount commit — so `shown` flips in the SAME commit as
 * `present` with zero timing race (no rAF/timeout chaining: on a loaded
 * renderer those can coalesce with the mount and pop in with no animation).
 * Fade-OUT flips `shown` (the opacity transition interpolates 1 → 0 on the
 * long-painted element) but keeps `present` true for `ms` so the fade
 * completes before unmount.
 *
 * SSR/first-render: state initializes from `visible`, so server-rendered
 * output shows the settled state (no hydration flash).
 */
export function useFadePresence(
  visible: boolean,
  ms = 300
): { present: boolean; shown: boolean } {
  const [present, setPresent] = useState(visible);
  const [shown, setShown] = useState(visible);
  useEffect(() => {
    if (visible) {
      setPresent(true);
      setShown(true);
      return;
    }
    setShown(false);
    const t = setTimeout(() => setPresent(false), ms);
    return () => clearTimeout(t);
  }, [visible, ms]);
  return { present, shown };
}

export default useFadePresence;
