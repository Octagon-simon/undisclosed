// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";

import {
  FIRST_TOKEN_LABEL_SETS,
  FirstTokenMeter,
  type FirstTokenStage,
} from "@/components/ChatBox/MessageItem/FirstTokenMeter";

/**
 * The slot under the user's message, from Enter to the first token. One line of
 * type: the label, a separator, the elapsed clock.
 *
 * The row only states what the app can prove happened. The send is local, the
 * acceptance is stamped on SSE `onopen`, and the first token is the first
 * `reasoning` chunk (or the ack for models that answer without thinking). Those
 * are the only three moments available, which is why there is no bar: a bar
 * would be inventing a denominator, and two thirds of it would never move.
 *
 * **States**
 * - `sent`: the request is out, no server confirmation yet.
 * - `accepted`: the run exists on the server, the model is the one holding
 *   things up.
 * - `writing`: accepted, nothing streamed yet, one beat past acceptance. Same
 *   information as `accepted`, later wording: the real turn holds the accepted
 *   line for 1.2s (`ACCEPTED_BEAT_MS` in `UserQueryGroup`) and then says it
 *   plainly until the first token. Without it the row sat on one label and
 *   jumped straight to the overrun.
 * - past `typicalMs`: "Almost there" in the row's own ink. Ten seconds in is
 *   still inside a normal reasoning turn, so the row encourages rather than
 *   warns.
 * - past `stalledMs`: label and clock go amber and keep shimmering, now through
 *   a brighter amber. Nothing resets or re-announces the earlier stages.
 *
 * The motion is the clock climbing, a 160ms fade when the label changes, and a
 * 2px rise on mount. The live label is the shared `ShinyText` loader, at the
 * same 2.5s speed as the thinking header and the in-flight work steps, so the
 * wait looks like the rest of the app rather than a one-off. It keeps the row's
 * ink: the sweep is a transparent band through `currentColor`, not the loader's
 * grey, so the label stays as dark as the rest of the row. `ShinyText`'s own
 * stylesheet drops the animation under `prefers-reduced-motion`.
 */
const meta: Meta<typeof FirstTokenMeter> = {
  title: "ChatBox/FirstTokenMeter",
  component: FirstTokenMeter,
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="w-[460px] bg-ds-bg-neutral-muted-default p-6">
        <div className="rounded-xl border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-5 py-4">
          <Story />
        </div>
      </div>
    ),
  ],
  argTypes: {
    stage: {
      control: "inline-radio",
      options: ["sent", "accepted", "writing"] satisfies FirstTokenStage[],
    },
    elapsedMs: { control: { type: "range", min: 0, max: 20000, step: 100 } },
    typicalMs: { control: { type: "number" } },
  },
  args: {
    stage: "sent",
    elapsedMs: 400,
    typicalMs: 8000,
  },
  tags: ["autodocs"],
};

export default meta;

type Story = StoryObj<typeof FirstTokenMeter>;

/** A caption in a fixed gutter, so several rows line up while you compare them. */
function Row({
  caption,
  children,
}: {
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-x-4">
      <span className="text-label-xs uppercase tracking-wide text-ds-text-neutral-subtle-default">
        {caption}
      </span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** What occupies the slot after the handoff. Story-only stand-in. */
function AckLine() {
  return (
    <div className="text-body-sm text-ds-text-neutral-default-default">
      On it. Let me find where the retry budget is spent before I change
      anything.
    </div>
  );
}

/** One row, driven by the controls. */
export const Waiting: Story = {};

/** The five states the row can be in, at the app's typical of 8s. */
export const States: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <Row caption="sent">
        <FirstTokenMeter stage="sent" elapsedMs={400} typicalMs={8000} />
      </Row>
      <Row caption="accepted">
        <FirstTokenMeter stage="accepted" elapsedMs={1000} typicalMs={8000} />
      </Row>
      <Row caption="writing">
        <FirstTokenMeter stage="writing" elapsedMs={3200} typicalMs={8000} />
      </Row>
      <Row caption="almost">
        <FirstTokenMeter stage="writing" elapsedMs={9400} typicalMs={8000} />
      </Row>
      <Row caption="stalled">
        <FirstTokenMeter stage="writing" elapsedMs={24000} typicalMs={8000} />
      </Row>
    </div>
  ),
};

/** The label sets, so the voice can be picked without touching the component. */
const WORDING_STEPS: { stage: FirstTokenStage; elapsedMs: number }[] = [
  { stage: "sent", elapsedMs: 200 },
  { stage: "accepted", elapsedMs: 1100 },
  { stage: "writing", elapsedMs: 2900 },
  { stage: "writing", elapsedMs: 8400 },
];

export const Wording: Story = {
  render: () => (
    <div className="flex flex-col gap-6">
      {(["calm", "plain", "terse"] as const).map((set) => (
        <div key={set} className="flex flex-col gap-1">
          <div className="text-label-xs uppercase tracking-wide text-ds-text-neutral-subtle-default">
            {set}
            {set === "calm" ? " · shipping" : ""}
          </div>
          {WORDING_STEPS.map(({ stage, elapsedMs }) => (
            <FirstTokenMeter
              key={`${stage}-${elapsedMs}`}
              stage={stage}
              elapsedMs={elapsedMs}
              typicalMs={8000}
              labels={FIRST_TOKEN_LABEL_SETS[set]}
            />
          ))}
        </div>
      ))}
    </div>
  ),
};

/** The switch, with nothing else changing: last frame in, first frame out. */
export const Handoff: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <Row caption="t+4.3s">
        <FirstTokenMeter stage="writing" elapsedMs={4300} typicalMs={8000} />
      </Row>
      <Row caption="t+4.4s">
        <div className="min-w-0">
          <FirstTokenMeter
            stage="writing"
            elapsedMs={4400}
            typicalMs={8000}
            firstTokenMs={4400}
          />
          <AckLine />
        </div>
      </Row>
    </div>
  ),
};

/**
 * Real time, at the shipped cadence: acceptance at 0.8s, the accepted line held
 * for 1.2s, "Waiting for the first words" from 2s, first word at 4.3s, then the
 * ack takes over.
 */
export const Live: Story = {
  render: () => <LiveTurn />,
};

function LiveTurn() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const tick = setInterval(() => setElapsed(Date.now() - startedAt), 100);
    return () => clearInterval(tick);
  }, []);

  return (
    <div className="min-w-0">
      <FirstTokenMeter
        stage={
          elapsed < 800 ? "sent" : elapsed < 2000 ? "accepted" : "writing"
        }
        elapsedMs={elapsed}
        typicalMs={8000}
        firstTokenMs={elapsed >= 4300 ? 4300 : null}
      />
      {elapsed >= 4300 ? <AckLine /> : null}
    </div>
  );
}
