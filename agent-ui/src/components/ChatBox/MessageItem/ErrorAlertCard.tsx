// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { Button } from '@/components/ui/button';
import {
  presentError,
  type ErrorTone,
  type PresentedError,
} from '@/lib/errorPresentation';
import { cn } from '@/lib/utils';
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  Info,
  RotateCcw,
  TriangleAlert,
  X,
} from 'lucide-react';
import { useCallback, useId, useMemo, useState, type ReactNode } from 'react';

const COPIED_RESET_MS = 2000;

const TONE_STYLES: Record<
  ErrorTone,
  {
    container: string;
    accent: string;
    tone: string;
    icon: typeof CircleAlert;
  }
> = {
  error: {
    container: 'bg-ds-bg-error-subtle-default',
    accent: 'bg-ds-bg-error-default-default',
    tone: 'text-ds-text-error-strong-default',
    icon: CircleAlert,
  },
  warning: {
    container: 'bg-ds-bg-warning-subtle-default',
    accent: 'bg-ds-bg-warning-default-default',
    tone: 'text-ds-text-warning-strong-default',
    icon: TriangleAlert,
  },
  information: {
    container: 'bg-ds-bg-information-subtle-default',
    accent: 'bg-ds-bg-information-default-default',
    tone: 'text-ds-text-information-strong-default',
    icon: Info,
  },
};

export interface ErrorAlertCardProps {
  /** Raw error text as it arrives in the transcript. */
  content?: string;
  /** Overrides derived from `content`, for callers that already classified it. */
  tone?: ErrorTone;
  title?: string;
  message?: string;
  hint?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  retryLabel?: string;
  dismissLabel?: string;
  /** Extra actions rendered after Retry / Dismiss (e.g. "Start new chat"). */
  actions?: ReactNode;
  defaultDetailsOpen?: boolean;
  hideDetails?: boolean;
  compact?: boolean;
  className?: string;
}

/**
 * Chat error surface: a readable headline and the provider's message up front,
 * with the raw payload folded into Details instead of dumped into the bubble.
 */
export function ErrorAlertCard({
  content,
  tone: toneProp,
  title: titleProp,
  message: messageProp,
  hint: hintProp,
  onRetry,
  onDismiss,
  retryLabel = 'Try again',
  dismissLabel = 'Dismiss',
  actions,
  defaultDetailsOpen = false,
  hideDetails = false,
  compact = false,
  className,
}: ErrorAlertCardProps) {
  const presented: PresentedError = useMemo(
    () => presentError(content),
    [content],
  );
  const detailsId = useId();
  const [detailsOpen, setDetailsOpen] = useState(defaultDetailsOpen);
  const [copied, setCopied] = useState(false);

  const tone = toneProp ?? presented.tone;
  const styles = TONE_STYLES[tone];
  const Icon = styles.icon;
  const showDetails = !hideDetails && Boolean(presented.details);

  const handleCopy = useCallback(async () => {
    if (!presented.details) return;
    try {
      await navigator.clipboard.writeText(presented.details);
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      // Clipboard can be unavailable in the embedded webview; the details
      // stay selectable, so there is nothing to recover from.
    }
  }, [presented.details]);

  return (
    <section
      data-tone={tone}
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn(
        'relative w-full overflow-hidden rounded-lg',
        compact ? 'py-2 pl-3 pr-3' : 'py-3 pl-4 pr-4',
        styles.container,
        className,
      )}
    >
      <span
        aria-hidden
        className={cn('absolute inset-y-0 left-0 w-1', styles.accent)}
      />
      <div className={cn('flex min-w-0 items-start', compact ? 'gap-2' : 'gap-3')}>
        <Icon
          className={cn('mt-0.5 size-4 shrink-0', styles.tone)}
          aria-hidden
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3
              className={cn(
                'my-0 text-sm font-semibold leading-normal',
                styles.tone,
              )}
            >
              {titleProp ?? presented.title}
            </h3>
            {presented.code && (
              <span className="font-mono text-xs leading-normal text-ds-text-neutral-muted-default">
                {presented.code}
              </span>
            )}
          </div>

          <p className="mb-0 mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-ds-text-neutral-default-default">
            {messageProp ?? presented.message}
          </p>

          {hintProp !== undefined
            ? hintProp && (
                <p className="mb-0 mt-1 text-sm leading-normal text-ds-text-neutral-muted-default">
                  {hintProp}
                </p>
              )
            : presented.hint && (
                <p className="mb-0 mt-1 text-sm leading-normal text-ds-text-neutral-muted-default">
                  {presented.hint}
                </p>
              )}

          {showDetails && (
            <div className="mt-3">
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  aria-expanded={detailsOpen}
                  aria-controls={detailsId}
                  onClick={() => setDetailsOpen((open) => !open)}
                  className="flex items-center gap-1 rounded-sm p-0 text-sm font-medium leading-normal text-ds-text-neutral-muted-default transition-colors hover:text-ds-text-neutral-default-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-ring-brand-default-focus/50"
                >
                  {detailsOpen ? 'Hide details' : 'Show details'}
                  <ChevronRight
                    className={cn(
                      'size-3.5 transition-transform duration-150',
                      detailsOpen && 'rotate-90',
                    )}
                    aria-hidden
                  />
                </button>
                {detailsOpen && (
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="flex items-center gap-1 rounded-sm p-0 text-sm font-medium leading-normal text-ds-text-neutral-muted-default transition-colors hover:text-ds-text-neutral-default-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-ring-brand-default-focus/50"
                  >
                    {copied ? (
                      <>
                        <Check className="size-3.5" aria-hidden />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy className="size-3.5" aria-hidden />
                        Copy
                      </>
                    )}
                  </button>
                )}
              </div>
              {detailsOpen && (
                <pre
                  id={detailsId}
                  className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-ds-bg-neutral-subtle-default p-2 font-mono text-sm leading-relaxed text-ds-text-neutral-muted-default"
                >
                  {presented.details}
                </pre>
              )}
            </div>
          )}

          {(onRetry || onDismiss || actions) && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {onRetry && (
                <Button size="xs" variant="secondary" onClick={onRetry}>
                  <RotateCcw aria-hidden />
                  {retryLabel}
                </Button>
              )}
              {onDismiss && (
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={onDismiss}
                  aria-label={dismissLabel}
                >
                  <X aria-hidden />
                  {dismissLabel}
                </Button>
              )}
              {actions}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
