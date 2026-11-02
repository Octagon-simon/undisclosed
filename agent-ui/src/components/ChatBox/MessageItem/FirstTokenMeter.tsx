// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import ShinyText from "@/components/ui/ShinyText/ShinyText";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import { useTranslation } from "react-i18next";

/**
 * The wait between Enter and the first token, as one line of type: the label
 * saying where the turn is, and the elapsed clock.
 *
 * There is no bar and no dot. The app can observe two events (the send, and the
 * server accepting the run), so a multi-segment meter was drawing a third of
 * its meaning out of nothing, and a ring-plus-dot read as a radio button.
 *
 * A still indicator reads as a stuck one (HIG progress indicators, and NN/g on
 * static indicators), so the label runs on the shared `ShinyText` loader, the
 * same one the thinking header and in-flight work steps use. The clock is the
 * authoritative liveness signal: if the app wedges, the digits stop. Nothing
 * about the motion implies quantity. It renders nothing once the first token
 * lands.
 */

/** The three events between Enter and the first token. */
export type FirstTokenStage = "sent" | "accepted" | "writing";

export interface FirstTokenLabels {
  sent: string;
  accepted: string;
  writing: string;
  almost: string;
  slow: string;
}

/** Label sets reviewed in Storybook. `calm` is what ships. */
export const FIRST_TOKEN_LABEL_SETS = {
  calm: {
    sent: "Request sent",
    accepted: "Agent is on it",
    writing: "Waiting for the first words",
    almost: "Almost there",
    slow: "Taking longer than usual",
  },
  plain: {
    sent: "Request sent",
    accepted: "Run accepted",
    writing: "Awaiting first token",
    almost: "Nearly there",
    slow: "Taking longer than usual",
  },
  terse: {
    sent: "Sent",
    accepted: "Accepted",
    writing: "Starting up",
    almost: "Almost",
    slow: "Taking a while",
  },
} satisfies Record<string, FirstTokenLabels>;

function clock(ms: number) {
  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
}

export interface FirstTokenMeterProps {
  stage: FirstTokenStage;
  /** Milliseconds since the user pressed send. */
  elapsedMs: number;
  /** Past this, the row encourages instead of restating the stage. */
  typicalMs?: number;
  /** Past this, the row stops encouraging and states the wait as amber. */
  stalledMs?: number;
  /**
   * Set when the first token lands (the first `reasoning` chunk, or the ack
   * for models that answer without thinking). The row then renders nothing.
   */
  firstTokenMs?: number | null;
  labels?: Partial<FirstTokenLabels>;
  className?: string;
}

export function FirstTokenMeter({
  stage,
  elapsedMs,
  typicalMs = 3000,
  stalledMs = 20000,
  firstTokenMs,
  labels,
  className,
}: FirstTokenMeterProps) {
  const { t } = useTranslation();
  const reduceMotion = useReducedMotion();
  const text: FirstTokenLabels = {
    sent:
      labels?.sent ??
      t("chat.first-token-sent", { defaultValue: FIRST_TOKEN_LABEL_SETS.calm.sent }),
    accepted:
      labels?.accepted ??
      t("chat.first-token-accepted", {
        defaultValue: FIRST_TOKEN_LABEL_SETS.calm.accepted,
      }),
    writing:
      labels?.writing ??
      t("chat.first-token-writing", {
        defaultValue: FIRST_TOKEN_LABEL_SETS.calm.writing,
      }),
    almost:
      labels?.almost ??
      t("chat.first-token-almost", {
        defaultValue: FIRST_TOKEN_LABEL_SETS.calm.almost,
      }),
    slow:
      labels?.slow ??
      t("chat.first-token-slow", { defaultValue: FIRST_TOKEN_LABEL_SETS.calm.slow }),
  };

  // First token: hand the slot over instead of staying in it.
  if (typeof firstTokenMs === "number") return null;

  const overrun = elapsedMs > typicalMs;
  const stalled = elapsedMs > stalledMs;
  const label = stalled ? text.slow : overrun ? text.almost : text[stage];

  return (
    <motion.div
      className={cn("flex h-8 min-w-0 items-center text-body-sm", className)}
      initial={reduceMotion ? false : { opacity: 0, y: 2 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
    >
      {/* Announce the label only. The clock ticks four times a second, so a live
          region around the whole row would read the wait out loud. */}
      <span className="sr-only" role="status" aria-live="polite">
        {label}
      </span>

      {/* One inline line of type, so the smaller clock sits on the same
          baseline as the label without any box alignment to get wrong. */}
      <div aria-hidden className="min-w-0 truncate">
        <motion.div
          key={label}
          className={cn(
            "inline-block",
            stalled && "text-ds-text-warning-default-default",
          )}
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
        >
          {/* The sweep is a transparent band through the row's own ink, so the
              label keeps its colour. Stalled turns repaint the ink amber and
              sweep a brighter amber through it. */}
          <ShinyText
            text={label}
            speed={2.5}
            color="currentColor"
            shineColor={stalled ? "var(--colors-yellow-200)" : "transparent"}
            className="!font-normal"
          />
        </motion.div>
        <span className="mx-1.5 text-ds-text-neutral-subtle-default">·</span>
        <span
          className={cn(
            "font-mono text-label-xs transition-colors duration-500",
            stalled
              ? "text-ds-text-warning-default-default"
              : "text-ds-text-neutral-subtle-default",
          )}
        >
          <span className="tabular-nums">{clock(elapsedMs)}</span>
        </span>
      </div>
    </motion.div>
  );
}
