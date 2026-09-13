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

/**
 * Single source of truth for provider ids, labels and local/cloud classification.
 *
 * `id` is the backend `provider_name`, which is also the `model_platform` sent
 * to the brain and resolved by CAMEL (`ModelPlatformType`). Keeping these ids
 * in one place stops the chatbox picker and the models screen from drifting:
 * the models screen used to write `qwen` / `openai-compatible`, while the
 * chatbox catalog (and CAMEL) expect `tongyi-qianwen` / `openai-compatible-model`,
 * so models added there never showed up as selectable.
 */

export type ProviderKind = 'cloud' | 'local';

export interface ProviderPreset {
  /** Backend `provider_name` == CAMEL `model_platform` id. */
  id: string;
  label: string;
  modelHint: string;
  kind: ProviderKind;
  /** Requires a user-supplied base URL. */
  needsUrl?: boolean;
  /** Default endpoint prefilled for local runtimes. */
  defaultEndpoint?: string;
}

export const CLOUD_PROVIDER_PRESETS: ProviderPreset[] = [
  { id: 'openai', label: 'OpenAI', modelHint: 'gpt-4o', kind: 'cloud' },
  {
    id: 'anthropic',
    label: 'Anthropic',
    modelHint: 'claude-sonnet-5',
    kind: 'cloud',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    modelHint: 'gemini-3-pro-preview',
    kind: 'cloud',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    modelHint: 'deepseek-chat',
    kind: 'cloud',
  },
  { id: 'tongyi-qianwen', label: 'Qwen', modelHint: 'qwen-max', kind: 'cloud' },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    modelHint: 'openai/gpt-4o',
    kind: 'cloud',
  },
  {
    id: 'openai-compatible-model',
    label: 'OpenAI-compatible',
    modelHint: 'model-name',
    kind: 'cloud',
    needsUrl: true,
  },
];

export const LOCAL_PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'ollama',
    label: 'Ollama',
    modelHint: 'llama3.1',
    kind: 'local',
    needsUrl: true,
    defaultEndpoint: 'http://localhost:11434/v1',
  },
  {
    id: 'lmstudio',
    label: 'LM Studio',
    modelHint: 'model-name',
    kind: 'local',
    needsUrl: true,
    defaultEndpoint: 'http://localhost:1234/v1',
  },
  {
    id: 'vllm',
    label: 'vLLM',
    modelHint: 'model-name',
    kind: 'local',
    needsUrl: true,
    defaultEndpoint: 'http://localhost:8000/v1',
  },
  {
    id: 'sglang',
    label: 'SGLang',
    modelHint: 'model-name',
    kind: 'local',
    needsUrl: true,
    defaultEndpoint: 'http://localhost:30000/v1',
  },
  {
    id: 'llama.cpp',
    label: 'LLaMA.cpp',
    modelHint: 'model-name',
    kind: 'local',
    needsUrl: true,
    defaultEndpoint: 'http://localhost:8080/v1',
  },
];

export const PROVIDER_PRESETS: ProviderPreset[] = [
  ...CLOUD_PROVIDER_PRESETS,
  ...LOCAL_PROVIDER_PRESETS,
];

export function providerPreset(id: string | null | undefined): ProviderPreset | undefined {
  if (!id) return undefined;
  return PROVIDER_PRESETS.find((preset) => preset.id === id);
}

/** Human label for a provider id, falling back to the raw id. */
export function providerLabel(id: string | null | undefined): string {
  if (!id) return '';
  return providerPreset(id)?.label ?? id;
}

export function isLocalProviderId(id: string | null | undefined): boolean {
  return providerPreset(id)?.kind === 'local';
}

/** Cloud unless the id is a known local runtime. */
export function providerKind(id: string | null | undefined): ProviderKind {
  return isLocalProviderId(id) ? 'local' : 'cloud';
}
