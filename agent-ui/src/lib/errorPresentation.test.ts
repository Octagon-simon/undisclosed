// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
  isErrorContent,
  isRetryableError,
  presentError,
} from '@/lib/errorPresentation';

const LITELLM_PY_DICT = `❌ **Error**: litellm.BadRequestError: OpenAIException - Error code: 400 - {'error': {'message': "Invalid value for 'temperature': expected a number between 0 and 2, got 2.5.", 'type': 'invalid_request_error', 'param': 'temperature', 'code': None}}`;

const RATE_LIMIT = `❌ **Error**: Error code: 429 - {"error": {"message": "Rate limit reached for gpt-4o on tokens per min (TPM): Limit 30000.", "type": "tokens", "code": "rate_limit_exceeded"}}`;

const CONTEXT = `❌ **Error**: litellm.BadRequestError: OpenAIException - Error code: 400 - {"error": {"message": "This model's maximum context length is 128000 tokens. However, your messages resulted in 141902 tokens.", "type": "invalid_request_error", "code": "context_length_exceeded"}}`;

const AUTH = `❌ **Error**: Error code: 401 - {"error": {"message": "Incorrect API key provided: sk-proj-***.", "type": "invalid_request_error", "code": "invalid_api_key"}}`;

describe('presentError', () => {
  it('lifts the provider message out of a Python dict repr', () => {
    const presented = presentError(LITELLM_PY_DICT);

    expect(presented.message).toBe(
      "Invalid value for 'temperature': expected a number between 0 and 2, got 2.5.",
    );
    expect(presented.message).not.toContain('{');
    expect(presented.code).toBe('HTTP 400');
    expect(presented.kind).toBe('validation');
    expect(presented.tone).toBe('error');
    expect(presented.details).toContain("'error'");
  });

  it('reads the code field from a parsed JSON payload', () => {
    const presented = presentError(RATE_LIMIT);

    expect(presented.kind).toBe('rate_limit');
    expect(presented.tone).toBe('warning');
    expect(presented.title).toBe('Rate limit reached');
    expect(presented.code).toBe('rate_limit_exceeded');
    expect(presented.message).toContain('Rate limit reached for gpt-4o');
    expect(presented.hint).toMatch(/wait a moment/i);
  });

  it('treats an over-long conversation as a context problem, not a bad request', () => {
    const presented = presentError(CONTEXT);

    expect(presented.kind).toBe('context');
    expect(presented.tone).toBe('warning');
    expect(presented.title).toBe('Context window exceeded');
    expect(presented.message).toContain('maximum context length');
  });

  it('recognises a rejected key', () => {
    const presented = presentError(AUTH);

    expect(presented.kind).toBe('auth');
    expect(presented.code).toBe('invalid_api_key');
    expect(presented.hint).toMatch(/settings/i);
  });

  it('handles a bare SSE error payload with no marker', () => {
    const presented = presentError(
      '{"error": "not_found", "message": "No playback data found for this task."}',
    );

    expect(presented.message).toBe('No playback data found for this task.');
    expect(presented.title).toBe('Nothing to replay');
    expect(presented.tone).toBe('information');
    expect(presented.details).toContain('"not_found"');
  });

  it('classifies a refused connection', () => {
    const presented = presentError(
      '❌ **Error**: litellm.APIConnectionError: OpenAIException - Connection error. [Errno 61] Connection refused',
    );

    expect(presented.kind).toBe('network');
    expect(presented.tone).toBe('warning');
    expect(presented.title).toBe('Connection failed');
  });

  it('classifies a dropped stream from a system error', () => {
    const presented = presentError(
      '**System Error**: Failed to parse server message. The connection may be unstable.',
    );

    expect(presented.kind).toBe('system');
    expect(presented.message).toContain('Failed to parse server message');
  });

  it('falls back honestly when there is nothing to read', () => {
    const presented = presentError('❌ **Error**: {}');

    expect(presented.title).toBe('The run failed');
    expect(presented.message).toBe('The run stopped before it could finish.');
    expect(presented.details).toBeUndefined();
  });

  it('never throws on an empty value', () => {
    expect(presentError('').message).toBe(
      'The run stopped before it could finish.',
    );
    expect(presentError(undefined).kind).toBe('unknown');
  });
});

describe('isErrorContent', () => {
  it('matches the markers the chat writes into the transcript', () => {
    expect(isErrorContent('❌ **Error**: boom')).toBe(true);
    expect(isErrorContent('**System Error**: stream dropped')).toBe(true);
    expect(isErrorContent('**Critical Error**: unexpected')).toBe(true);
  });

  it('matches a bare error payload', () => {
    expect(isErrorContent('{"error": "not_found"}')).toBe(true);
    expect(isErrorContent('{"detail": "Not Found"}')).toBe(true);
  });

  it('leaves normal answers, JSON answers, and prose alone', () => {
    expect(isErrorContent('The run finished and wrote report.md.')).toBe(false);
    expect(isErrorContent('{"rows": [1, 2, 3]}')).toBe(false);
    expect(isErrorContent('')).toBe(false);
    expect(isErrorContent(undefined)).toBe(false);
  });
});

describe('isRetryableError', () => {
  it('offers a retry for transient failures', () => {
    expect(isRetryableError(RATE_LIMIT)).toBe(true);
    expect(
      isRetryableError(
        '❌ **Error**: litellm.APIConnectionError: OpenAIException - Connection error. [Errno 61] Connection refused',
      ),
    ).toBe(true);
    expect(
      isRetryableError('❌ **Error**: Error code: 408 - the request timed out'),
    ).toBe(true);
  });

  it('withholds a retry when resending would fail the same way', () => {
    expect(isRetryableError(CONTEXT)).toBe(false);
    expect(isRetryableError(AUTH)).toBe(false);
    expect(isRetryableError(LITELLM_PY_DICT)).toBe(false);
  });

  it('is false for content that is not an error at all', () => {
    expect(isRetryableError('The run finished and wrote report.md.')).toBe(false);
    expect(isRetryableError(undefined)).toBe(false);
  });
});
