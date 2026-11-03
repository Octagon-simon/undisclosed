// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

export type ErrorKind =
  | 'auth'
  | 'credits'
  | 'rate_limit'
  | 'context'
  | 'network'
  | 'system'
  | 'timeout'
  | 'tool'
  | 'provider'
  | 'not_found'
  | 'validation'
  | 'unknown';

export type ErrorTone = 'error' | 'warning' | 'information';

export interface PresentedError {
  kind: ErrorKind;
  tone: ErrorTone;
  /** Short, human headline ("Rate limit reached"). */
  title: string;
  /** What actually happened, readable prose instead of a payload dump. */
  message: string;
  /** One actionable next step, when there is an obvious one. */
  hint?: string;
  /** HTTP status or provider code shown as a chip (`429`, `rate_limit_exceeded`). */
  code?: string;
  /** Provider error type (`invalid_request_error`), kept for the details header. */
  type?: string;
  /** Pretty raw payload for the disclosure. Absent when it adds nothing. */
  details?: string;
  raw: string;
}

const ERROR_MARKER =
  /^\s*(?:❌\s*)?\*{0,2}(?:system\s+|critical\s+)?error\*{0,2}\s*[:：]\s*/i;

const MAX_PAYLOAD_CHARS = 8000;

/** Matches agent message content that should render as an error card. */
export function isErrorContent(content: string | undefined): boolean {
  if (!content) return false;
  const text = content.trim();
  if (!text) return false;
  if (ERROR_MARKER.test(text) || /^❌/.test(text)) return true;
  // A bare payload (`{"error": ...}` from the SSE error path) leaks the same
  // JSON into the chat, so treat it as an error too.
  if (text.startsWith('{') && text.endsWith('}')) {
    try {
      const parsed: unknown = JSON.parse(text);
      return isRecord(parsed) && ('error' in parsed || 'detail' in parsed);
    } catch {
      return false;
    }
  }
  return false;
}

function unescapeQuoted(value: string): string {
  return value
    .replace(/\\(['"\\])/g, '$1')
    .replace(/\\n/g, ' ')
    .replace(/\\r/g, ' ');
}

/** Reads `"key": "value"` from JSON or a Python dict repr (`'key': 'value'`). */
function quotedField(text: string, key: string): string | undefined {
  const pattern = new RegExp(
    `['"]${key}['"]\\s*:\\s*(['"])((?:\\\\.|(?!\\1).)*)\\1`,
    'i',
  );
  const match = text.match(pattern);
  if (!match) return undefined;
  const value = unescapeQuoted(match[2]).trim();
  return value || undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function messageFromValue(value: unknown, depth = 0): string | undefined {
  if (depth > 4) return undefined;
  if (typeof value === 'string') {
    const text = value.trim();
    return text || undefined;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = messageFromValue(item, depth + 1);
      if (found) return found;
    }
    return undefined;
  }
  if (!isRecord(value)) return undefined;
  for (const key of [
    'message',
    'msg',
    'detail',
    'error',
    'reason',
    'description',
  ]) {
    const found = messageFromValue(value[key], depth + 1);
    if (found) return found;
  }
  return undefined;
}

function recordField(value: unknown, ...path: string[]): string | undefined {
  let current: unknown = value;
  for (const key of path) {
    if (!isRecord(current)) return undefined;
    current = current[key];
  }
  if (typeof current === 'string' || typeof current === 'number') {
    const text = String(current).trim();
    return text || undefined;
  }
  return undefined;
}

/** Removes litellm/SDK framing that leaks into `str(exc)`. */
function stripFraming(text: string): string {
  let out = text.trim();
  for (let i = 0; i < 3; i += 1) {
    const before = out;
    out = out
      .replace(/^litellm\.[\w.]+(?:Error|Exception)\s*:\s*/i, '')
      .replace(/^[\w.]+(?:Error|Exception)\s+-\s*/i, '')
      .replace(/^Error code:\s*\d{3}\s*-\s*/i, '')
      .replace(/^status code:\s*\d{3}\s*-\s*/i, '')
      .replace(/^HTTP\s*\d{3}\s*[:-]\s*/i, '')
      .trim();
    if (before === out) break;
  }
  return out;
}

function tidyProse(text: string): string {
  return text
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.;:])/g, '$1')
    .replace(/^[-–—:,\s]+/, '')
    .trim();
}

