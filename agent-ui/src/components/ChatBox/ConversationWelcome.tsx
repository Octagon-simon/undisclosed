// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

/**
 * First-launch / empty-conversation welcome shown above the composer when a
 * conversation has no messages yet — a friendly greeting plus a few starter
 * prompts. Clicking a prompt prefills the composer (via `onPick`) so the user
 * can tweak and send. Replaces the previous blank panel.
 */

import { useTranslation } from 'react-i18next';

/**
 * Undisclosed logomark: three redaction bars ("blacked-out" lines of text) — the
 * brand metaphor for private / on-device / undisclosed work. Inlined (not an
 * <img>) so it renders under the agent-embed CSP, which blocks external assets.
 */
function UndisclosedMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      className={className}
      fill="none"
      aria-hidden
      style={{ color: '#8b5cf6' }}
    >
      <rect x="7" y="13" width="34" height="6.4" rx="3.2" fill="currentColor" />
      <rect
        x="7"
        y="24"
        width="25"
        height="6.4"
        rx="3.2"
        fill="currentColor"
        opacity="0.82"
      />
      <rect
        x="7"
        y="35"
        width="16"
        height="6.4"
        rx="3.2"
        fill="currentColor"
        opacity="0.64"
      />
    </svg>
  );
}

const SUGGESTIONS = [
  'Explain what this project does',
  'Review the code in this workspace',
  'Help me find and fix a bug',
  "Summarize this project's structure",
];

export function ConversationWelcome({
  onPick,
}: {
  /** Prefill the composer with a starter prompt. */
  onPick: (text: string) => void;
}) {
  const { t } = useTranslation();
  return (
    // Left-anchored (items-start + text-left) so the horizontal padding reads as
    // a real gutter from the panel border. A centered layout swallows the padding
    // into whitespace, making it look like no padding was applied at all.
    <div className="flex flex-1 flex-col items-start justify-center gap-4 px-5 py-8 text-left">
      {/* Explicit colors: the ds brand tokens are UNMAPPED in the embed theme,
          so the badge bg/icon resolved to nothing and the logo vanished in dark
          mode. Pin a translucent brand fill + a vivid icon that read on both. */}
      <span
        className="flex h-11 w-11 items-center justify-center rounded-2xl"
        style={{ backgroundColor: 'rgba(124,58,237,0.16)' }}
      >
        <UndisclosedMark className="h-6 w-6" />
      </span>
      <div className="flex flex-col gap-1">
        <div className="text-heading-h5 font-bold text-ds-text-neutral-default-default">
          {t('chat.welcome-title', { defaultValue: 'Welcome to Undisclosed' })}
        </div>
        <div className="max-w-[440px] text-body-sm leading-relaxed text-ds-text-neutral-subtle-default">
          {t('chat.welcome-sub', {
            defaultValue:
              "I'm your coding agent inside this project. Ask me to explore the codebase, explain it, debug, or ship changes right here.",
          })}
        </div>
      </div>
      <div className="flex w-full flex-col gap-2">
        <div className="text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
          {t('chat.welcome-suggest', { defaultValue: 'Try one of these' })}
        </div>
        <div className="flex flex-col items-start gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              // w-fit: the pill (and its hover fill) sizes to its label, so the
              // hover no longer stretches edge-to-edge across the panel.
              // Explicit list-hoverBackground: the ds-*-hover tokens map to
              // Theia's menu-selectionBackground (an accent — red in some
              // themes); use the neutral list hover instead.
              className="w-fit max-w-full rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3.5 py-2 text-left text-label-sm text-ds-text-neutral-default-default outline-none transition-colors hover:bg-[var(--theia-list-hoverBackground)]"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
