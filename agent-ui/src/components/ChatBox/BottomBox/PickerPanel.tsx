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

import { fetchConnectedProviders, providerLabel } from '@/api/connectors';
import { proxyFetchGet } from '@/api/http';
import ellipseIcon from '@/assets/mcp/Ellipse-25.svg';
import { Button } from '@/components/ui/button';
import {
  useIntegrationManagement,
  type IntegrationItem,
} from '@/hooks/useIntegrationManagement';
import { integrationLeadingIconUrl } from '@/lib/connectorIcons';
import {
  RICH_CONNECTOR_STYLE_CLASSES,
  RICH_SKILL_STYLE_CLASSES,
  connectorNameToToken,
  hashSkillLabel,
} from '@/lib/richText';
import { requestEmbedScreen } from '@/agent-embed/embedNav';
import { mcpList } from '@/api/brain';
import { skillNameToDirName } from '@/lib/skillToolkit';
import { cn } from '@/lib/utils';
import { useServerCapabilityStore } from '@/store/serverCapabilityStore';
import { useSkillsStore } from '@/store/skillsStore';
import { Check, Plus, Wrench } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

/**
 * An item shown in a picker panel. `token` is the exact string inserted inline
 * into the rich chat input when the item is selected (`#skill` / `@connector`).
 */
export interface PickerItem {
  id: string;
  name: string;
  token: string;
  /** Provider icon URL for hosted connector items. */
  iconUrl?: string;
}

/** A labelled section within a picker (e.g. built-in vs. your own connectors). */
export interface PickerGroup {
  id: string;
  /** Section heading; omit for a single ungrouped list (e.g. skills). */
  label?: string;
  items: PickerItem[];
}

interface PickerPanelProps {
  title: string;
  groups: PickerGroup[];
  /** Current input text — an item is "added" when its token appears in it. */
  inputValue: string;
  onToggleItem: (item: PickerItem) => void;
  /** Leading token tag for a row (`#skill` / `@connector`). */
  renderTag: (item: PickerItem) => ReactNode;
  /** Leading logo/icon for a row, shown before the item name. Omit for no logo. */
  renderLogo?: (item: PickerItem) => ReactNode;
  loading?: boolean;
  emptyLabel: string;
  emptyActionLabel: string;
  onEmptyAction: () => void;
}

/**
 * Floating list panel shown above BoxMain in the BottomBox shell. Selecting an
 * item inserts its token inline into the input; selecting an added item removes
 * it. Purely presentational — the trigger and open state live in BottomBox.
 */
export function PickerPanel({
  title,
  groups,
  inputValue,
  onToggleItem,
  renderTag,
  renderLogo,
  loading = false,
  emptyLabel,
  emptyActionLabel,
  onEmptyAction,
}: PickerPanelProps) {
  const nonEmptyGroups = groups.filter((g) => g.items.length > 0);
  const totalItems = nonEmptyGroups.reduce((n, g) => n + g.items.length, 0);

  return (
    // No border at all (same fix as the Back-header box) — the prominent ds
    // panel-border read as a heavy box. Separation comes from the background +
    // shadow, so it floats like a popover.
    <div
      style={{ boxShadow: '0 8px 28px rgba(0,0,0,0.35)' }}
      className="flex w-full flex-col overflow-hidden rounded-2xl bg-ds-bg-neutral-subtle-default"
    >
      {/* Header */}
      <div className="flex items-center gap-1 px-3 pb-1 pt-2">
        <span className="text-xs font-bold text-ds-text-neutral-muted-default">
          {title}
        </span>
        {totalItems > 0 && (
          <span className="text-xs font-bold text-ds-text-neutral-muted-default">
            {totalItems}
          </span>
        )}
      </div>

      {/* List: max-h-[240px] caps the panel's scrollable area */}
      <div className="scrollbar-always-visible flex max-h-[240px] flex-col gap-0.5 overflow-y-auto p-1">
        {loading ? (
          <>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-8 w-full animate-pulse rounded-lg bg-ds-bg-neutral-strong-default"
              />
            ))}
          </>
        ) : totalItems === 0 ? (
          <div className="flex w-full items-center justify-between gap-2 px-2 py-2">
            <span className="text-xs font-normal text-ds-text-neutral-muted-default">
              {emptyLabel}
            </span>
            <Button
              variant="ghost"
              size="xs"
              buttonContent="text"
              onClick={onEmptyAction}
            >
              {emptyActionLabel}
            </Button>
          </div>
        ) : (
          nonEmptyGroups.map((group) => (
            <Fragment key={group.id}>
              {group.label && (
                <div className="px-2 pb-0.5 pt-1.5 text-xs font-bold text-ds-text-neutral-muted-default">
                  {group.label}
                </div>
              )}
              {group.items.map((item) => (
                <PickerPanelItem
                  key={item.id}
                  item={item}
                  tag={renderTag(item)}
                  logo={renderLogo?.(item)}
                  added={inputValue.includes(item.token)}
                  onToggle={() => onToggleItem(item)}
                />
              ))}
            </Fragment>
          ))
        )}
      </div>

      {/* Persistent manage action: the empty-state action only renders at zero
          items, so once you've added connectors/skills there was no way back to
          the manage screen. Keep it reachable here. */}
      {totalItems > 0 && (
        <div className="flex justify-end border-t border-solid border-ds-border-neutral-subtle-default px-2 py-1.5">
          <Button
            variant="ghost"
            size="xs"
            buttonContent="text"
            onClick={onEmptyAction}
          >
            {emptyActionLabel}
          </Button>
        </div>
      )}
    </div>
  );
}