interface Payload {
  text: string;
  value: unknown;
}

function findPayload(text: string): Payload | undefined {
  const first = text.indexOf('{');
  const last = text.lastIndexOf('}');
  if (first < 0 || last <= first) return undefined;
  const slice = text.slice(first, last + 1);
  if (slice.length > MAX_PAYLOAD_CHARS) return undefined;
  try {
    return { text: slice, value: JSON.parse(slice) };
  } catch {
    // Python dict repr from litellm: unparseable as JSON, but the quoted
    // fields are still readable through `quotedField`.
    return { text: slice, value: undefined };
  }
}

function numericStatus(text: string): string | undefined {
  const explicit = text.match(/\b(?:error|status)\s*code\s*[:=]\s*(\d{3})\b/i);
  if (explicit) return explicit[1];
  const http = text.match(/\bHTTP\s*(\d{3})\b/i);
  if (http) return http[1];
  const bare = text.match(/\b(4\d{2}|5\d{2})\b/);
  if (bare) return bare[1];
  return undefined;
}

interface Classification {
  kind: ErrorKind;
  tone: ErrorTone;
  title: string;
  hint?: string;
}

function classify(input: {
  code?: string;
  type?: string;
  message: string;
  reason?: string;
  raw: string;
}): Classification {
  const haystack = `${input.message} ${input.type ?? ''} ${input.code ?? ''}`;
  const code =
    input.code && /^\d{3}$/.test(input.code) ? input.code : undefined;

  if (
    /not[_ ]?found|no playback|playback data|unavailable for this task/i.test(
      input.reason ?? '',
    )
  ) {
    return {
      kind: 'not_found',
      tone: 'information',
      title: 'Nothing to replay',
      hint: 'This conversation has no saved turns to play back.',
    };
  }

  if (
    /context[_ ]?(length|window)|maximum context|too many tokens|token limit|reduce the length|truncat/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'context',
      tone: 'warning',
      title: 'Context window exceeded',
      hint: 'Start a new chat or generate a handoff to keep working with a smaller history.',
    };
  }

  if (
    code === '429' ||
    /rate[_ ]?limit|too many requests|tokens per min|requests per min|quota exceeded|overloaded/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'rate_limit',
      tone: 'warning',
      title: 'Rate limit reached',
      hint: 'The provider is throttling requests. Wait a moment, then run it again.',
    };
  }

  if (
    code === '402' ||
    /insufficient (balance|credit|quota|funds)|payment required|billing|out of credit|no credit/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'credits',
      tone: 'error',
      title: 'Out of credits',
      hint: 'Add credit to the provider account, then run it again.',
    };
  }

  if (
    code === '401' ||
    code === '403' ||
    /invalid (api|x-api|access)[ _-]?key|incorrect api key|unauthori[sz]ed|forbidden|authentication|not authorized/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'auth',
      tone: 'error',
      title: 'Authentication failed',
      hint: "The provider rejected the key. Check the model's API key in Settings.",
    };
  }

  if (
    /failed to parse (the )?(server|sse)|stream (was )?(interrupted|closed)|connection may be unstable/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'system',
      tone: 'error',
      title: 'Connection interrupted',
      hint: 'The answer stream dropped mid-flight. Send the message again.',
    };
  }

  if (
    /ECONNREFUSED|ENOTFOUND|ECONNRESET|EHOSTUNREACH|fetch failed|network|socket hang up|connection (error|refused|reset)|getaddrinfo/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'network',
      tone: 'warning',
      title: 'Connection failed',
      hint: 'The request never reached the provider. Check the network, then retry.',
    };
  }

  if (
    code === '408' ||
    code === '504' ||
    /timeout|timed out|ETIMEDOUT|deadline exceeded|took too long/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'timeout',
      tone: 'warning',
      title: 'Request timed out',
      hint: 'The provider took too long to answer. Run it again.',
    };
  }

  if (
    code === '404' ||
    /not found|no such model|does not exist/i.test(haystack)
  ) {
    return {
      kind: 'not_found',
      tone: 'error',
      title: 'Model or endpoint not found',
      hint: 'Check the selected model and base URL for this provider.',
    };
  }

  if (
    /tool (call|step|execution)?\s*(failed|error)|tool_call|function call/i.test(
      haystack,
    )
  ) {
    return {
      kind: 'tool',
      tone: 'error',
      title: 'A tool step failed',
      hint: 'The run stopped on a tool call. The raw error is under Details.',
    };
  }

  if (code && code.startsWith('5')) {
    return {
      kind: 'provider',
      tone: 'error',
      title: 'Provider error',
      hint: 'The provider failed on its side. Try again in a moment.',
    };
  }

  if (
    code === '400' ||
    code === '422' ||
    /validation|invalid (request|parameter|value)|bad request/i.test(haystack)
  ) {
    return {
      kind: 'validation',
      tone: 'error',
      title: 'Request rejected',
      hint: 'The provider refused this request. Details below show its reason.',
    };
  }

  return {
    kind: 'unknown',
    tone: 'error',
    title: 'The run failed',
  };
}

