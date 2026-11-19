import { useEffect, useRef } from "react";
import { ArrowRight, Eye, Layers, ListChecks, X } from "lucide-react";

const SEEN_KEY = "bikeflow.onboarding.v1";

/** First visit only. Storage can be blocked (private windows), so never let it break the page. */
export function shouldShowOnboarding() {
  try {
    return localStorage.getItem(SEEN_KEY) !== "seen";
  } catch {
    return true;
  }
}

export function markOnboardingSeen() {
  try {
    localStorage.setItem(SEEN_KEY, "seen");
  } catch {
    /* storage unavailable: the guide simply shows again next time */
  }
}

const STEPS = [
  {
    icon: ListChecks,
    title: "Pick a demo story",
    text: "Real summer-2021 Chicago station data, replayed as it happened. Or set your own trip.",
  },
  {
    icon: Layers,
    title: "Read the forecast",
    text: "Bike and open-dock chances at the minute you arrive, plus a backup if a station is likely to run out.",
  },
  {
    icon: Eye,
    title: "Reveal what happened",
    text: "Check the plan against what the station actually had, and compare with a current-count app.",
  },
];

/**
 * A short three-step guide: what the app does differently and the fastest way
 * to see it (the "dock fills up" story).
 */
export default function Onboarding({
  replayReady,
  onStartStory,
  onClose,
}: {
  replayReady: boolean;
  onStartStory: () => void;
  onClose: () => void;
}) {
  const primary = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  // Focus once when opened (and again if the replay button appears after /health loads).
  useEffect(() => primary.current?.focus(), [replayReady]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="onboarding-backdrop" onClick={onClose}>
      <section
        className="onboarding"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="icon-btn onboarding-close"
          aria-label="Close guide"
          onClick={onClose}
        >
          <X size={16} />
        </button>
        <span className="eyebrow">HOW BIKEFLOW WORKS</span>
        <h2 id="onboarding-title">
          A bike when you get there.
          <br />A dock when you arrive.
        </h2>
        <p className="onboarding-intro">
          Other apps show how many bikes and docks a station has right now.
          BikeFlow forecasts what will be there when you arrive, and plans
          around stations likely to run out.
        </p>
        <ol className="onboarding-steps">
          {STEPS.map(({ icon: Icon, title, text }, i) => (
            <li key={title}>
              <span className="onboarding-num">{i + 1}</span>
              <div>
                <strong>
                  <Icon size={14} /> {title}
                </strong>
                <small>{text}</small>
              </div>
            </li>
          ))}
        </ol>
        <div className="onboarding-actions">
          {replayReady && (
            <button
              ref={primary}
              className="primary-btn"
              onClick={onStartStory}
            >
              Start with the "dock fills up" story <ArrowRight size={16} />
            </button>
          )}
          <button
            ref={replayReady ? undefined : primary}
            className="compare-btn"
            onClick={onClose}
          >
            Explore on my own
          </button>
        </div>
        <small className="onboarding-note">
          Reopen this guide any time from “How it works”.
        </small>
      </section>
    </div>
  );
}