interface PickerPanelItemProps {
  item: PickerItem;
  tag: ReactNode;
  logo?: ReactNode;
  added: boolean;
  onToggle: () => void;
}

function PickerPanelItem({
  item,
  tag,
  logo,
  added,
  onToggle,
}: PickerPanelItemProps) {
  return (
    <button
      type="button"
      aria-pressed={added}
      className="group flex w-full items-center gap-2 rounded-xl border-0 bg-ds-bg-neutral-subtle-default px-2 py-1.5 text-left transition-colors hover:bg-ds-bg-neutral-default-default"
      onClick={onToggle}
    >
      {logo && (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center">
          {logo}
        </span>
      )}
      <span className="min-w-0 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap text-sm font-medium text-ds-text-neutral-default-default">
        {item.name}
      </span>
      <span className="max-w-[45%] shrink-0 overflow-hidden whitespace-nowrap">
        {tag}
      </span>
      <span className="flex h-5 w-5 shrink-0 items-center justify-center">
        {added ? (
          <Check size={16} className="text-ds-icon-success-default-default" />
        ) : (
          <Plus
            size={16}
            className="text-ds-icon-neutral-muted-default opacity-0 transition-opacity group-hover:opacity-100"
          />
        )}
      </span>
    </button>
  );
}

interface WiredPickerPanelProps {
  inputValue: string;
  onToggleItem: (item: PickerItem) => void;
}

/** Built-in integrations excluded from the MCP connector list (mirrors settings). */
const EXCLUDED_BUILTIN_CONNECTORS = ['Search', 'RAG'];

/**
 * Connected connectors only, matching the Connectors page sidebar: connected
 * hosted connectors (when the Connector Gateway is enabled), connected built-in
 * integrations (`/api/v1/config/info` + configs), and the user's enabled MCPs
 * (`/api/v1/mcp/users`), shown as labelled sections.
 */
export function ConnectorPickerPanel({
  inputValue,
  onToggleItem,
}: WiredPickerPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Standalone product: the picker lists ONLY the user's LOCAL MCP servers
  // (~/.eigent/mcp.json via /mcp/list) — the exact source the agent reads, and
  // the same list Manage Connectors shows. Eigent's hosted/cloud "account"
  // connectors (the :3001 service — built-ins, cloud-registered MCPs, gateway
  // OAuth providers) are intentionally NOT pulled in: one consistent list, and
  // no external dependency.
  const [localMcps, setLocalMcps] = useState<PickerItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    mcpList()
      .then((res) => {
        if (cancelled) return;
        const servers = (res?.mcpServers ?? {}) as Record<string, unknown>;
        setLocalMcps(
          Object.keys(servers).map((name) => ({
            id: `local-${name}`,
            name,
            token: connectorNameToToken(name),
          }))
        );
      })
      .catch(() => {
        if (!cancelled) setLocalMcps([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups: PickerGroup[] = [
    { id: 'yours', label: t('setting.your-own-mcps'), items: localMcps },
  ];

  return (
    <PickerPanel
      title={t('chat.input-attach-connectors')}
      groups={groups}
      inputValue={inputValue}
      onToggleItem={onToggleItem}
      renderTag={(item) => (
        <span
          className={cn(
            'rounded px-1 py-px text-xs font-medium',
            RICH_CONNECTOR_STYLE_CLASSES
          )}
        >
          {item.token}
        </span>
      )}
      renderLogo={() => (
        <Wrench size={16} className="text-ds-icon-neutral-muted-default" />
      )}
      loading={loading}
      emptyLabel={t('chat.no-connectors-added')}
      emptyActionLabel={t('chat.input-attach-manage-connectors')}
      onEmptyAction={() => {
        // Embed: switch the panel to the connectors screen. Desktop app: no
        // listener, so the navigate() below handles it.
        requestEmbedScreen('connectors');
        navigate('/history?tab=connectors');
      }}
    />
  );
}

/** Lists the user's enabled skills from the skills store. */
export function SkillPickerPanel({
  inputValue,
  onToggleItem,
}: WiredPickerPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const skills = useSkillsStore((s) => s.skills);
  const syncFromDisk = useSkillsStore((s) => s.syncFromDisk);

  // Skills are loaded from the Brain (`/skills`) by syncFromDisk, which in the
  // desktop app runs at startup. In the embedded panel nothing triggers it, so
  // the picker came up empty even though the Brain knows the skills. Load them
  // when the picker first opens (no-op once populated).
  useEffect(() => {
    if (skills.length === 0) {
      void syncFromDisk();
    }
    // Only on first mount of the open panel; syncFromDisk is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = useMemo(
    () =>
      skills
        .filter((s) => s.enabled)
        .map((s) => ({
          id: s.id,
          name: s.name,
          token: `#${s.skillDirName || skillNameToDirName(s.name)}`,
        })),
    [skills]
  );

  return (
    <PickerPanel
      title={t('chat.input-attach-skills')}
      groups={[{ id: 'skills', items }]}
      inputValue={inputValue}
      onToggleItem={onToggleItem}
      renderTag={(item) => {
        const clsIdx =
          hashSkillLabel(item.token) % RICH_SKILL_STYLE_CLASSES.length;
        return (
          <span
            className={cn(
              'rounded px-1 py-px text-xs font-medium',
              RICH_SKILL_STYLE_CLASSES[clsIdx]
            )}
          >
            {item.token}
          </span>
        );
      }}
      emptyLabel={t('chat.no-skills-added')}
      emptyActionLabel={t('chat.input-attach-manage-skills')}
      onEmptyAction={() => {
        requestEmbedScreen('skills');
        navigate('/history?tab=agents');
      }}
    />
  );
}
