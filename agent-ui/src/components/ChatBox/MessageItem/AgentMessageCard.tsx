// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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

import { fileInfoFromPath } from '@/lib/fileInfo';
import { usePageTabStore } from '@/store/pageTabStore';
import { useFeedbackStore } from '@/store/feedbackStore';
import { useHost } from '@/host';
import { Check, Copy, FileText, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '../../ui/button';
import { MarkDown } from './MarkDown';
import { StatusDot } from './PanelSection';

const COPIED_RESET_MS = 2000;

interface AgentMessageCardProps {
  id: string;
  content: string;
  className?: string;
  typewriter?: boolean;
  attaches?: File[];
  /** Shown only after markdown (and typewriter, if enabled) has finished rendering — e.g. generated file chips. */
  deferredFooter?: ReactNode;
  onTyping?: () => void;
  onMarkdownRenderComplete?: () => void;
  hideFeedbackAndCopyBtn?: boolean; //hide the feedback (thumb up/thumb down and copy btn from being actioned)
  /** Render the inline cyan response-indicator dot to the left of the body
   *  (reference design Section 3). Opt-in so only the actual agent reply is
   *  prefixed, not notices/approval cards. */
  indicator?: boolean;
}

// Tracks agent messages that have already played the typewriter (by stable message id).
const completedTypewriterByMessageId = new Map<string, boolean>();

export function AgentMessageCard({
  id,
  content,
  typewriter = true,
  onTyping,
  onMarkdownRenderComplete,
  className,
  attaches,
  deferredFooter,
  hideFeedbackAndCopyBtn,
  indicator,
}: AgentMessageCardProps) {
  const openFilePreview = usePageTabStore((s) => s.openFilePreview);
  const host = useHost();
  const [markdownAndTypingComplete, setMarkdownAndTypingComplete] = useState(
    () => completedTypewriterByMessageId.has(id)
  );

  useEffect(() => {
    setMarkdownAndTypingComplete(completedTypewriterByMessageId.has(id));
  }, [id]);

  const isCompleted = completedTypewriterByMessageId.has(id);
  const enableTypewriter = !isCompleted;

  const [copied, setCopied] = useState(false);
  // Feedback is persisted (local brain) and keyed by message id, so it survives
  // reloads and stays in sync with the Stats panel tally. Subscribe to just this
  // message's rating.
  const feedback = useFeedbackStore((s) => s.map[id]?.rating ?? null);
  const setRating = useFeedbackStore((s) => s.setRating);
  const { t } = useTranslation();

  // Hydrate the map once (guarded inside the store) so a reloaded conversation
  // shows the thumbs the user already gave.
  useEffect(() => {
    void useFeedbackStore.getState().hydrate();
  }, []);

  const handleTypingComplete = () => {
    if (!completedTypewriterByMessageId.has(id)) {
      completedTypewriterByMessageId.set(id, true);
    }
    if (onTyping) {
      onTyping();
    }
  };

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      toast.success(t('setting.copied-to-clipboard'));
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  }, [content, t]);

  const handleMarkdownRenderComplete = useCallback(() => {
    setMarkdownAndTypingComplete(true);
    onMarkdownRenderComplete?.();
  }, [onMarkdownRenderComplete]);

  const handleThumbUp = useCallback(() => {
    const adding = feedback !== 'up'; // toggling the active thumb clears it
    void setRating(id, 'up');
    if (adding) toast.success('Thanks for your feedback');
  }, [feedback, id, setRating]);

  const handleThumbDown = useCallback(() => {
    const adding = feedback !== 'down';
    void setRating(id, 'down');
    if (adding) toast.success('Thanks for your feedback');
  }, [feedback, id, setRating]);

  const showDeferredFileUi =
    markdownAndTypingComplete &&
    ((attaches && attaches.length > 0) || deferredFooter != null);

  return (
    <div
      key={id}
      className={`rounded-xl py-3 flex w-full flex-col bg-transparent ${className || ''} overflow-hidden`}
    >
      {indicator ? (
        <div className="flex w-full items-start gap-2">
          <StatusDot className="mt-[6px] bg-ds-bg-information-default-default" />
          <div className="min-w-0 flex-1">
            <MarkDown
              content={content}
              onTyping={handleTypingComplete}
              onMarkdownRenderComplete={handleMarkdownRenderComplete}
              enableTypewriter={enableTypewriter && typewriter}
            />
          </div>
        </div>
      ) : (
        <MarkDown
          content={content}
          onTyping={handleTypingComplete}
          onMarkdownRenderComplete={handleMarkdownRenderComplete}
          enableTypewriter={enableTypewriter && typewriter}
        />
      )}
      {showDeferredFileUi && attaches && attaches.length > 0 && (
        <div className="gap-2 mt-[10px] flex flex-wrap">
          {attaches?.map((file) => {
            return (
              <div
                onClick={(e) => {
                  e.stopPropagation();
                  // In the Theia embed, open the file in the editor via the
                  // host bridge; only fall back to the desktop page-tab preview
                  // when there is no host. Previously this used openFilePreview
                  // unconditionally, so clicking an agent file chip did nothing
                  // in the editor build.
                  if (host?.openFile && file.filePath) {
                    void host.openFile(file.filePath);
                  } else {
                    openFilePreview(
                      fileInfoFromPath(file.filePath, file.fileName)
                    );
                  }
                }}
                key={'attache-' + file.fileName}
                className="gap-2 rounded-2xl border-ds-border-neutral-subtle-default bg-ds-bg-neutral-default-default py-1 pl-2 flex w-full cursor-pointer items-center border border-solid"
              >
                <FileText size={24} className="flex-shrink-0" />
                <div className="flex flex-col">
                  <div className="text-body max-w-48 text-sm font-bold text-ds-text-neutral-default-default overflow-hidden text-ellipsis whitespace-nowrap">
                    {file?.fileName?.split('.')[0]}
                  </div>
                  <div className="text-xs font-medium leading-29 text-ds-text-neutral-default-default">
                    {file?.fileName?.split('.')[1]}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {showDeferredFileUi && deferredFooter != null && (
        <div className="mt-[10px] w-full">{deferredFooter}</div>
      )}
      {markdownAndTypingComplete && !hideFeedbackAndCopyBtn && (
        <div className="mt-3 gap-1 flex shrink-0 justify-start">
          <Button
            onClick={handleCopy}
            variant="ghost"
            size="xs"
            buttonContent="icon-only"
            aria-label={t('setting.copy')}
          >
            {copied ? (
              <Check className="h-4 w-4 text-ds-text-success-default-default" />
            ) : (
              <Copy className="h-4 w-4" />
            )}
          </Button>
          <Button
            onClick={handleThumbUp}
            variant="ghost"
            size="xs"
            buttonContent="icon-only"
            aria-label={feedback === 'up' ? 'Rated helpful — click to remove' : 'Thumb up'}
            aria-pressed={feedback === 'up'}
            title={feedback === 'up' ? 'Rated helpful — click to remove' : 'Good response'}
          >
            <ThumbsUp
              className={`h-4 w-4 ${feedback === 'up' ? 'text-ds-text-success-default-default' : ''}`}
              // Fill the icon while rated so it reads as SOLID (rated) vs the
              // hollow default — the affordance that this answer is rated and a
              // re-click clears it.
              fill={feedback === 'up' ? 'currentColor' : 'none'}
            />
          </Button>
          <Button
            onClick={handleThumbDown}
            variant="ghost"
            size="xs"
            buttonContent="icon-only"
            aria-label={feedback === 'down' ? 'Rated not helpful — click to remove' : 'Thumb down'}
            aria-pressed={feedback === 'down'}
            title={feedback === 'down' ? 'Rated not helpful — click to remove' : 'Bad response'}
          >
            <ThumbsDown
              className={`h-4 w-4 ${feedback === 'down' ? 'text-ds-text-error-default-default' : ''}`}
              fill={feedback === 'down' ? 'currentColor' : 'none'}
            />
          </Button>
        </div>
      )}
    </div>
  );
}
