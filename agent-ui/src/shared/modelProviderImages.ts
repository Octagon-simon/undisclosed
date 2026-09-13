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

import antLingImage from '@/assets/model/ant-ling.svg';
import anthropicImage from '@/assets/model/anthropic.svg';
import azureImage from '@/assets/model/azure.svg';
import bedrockImage from '@/assets/model/bedrock.svg';
import deepseekImage from '@/assets/model/deepseek.svg';
import eigentImage from '@/assets/model/eigent.svg';
import ernieImage from '@/assets/model/ernie.png';
import geminiImage from '@/assets/model/gemini.svg';
import llamaCppImage from '@/assets/model/llamacpp.svg';
import lmstudioImage from '@/assets/model/lmstudio.svg';
import minimaxImage from '@/assets/model/minimax.svg';
import modelarkImage from '@/assets/model/modelark.svg';
import moonshotImage from '@/assets/model/moonshot.svg';
import ollamaImage from '@/assets/model/ollama.svg';
import openaiImage from '@/assets/model/openai.svg';
import openrouterImage from '@/assets/model/openrouter.svg';
import orcarouterImage from '@/assets/model/orcarouter.svg';
import qwenImage from '@/assets/model/qwen.svg';
import sglangImage from '@/assets/model/sglang.svg';
import vllmImage from '@/assets/model/vllm.svg';
import zaiImage from '@/assets/model/zai.svg';
import {
  DARK_FILL_MODELS,
  LLAMA_CPP_PROVIDER_ID,
  PROVIDER_AVATAR_URLS,
} from '@/pages/Agents/localModels';

const MODEL_PROVIDER_IMAGE_MAP: Record<string, string> = {
  cloud: eigentImage,
  openai: openaiImage,
  'codex-subscription': openaiImage,
  'ant-ling': antLingImage,
  anthropic: anthropicImage,
  gemini: geminiImage,
  nebius: PROVIDER_AVATAR_URLS.nebius,
  openrouter: openrouterImage,
  orcarouter: orcarouterImage,
  'tongyi-qianwen': qwenImage,
  deepseek: deepseekImage,
  ernie: ernieImage,
  minimax: minimaxImage,
  'z.ai': zaiImage,
  moonshot: moonshotImage,
  ModelArk: modelarkImage,
  'samba-nova': PROVIDER_AVATAR_URLS['samba-nova'],
  grok: PROVIDER_AVATAR_URLS.grok,
  mistral: PROVIDER_AVATAR_URLS.mistral,
  'aws-bedrock': bedrockImage,
  'aws-bedrock-converse': bedrockImage,
  azure: azureImage,
  'openai-compatible-model': openaiImage,
  ollama: ollamaImage,
  vllm: vllmImage,
  sglang: sglangImage,
  lmstudio: lmstudioImage,
  [LLAMA_CPP_PROVIDER_ID]: llamaCppImage,
  'local-ollama': ollamaImage,
  'local-vllm': vllmImage,
  'local-sglang': sglangImage,
  'local-lmstudio': lmstudioImage,
  'local-llama.cpp': llamaCppImage,
};

/** Resolve provider / tab id to a logo URL for dropdowns and sidebars. */
export function getModelImage(modelId: string | null): string | null {
  if (!modelId) return null;
  return MODEL_PROVIDER_IMAGE_MAP[modelId] ?? null;
}

/**
 * Are we rendering a dark surface?
 *
 * Appearance resolves to a concrete `light` | `dark` mode, but callers are not
 * consistent about what they pass:
 *
 *  - `useAuthStore().appearance` holds the RESOLVED mode (ThemeProvider writes
 *    it back via `setResolvedAppearance`), so it is 'dark' whenever the app is
 *    actually dark.
 *  - Some callers pass `appearanceMode` instead, which is 'system' when the
 *    user picked "follow system". `appearanceMode === 'dark'` is then FALSE
 *    even though the app is rendering dark, so every dark-fill logo quietly
 *    failed to invert.
 *
 * 'system' therefore counts as dark: invert only ever applies to dark-fill
 * marks, and light-on-dark is the intended look for a dark surface.
 */
export function rendersDarkSurface(appearance: string | undefined): boolean {
  return appearance === 'dark' || appearance === 'system';
}

/** Whether a logo should be inverted in dark mode (fill-style logos). */
export function needsInvertModelImage(
  modelId: string | null,
  appearance: string | undefined
): boolean {
  if (!modelId || !rendersDarkSurface(appearance)) return false;
  const key = modelId.startsWith('local-')
    ? modelId.replace('local-', '')
    : modelId;
  return DARK_FILL_MODELS.has(key);
}

/**
 * Inline style for a provider/model logo `<img>`.
 *
 * Dark-mode support for marks that are a solid dark shape (Anthropic, OpenAI,
 * Moonshot, ...): a dark logo disappears against the dark surface, so we invert
 * it. This is the single place that owns the rule, so a caller cannot forget it
 * the way the Anthropic logo in the model picker previously rendered "missing".
 *
 * Light mode never inverts, so the light-mode rendering is unchanged.
 */
export function modelImageStyle(
  modelId: string | null,
  appearance: string | undefined
): { filter: string } | undefined {
  return needsInvertModelImage(modelId, appearance)
    ? { filter: 'invert(1)' }
    : undefined;
}
