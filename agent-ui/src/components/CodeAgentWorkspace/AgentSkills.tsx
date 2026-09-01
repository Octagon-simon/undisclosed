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
 * Compact, panel-native Skills manager for the embedded agent. Lists the user's
 * skills (and examples) with an enable toggle + delete, and adds a skill by
 * uploading a SKILL.md zip. Deliberately NOT the full desktop Skills page
 * (whose hero header / wide cards / big margins don't fit the narrow panel).
 */

import { skillImportZip } from '@/api/brain';
import { useSkillsStore, type Skill } from '@/store/skillsStore';
import { Loader2, Plus, Sparkles, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

function Toggle({
  checked,
  onChange,
  busy,
}: {
  checked: boolean;
  onChange: () => void;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={busy}
      onClick={onChange}
      // Explicit on=green/off=grey — the ds brand token is unmapped in the embed
      // theme (resolves to black). Both read on light and dark.
      style={{ backgroundColor: checked ? '#22c55e' : '#6b7280' }}
      className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50"
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all ${
          checked ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
  );
}

function SkillRow({
  skill,
  onToggle,
  onDelete,
}: {
  skill: Skill;
  onToggle: () => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="flex items-start gap-2 rounded-lg px-2.5 py-2 transition-colors hover:bg-ds-bg-neutral-muted-default">
      <div className="min-w-0 flex-1">
        <div className="truncate text-label-sm font-medium text-ds-text-neutral-default-default">
          {skill.name}
        </div>
        {skill.description ? (
          <div className="mt-0.5 line-clamp-2 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
            {skill.description}
          </div>
        ) : null}
      </div>
      <Toggle checked={skill.enabled} onChange={() => run(onToggle)} busy={busy} />
      {onDelete ? (
        <button
          type="button"
          onClick={() => run(onDelete)}
          disabled={busy}
          aria-label="Delete skill"
          className="shrink-0 rounded-md p-1 text-ds-icon-neutral-subtle-default outline-none transition-colors hover:bg-ds-bg-neutral-subtle-hover hover:text-ds-icon-error-default-default disabled:opacity-50"
        >
          <Trash2 size={13} aria-hidden />
        </button>
      ) : (
        <span className="w-[22px] shrink-0" />
      )}
    </li>
  );
}

export default function AgentSkills() {
  const { skills, syncFromDisk, toggleSkill, deleteSkill } = useSkillsStore();
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await syncFromDisk();
    } finally {
      setLoading(false);
    }
  }, [syncFromDisk]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onPickZip = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file) return;
      setAdding(true);
      try {
        const buf = await file.arrayBuffer();
        const res = await skillImportZip(buf);
        if (!res.success) throw new Error(res.error || 'Import failed');
        toast.success('Skill added.');
        await refresh();
      } catch (err) {
        toast.error((err as Error)?.message || 'Failed to add skill.');
      } finally {
        setAdding(false);
      }
    },
    [refresh]
  );

  const yours = skills.filter((s) => !s.isExample);
  const examples = skills.filter((s) => s.isExample);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
          Skills
        </span>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={adding}
          className="flex items-center gap-1 rounded-md bg-ds-bg-neutral-muted-default px-2 py-1 text-label-xs text-ds-text-neutral-default-default outline-none transition-colors hover:bg-ds-bg-neutral-subtle-hover disabled:opacity-50"
        >
          {adding ? (
            <Loader2 size={13} className="animate-spin" aria-hidden />
          ) : (
            <Plus size={13} aria-hidden />
          )}
          Add
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={onPickZip}
        />
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2
            className="h-5 w-5 animate-spin text-ds-icon-neutral-subtle-default"
            aria-hidden
          />
        </div>
      ) : skills.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <Sparkles
            className="h-6 w-6 text-ds-icon-neutral-subtle-default"
            aria-hidden
          />
          <div className="text-label-sm text-ds-text-neutral-default-default">
            No skills yet
          </div>
          <div className="max-w-[240px] text-label-xs text-ds-text-neutral-subtle-default">
            Add a skill (a SKILL.md zip) to teach the agent a reusable procedure.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {yours.length > 0 ? (
            <div>
              <div className="mb-0.5 px-1 text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
                Your skills
              </div>
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {yours.map((s) => (
                  <SkillRow
                    key={s.id}
                    skill={s}
                    onToggle={() => toggleSkill(s.id)}
                    onDelete={() => deleteSkill(s.id)}
                  />
                ))}
              </ul>
            </div>
          ) : null}
          {examples.length > 0 ? (
            <div>
              <div className="mb-0.5 px-1 text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
                Examples
              </div>
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {examples.map((s) => (
                  <SkillRow
                    key={s.id}
                    skill={s}
                    onToggle={() => toggleSkill(s.id)}
                  />
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
