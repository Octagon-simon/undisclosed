// Copyright 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Undisclosed logomark: three redaction bars ("blacked-out" lines of text).
 * Inlined rather than an <img> so it inherits `currentColor` and still renders
 * under the agent-embed CSP, which blocks external assets.
 */
export function UndisclosedMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} fill="none" aria-hidden>
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

/** Mark plus the Undisclosed wordmark, for sidebars and footers. */
export function UndisclosedWordmark({ className }: { className?: string }) {
  return (
    <span
      className={['flex items-center gap-2', className]
        .filter(Boolean)
        .join(' ')}
    >
      <UndisclosedMark className="h-6 w-6 shrink-0" />
      <span className="text-heading-sm font-bold">Undisclosed</span>
    </span>
  );
}
