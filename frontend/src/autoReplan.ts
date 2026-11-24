// Once a plan is on screen, editing the trip replans by itself: a short pause
// lets a burst of edits (typing a date, stepping through walk limits) settle
// into one request.
export const AUTO_REPLAN_MS = 250;

export function debounced(run: () => void, ms = AUTO_REPLAN_MS) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    schedule() {
      clearTimeout(timer);
      timer = setTimeout(run, ms);
    },
    cancel() {
      clearTimeout(timer);
      timer = undefined;
    },
  };
}
