// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { AgentMessageCard } from '@/components/ChatBox/MessageItem/AgentMessageCard';
import { ErrorAlertCard } from '@/components/ChatBox/MessageItem/ErrorAlertCard';
import { Button } from '@/components/ui/button';
import type { Meta, StoryObj } from '@storybook/react-vite';

/**
 * The chat's error surface. Today a failed turn writes `❌ **Error**: ...` into
 * the transcript, so the bubble shows the provider's raw payload (`Error code:
 * 400 - {'error': {...}}`) as a wall of text. `presentError` in
 * `@/lib/errorPresentation` pulls out the provider's message and code and
 * classifies the failure; this card renders the readable part up front and
 * folds the payload into Details.
 *
 * **Where it belongs.** `AgentMessageCard` swaps markdown for this card when
 * `isErrorContent(content)` is true, so every error path that already writes an
 * error message (model errors, SSE error payloads, parse failures) gets it with
 * no data migration. The stored content is untouched, so history and replay
 * keep working.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof ErrorAlertCard> = {
  title: 'ChatBox/ErrorAlertCard',
  component: ErrorAlertCard,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[calc(100vw-2rem)] max-w-[680px] bg-ds-bg-neutral-subtle-default p-6">
        <Story />
      </div>
    ),
  ],
  argTypes: {
    tone: {
      control: 'select',
      options: ['error', 'warning', 'information'],
    },
    defaultDetailsOpen: { control: 'boolean' },
    hideDetails: { control: 'boolean' },
    compact: { control: 'boolean' },
    title: { control: 'text' },
    hint: { control: 'text' },
  },
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof ErrorAlertCard>;

const LITELLM_400 = `❌ **Error**: litellm.BadRequestError: OpenAIException - Error code: 400 - {'error': {'message': "Invalid value for 'temperature': expected a number between 0 and 2, got 2.5. Fix the request before retrying.", 'type': 'invalid_request_error', 'param': 'temperature', 'code': None}}`;

const RATE_LIMIT_429 = `❌ **Error**: Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4o in organization org-9f2a on tokens per min (TPM): Limit 30000, Used 29875, Requested 900. Please try again in 1.55s.', 'type': 'tokens', 'param': None, 'code': 'rate_limit_exceeded'}}`;

const CONTEXT_400 = `❌ **Error**: litellm.BadRequestError: OpenAIException - Error code: 400 - {'error': {'message': "This model's maximum context length is 128000 tokens. However, your messages resulted in 141902 tokens. Please reduce the length of the messages.", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'context_length_exceeded'}}`;

const AUTH_401 = `❌ **Error**: Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-proj-***. You can find your API key at https://platform.openai.com/account/api-keys.', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}}`;

const CREDITS_402 = `❌ **Error**: litellm.BadRequestError: OpenAIException - Error code: 402 - {'error': {'message': 'Insufficient Balance. Your account has no credit left. Top up and retry.', 'type': 'insufficient_quota', 'code': 'insufficient_quota'}}`;

const NETWORK = `❌ **Error**: litellm.APIConnectionError: OpenAIException - Connection error. [Errno 61] Connection refused while reaching api.openai.com`;

const TIMEOUT = `❌ **Error**: litellm.Timeout: OpenAIException - Request timed out after 600.0 seconds.`;

const TOOL_FAILURE = `❌ **Error**: Tool execution failed: browser_navigate - {"error": "net::ERR_NAME_NOT_RESOLVED", "url": "https://example.invalid/report", "attempt": 2}`;

const BARE_JSON = `{"error": "not_found", "message": "No playback data found for this task."}`;

const PARSE_FAILURE = `**System Error**: Failed to parse server message. The connection may be unstable.\n\nPlease try again or contact support if this persists.`;

/** The complaint: a model error with the provider payload still in it. */
export const ProviderRejectedRequest: Story = {
  args: { content: LITELLM_400 },
};

/** Throttled, not broken: warning tone, and retry is the obvious action. */
export const RateLimited: Story = {
  args: {
    content: RATE_LIMIT_429,
    onRetry: () => {},
    onDismiss: () => {},
  },
};

/** The history outgrew the window, so retry would fail again: offer the exit. */
export const ContextWindowExceeded: Story = {
  args: {
    content: CONTEXT_400,
    onDismiss: () => {},
    actions: (
      <Button size="xs" variant="outline">
        Start new chat
      </Button>
    ),
  },
};

export const InvalidApiKey: Story = {
  args: {
    content: AUTH_401,
    onDismiss: () => {},
    actions: (
      <Button size="xs" variant="outline">
        Open settings
      </Button>
    ),
  },
};

export const OutOfCredits: Story = {
  args: { content: CREDITS_402, onRetry: () => {} },
};

export const NetworkUnreachable: Story = {
  args: { content: NETWORK, onRetry: () => {} },
};

export const RequestTimedOut: Story = {
  args: { content: TIMEOUT, onRetry: () => {}, defaultDetailsOpen: false },
};

/** Tool failures are the noisiest payloads; the card still leads with prose. */
export const ToolFailure: Story = {
  args: { content: TOOL_FAILURE, onRetry: () => {} },
};

/** A bare SSE payload, previously printed verbatim into the bubble. */
export const ReplayUnavailable: Story = {
  args: { content: BARE_JSON, defaultDetailsOpen: true },
};

export const ParseFailure: Story = {
  args: { content: PARSE_FAILURE, onRetry: () => {} },
};

/** Nothing readable in the payload at all: honest fallback, no invented cause. */
export const NoUsableMessage: Story = {
  args: { content: '❌ **Error**: {}' },
};

/** Folded payload, the default state: the answer stays the loudest thing. */
export const DetailsCollapsedDefault: Story = {
  args: { content: LITELLM_400, onRetry: () => {} },
};

export const Compact: Story = {
  args: { content: RATE_LIMIT_429, compact: true },
};

/** One per tone, for the palette check. */
export const AllTones: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <ErrorAlertCard content={AUTH_401} />
      <ErrorAlertCard content={RATE_LIMIT_429} />
      <ErrorAlertCard
        tone="information"
        title="Model switched"
        message="The previous model was unavailable, so this turn ran on gpt-4o-mini."
        hint="Switch back in the model picker if you need the larger model."
        content=""
      />
    </div>
  ),
};

/**
 * Retry as the app wires it: `AgentMessageCard` hands the handler to the card
 * only when resending could help, so the rate-limit error offers Try again and
 * the context overflow does not.
 */
export const InChatThreadWithRetry: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <AgentMessageCard
        id="retry-rate-limit"
        typewriter={false}
        content={RATE_LIMIT_429}
        onRetry={() => {}}
      />
      <AgentMessageCard
        id="retry-context"
        typewriter={false}
        content={CONTEXT_400}
        onRetry={() => {}}
      />
    </div>
  ),
};

/** In the real thread: the same raw content, rendered through AgentMessageCard. */
export const InChatThread: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <div className="max-w-[420px] rounded-2xl bg-ds-bg-brand-default-default px-4 py-2.5 text-sm text-ds-text-brand-inverse-default">
          Summarise the last quarter&apos;s pipeline and write it to report.md
        </div>
      </div>
      <AgentMessageCard
        id="reply-1"
        typewriter={false}
        content="I read the CRM export and drafted the summary. Writing it to `report.md` now."
      />
      <AgentMessageCard id="error-1" typewriter={false} content={LITELLM_400} />
      <AgentMessageCard
        id="error-2"
        typewriter={false}
        content={RATE_LIMIT_429}
      />
    </div>
  ),
};