const NON_RETRYABLE_KINDS: ReadonlySet<ErrorKind> = new Set<ErrorKind>([
  'auth',
  'credits',
  'context',
  'not_found',
  'validation',
]);

/**
 * Whether resending the same prompt could plausibly succeed. Auth, credits,
 * context-window and validation failures repeat verbatim, so no Retry button.
 */
export function isRetryableError(input: string | undefined | null): boolean {
  if (!isErrorContent(input ?? undefined)) return false;
  return !NON_RETRYABLE_KINDS.has(presentError(input).kind);
}

/**
 * Turns the raw error text the agent streams into chat into something a person
 * can read: a headline, the provider's own message, and the payload folded
 * away under Details.
 */
export function presentError(input: string | undefined | null): PresentedError {
  const raw = (input ?? '').trim();
  if (!raw) {
    return {
      kind: 'unknown',
      tone: 'error',
      title: 'The run failed',
      message: 'The run stopped before it could finish.',
      raw,
    };
  }

  const body = stripFraming(raw.replace(ERROR_MARKER, ''));
  const payload = findPayload(body);
  const payloadObject = payload?.value;

  const providerMessage = payload
    ? stripFraming(
        quotedField(payload.text, 'message') ??
          messageFromValue(payloadObject) ??
          '',
      )
    : undefined;

  const prose = tidyProse(
    body.slice(0, payload ? body.indexOf(payload.text) : undefined),
  );

  const detailsRaw = payload ? payload.text.trim() : '';
  const prettyDetails =
    payload && payloadObject !== undefined
      ? JSON.stringify(payloadObject, null, 2)
      : detailsRaw;

  const message =
    tidyProse(providerMessage || '') ||
    tidyProse(stripFraming(prose)) ||
    'The run stopped before it could finish.';

  const type =
    recordField(payloadObject, 'error', 'type') ??
    recordField(payloadObject, 'type');
  const payloadCode =
    recordField(payloadObject, 'error', 'code') ??
    recordField(payloadObject, 'code');
  const status = numericStatus(raw) ?? numericStatus(body);
  const code = payloadCode ?? (status ? `HTTP ${status}` : undefined);

  const reason =
    recordField(payloadObject, 'error') ?? recordField(payloadObject, 'detail');

  const classification = classify({
    code,
    type,
    message,
    reason,
    raw,
  });

  const detailsText = prettyDetails.trim();
  const details =
    detailsText &&
    detailsText !== '{}' &&
    detailsText !== '[]' &&
    detailsText !== message
      ? detailsText
      : undefined;

  return {
    kind: classification.kind,
    tone: classification.tone,
    title: classification.title,
    message,
    hint: classification.hint,
    code,
    type,
    details,
    raw,
  };
}
