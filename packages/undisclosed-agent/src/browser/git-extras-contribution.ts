// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Extra git commands that Theia's built-in Git UI doesn't ship but developers
// expect (Antigravity-style): "Undo Last Commit", unstage-all, discard-all, plus
// a ✨ button that drafts a commit message from the staged diff via the Brain.
//
// PORT NOTE (Theia 1.76): upstream deleted the `@theia/git` package (last
// release 1.60.2; "use the built-in VS Code Git extension instead"). Source
// Control is now served by the bundled `vscode.git` extension. We therefore no
// longer inject `Git` / `GitRepositoryProvider` from `@theia/git`; instead we
// read the repository root + commit box from Theia's provider-agnostic
// `ScmService`, and shell out to `git` through a small same-origin backend
// endpoint (`POST /undisclosed-agent/git/exec`, see the backend module).

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  Command,
  CommandContribution,
  CommandRegistry,
  Emitter,
  MAIN_MENU_BAR,
  MenuContribution,
  MenuModelRegistry,
  MenuPath,
  MessageService,
  Disposable,
} from '@theia/core/lib/common';
import { Widget } from '@theia/core/lib/browser';
import { Endpoint } from '@theia/core/lib/browser/endpoint';
import { FileUri } from '@theia/core/lib/common/file-uri';
import {
  TabBarToolbarContribution,
  TabBarToolbarRegistry,
} from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import { QuickInputService } from '@theia/core/lib/browser/quick-input/quick-input-service';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { ScmService } from '@theia/scm/lib/browser/scm-service';
import { ScmWidget } from '@theia/scm/lib/browser/scm-widget';
import { ScmTreeWidget } from '@theia/scm/lib/browser/scm-tree-widget';
import { SCM_TITLE_MENU } from '@theia/scm/lib/browser/scm-repositories-widget';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { FileStatNode } from '@theia/filesystem/lib/browser/file-tree';
import {
  FileNavigatorContribution,
  NAVIGATOR_CONTEXT_MENU,
  NavigatorContextMenu,
} from '@theia/navigator/lib/browser/navigator-contribution';
import { FileNavigatorWidget } from '@theia/navigator/lib/browser/navigator-widget';
import URI from '@theia/core/lib/common/uri';
import {
  GENERATE_MESSAGE_ITEM_ID,
  renderCommitMessageButton,
} from './git-commit-message-button';

/** The Brain (agent backend) — the AI commit-message endpoint lives here. */
const BRAIN_BASE_URL = 'http://localhost:5001';

/** Same-origin backend endpoint that runs `git` and returns its output.
 *
 * Resolved through Theia's `Endpoint`, NOT a bare root-relative URL. In the dev
 * browser build the frontend origin IS the backend, so a path like
 * `/undisclosed-agent/git/exec` worked by accident; in the packaged Electron app
 * the renderer loads from a `file://` page, so the same path resolved to
 * `file:///undisclosed-agent/git/exec` and `fetch` failed ("Failed to fetch").
 * `Endpoint` resolves the real backend host:port in every mode. See the same
 * one-liner in `undisclosed-agent-widget.tsx` `serverUrl()` and in
 * `undisclosed-import/src/browser/backend-url.ts`. */
const GIT_EXEC_URL = new Endpoint({
  path: '/undisclosed-agent/git/exec',
})
  .getRestUrl()
  .toString();

/** A "Git" submenu in the main menu bar (discoverable; also in the palette). */
const GIT_MENU: MenuPath = [...MAIN_MENU_BAR, '8_git_extras'];

/** The Explorer's "navigation" group in the right-click context menu.
 *
 * `NavigatorContextMenu.NAVIGATION` ALREADY begins with `NAVIGATOR_CONTEXT_MENU`
 * — it is `['navigator-context-menu', 'navigation']` (see the Theia source:
 * `NAVIGATION = [...NAVIGATOR_CONTEXT_MENU, 'navigation']`). Spreading both here
 * produced `['navigator-context-menu', 'navigator-context-menu', 'navigation']`,
 * a path no widget renders, so the item never showed in the Explorer's context
 * menu even though the command itself worked from the palette. Use the
 * namespace member directly. */
const NAVIGATOR_NAVIGATION_MENU: MenuPath = NavigatorContextMenu.NAVIGATION;

const UNDO_SOFT: Command = {
  id: 'undisclosed.git.undoLastCommit',
  label: 'Git: Undo Last Commit (keep changes)',
};
const UNDO_HARD: Command = {
  id: 'undisclosed.git.undoLastCommitHard',
  label: 'Git: Undo Last Commit (discard changes)',
};
const UNSTAGE_ALL: Command = {
  id: 'undisclosed.git.unstageAll',
  label: 'Git: Unstage All',
};
const DISCARD_ALL: Command = {
  id: 'undisclosed.git.discardAll',
  label: 'Git: Discard All Changes',
};
/** Create a commit with no file changes (a "placeholder" commit), like VS Code's
 *  `git.commitEmpty`. Kept explicit here because the empty commit-message box no
 *  longer falls through to an empty commit. */
const COMMIT_EMPTY: Command = {
  id: 'undisclosed.git.commitEmpty',
  label: 'Git: Commit Empty…',
  // Rendered beside the label wherever the command appears (the Changes group
  // context menu, the SCM title "…" menu, the main Git submenu). Theia takes a
  // menu entry's icon from the command's `iconClass`, so without this the item
  // shows as a bare label next to the sparkle icon of Generate Commit Message.
  iconClass: 'codicon codicon-git-commit',
};
const GENERATE_MESSAGE: Command = {
  id: 'undisclosed.git.generateCommitMessage',
  label: 'Git: Generate Commit Message (AI)',
  iconClass: 'codicon codicon-sparkle',
};
/** Append the Explorer's selection to the repository's root `.gitignore`. */
const ADD_TO_GITIGNORE: Command = {
  id: 'undisclosed.git.addToGitignore',
  label: 'Add to .gitignore',
};

interface GitExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
}

/** Run `git <args>` in `cwd` via the backend exec endpoint. */
async function gitExec(cwd: string, args: string[]): Promise<GitExecResult> {
  const res = await fetch(GIT_EXEC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cwd, args }),
  });
  if (!res.ok) {
    throw new Error(`git exec request failed (HTTP ${res.status})`);
  }
  return (await res.json()) as GitExecResult;
}

@injectable()
export class GitExtrasContribution
  implements CommandContribution, MenuContribution, TabBarToolbarContribution
{
  @inject(MessageService) protected readonly messages!: MessageService;
  @inject(ScmService) protected readonly scm!: ScmService;
  @inject(WorkspaceService) protected readonly workspace!: WorkspaceService;
  @inject(QuickInputService) protected readonly quickInput!: QuickInputService;
  @inject(FileService) protected readonly files!: FileService;
  @inject(FileNavigatorContribution)
  protected readonly navigator!: FileNavigatorContribution;

  /** True while the AI commit-message request is in flight — drives the toolbar
   *  button's spinner (and disables it so it can't be double-fired). */
  protected generating = false;
  /** Fire when `generating` changes. The React toolbar button subscribes to this
   *  and re-renders itself; it is NOT used to re-render the SCM toolbar. */
  protected readonly onDidChangeToolbar = new Emitter<void>();

  protected setGenerating(value: boolean): void {
    this.generating = value;
    this.onDidChangeToolbar.fire();
  }

  /** Public read/subscribe hooks for the React toolbar button. It renders as its
   *  own React node and re-renders itself from this event, so it never asks the
   *  container TabBarToolbar to re-render (see git-commit-message-button.tsx). */
  isGenerating(): boolean {
    return this.generating;
  }

  onDidChangeGenerating(listener: () => void): Disposable {
    return this.onDidChangeToolbar.event(() => listener());
  }

  /** Run the commit-message generation (shared by the command and the button). */
  async trigger(): Promise<void> {
    if (this.generating) {
      return;
    }
    this.setGenerating(true);
    try {
      await this.generateCommitMessage();
    } finally {
      this.setGenerating(false);
    }
  }

  /**
   * The git repository root: prefer the selected Source Control repository (now
   * the built-in `vscode.git` provider), else fall back to the first workspace
   * root so the commands still work before SCM has settled.
   */
  protected repositoryRoot(): string | undefined {
    const scmRoot = this.scm.selectedRepository?.provider.rootUri;
    if (scmRoot) {
      return FileUri.fsPath(scmRoot);
    }
    const roots = this.workspace.tryGetRoots();
    if (roots.length > 0) {
      return FileUri.fsPath(roots[0].resource);
    }
    return undefined;
  }

  /**
   * The files AND folders currently selected in the Explorer.
   *
   * We deliberately do NOT use the navigator contribution's own
   * `getSelectedFileNodes()`: it filters the selection through `FileNode.is`,
   * whose runtime check is `FileStatNode.is(node) && !node.fileStat.isDirectory`
   * — i.e. FILES ONLY. Right-clicking a folder yields a `DirNode`, so that
   * helper returns `[]` and the command bailed out with "Select a file or folder
   * in the Explorer first." even though a folder WAS selected. Instead we read
   * the `FileNavigatorWidget`'s tree selection directly (the same set the user
   * right-clicked — `TreeWidget.handleContextMenuEvent` selects the node before
   * the menu opens) and filter with `FileStatNode.is`, which matches both files
   * and folders. `tryGetWidget()` is public on the view-contribution base, so no
   * `protected` access hack is needed.
   */
  protected selectedFileNodes(): FileStatNode[] {
    const widget = (
      this.navigator as unknown as {
        tryGetWidget(): FileNavigatorWidget | undefined;
      }
    ).tryGetWidget();
    return widget?.model.selectedNodes.filter(FileStatNode.is) ?? [];
  }

  /** `uri`'s path relative to `root`, slash-normalized, or undefined when `uri`
   *  is not inside `root` (so we never write a pattern that escapes the repo). */
  protected relativeToRoot(root: string, uri: URI): string | undefined {
    const toPosix = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '');
    const target = toPosix(FileUri.fsPath(uri));
    const base = toPosix(root);
    if (target === base || !target.startsWith(`${base}/`)) {
      return undefined;
    }
    return target.slice(base.length + 1);
  }

  /**
   * Append the Explorer's current selection to the repository's root
   * `.gitignore` (creating it if absent). Folders get a trailing slash so the
   * whole directory is ignored, matching what `git status` would suggest.
   */
  protected async addToGitignore(): Promise<void> {
    const root = this.repositoryRoot();
    if (!root) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    const nodes = this.selectedFileNodes();
    if (nodes.length === 0) {
      this.messages.warn('Select a file or folder in the Explorer first.');
      return;
    }
    const patterns: string[] = [];
    for (const node of nodes) {
      const rel = this.relativeToRoot(root, node.uri);
      if (!rel) {
        continue;
      }
      patterns.push(node.fileStat?.isDirectory ? `${rel}/` : rel);
    }
    if (patterns.length === 0) {
      this.messages.warn('The selection is outside the git repository.');
      return;
    }
    const gitignoreUri = FileUri.create(root).resolve('.gitignore');
    let existing = '';
    if (await this.files.exists(gitignoreUri)) {
      existing = (await this.files.read(gitignoreUri)).value ?? '';
    }
    // Treat an entry and its folder form as the same thing ("dist" == "dist/").
    const known = new Set(
      existing
        .split(/\r?\n/)
        .map((line) => line.trim().replace(/\/+$/, ''))
        .filter(Boolean)
    );
    const toAdd = patterns.filter(
      (pattern) => !known.has(pattern.replace(/\/+$/, ''))
    );
    if (toAdd.length === 0) {
      this.messages.info('Already in .gitignore.');
      return;
    }
    const prefix =
      existing.length === 0
        ? ''
        : existing.endsWith('\n')
          ? existing
          : `${existing}\n`;
    await this.files.write(gitignoreUri, `${prefix}${toAdd.join('\n')}\n`);
    this.messages.info(`Added to .gitignore: ${toAdd.join(', ')}`);
  }

  /** Generate a Conventional-Commits message from the staged diff via the Brain
   *  (which uses the model the user is chatting with), and drop it into the
   *  Source Control commit box. */
  protected async generateCommitMessage(): Promise<void> {
    const root = this.repositoryRoot();
    if (!root) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    let diff = '';
    try {
      const staged = await gitExec(root, ['diff', '--cached', '--no-color']);
      let patch = staged.stdout || '';
      let stagedScope = true;
      if (!patch.trim()) {
        // Nothing staged — fall back to the working-tree diff.
        const unstaged = await gitExec(root, ['diff', '--no-color']);
        patch = unstaged.stdout || '';
        stagedScope = false;
      }
      if (patch.trim()) {
        // Prepend the FULL list of changed files (--stat) ahead of the patch.
        // The patch can be truncated downstream for very large changesets, but
        // the stat is small and sits at the head, so the model always sees
        // EVERY changed file even when the patch body is trimmed — otherwise
        // late files were dropped and the message "missed" changes.
        const stat = await gitExec(
          root,
          stagedScope
            ? ['diff', '--cached', '--stat']
            : ['diff', '--stat']
        );
        diff = `Files changed:\n${(stat.stdout || '').trim()}\n\n${patch}`;
      }
    } catch (err) {
      this.messages.error(
        `Could not read the diff: ${(err as Error)?.message ?? err}`
      );
      return;
    }
    if (!diff.trim()) {
      this.messages.warn('No changes to summarize — stage some changes first.');
      return;
    }
    try {
      const res = await fetch(`${BRAIN_BASE_URL}/git/commit-message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ diff }),
      });
      const data = (await res.json()) as {
        success?: boolean;
        message?: string;
      };
      if (!data?.success || !data.message) {
        this.messages.error(
          data?.message || 'Could not generate a commit message.'
        );
        return;
      }
      const input = this.scm.selectedRepository?.input;
      if (input) {
        input.value = data.message;
      } else {
        this.messages.info(data.message);
      }
    } catch (err) {
      this.messages.error(
        `Commit-message request failed: ${(err as Error)?.message ?? err}`
      );
    }
  }

  /**
   * Create a commit with no file changes. Prefers the message already in the
   * Source Control box; otherwise prompts for one so the empty commit still has
   * a meaningful subject.
   */
  protected async commitEmpty(): Promise<void> {
    const root = this.repositoryRoot();
    if (!root) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    let message = (this.scm.selectedRepository?.input.value ?? '').trim();
    if (!message) {
      message = (
        (await this.quickInput.input({
          prompt: 'Message for the empty commit',
          placeHolder: 'chore: empty commit',
        })) ?? ''
      ).trim();
    }
    if (!message) {
      return;
    }
    await this.run(
      ['commit', '--allow-empty', '-m', message],
      'Created an empty commit.'
    );
  }

  protected async run(args: string[], okMessage: string): Promise<void> {
    const root = this.repositoryRoot();
    if (!root) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    try {
      const result = await gitExec(root, args);
      if (result.exitCode && result.exitCode !== 0) {
        this.messages.error(
          `git ${args.join(' ')} failed: ${result.stderr || result.exitCode}`
        );
      } else {
        this.messages.info(okMessage);
      }
    } catch (err) {
      this.messages.error(
        `git ${args.join(' ')} failed: ${(err as Error)?.message ?? err}`
      );
    }
  }

  protected async confirm(message: string): Promise<boolean> {
    const choice = await this.messages.warn(message, 'Cancel', 'Discard');
    return choice === 'Discard';
  }

  registerCommands(commands: CommandRegistry): void {
    commands.registerCommand(UNDO_SOFT, {
      execute: () =>
        this.run(
          ['reset', '--soft', 'HEAD~1'],
          'Undid the last commit — its changes are kept and staged.'
        ),
    });
    commands.registerCommand(UNDO_HARD, {
      execute: async () => {
        if (
          await this.confirm(
            'Undo the last commit AND permanently discard its changes? This cannot be undone.'
          )
        ) {
          this.run(
            ['reset', '--hard', 'HEAD~1'],
            'Undid the last commit and discarded its changes.'
          );
        }
      },
    });
    commands.registerCommand(UNSTAGE_ALL, {
      execute: () => this.run(['reset'], 'Unstaged all changes.'),
    });
    commands.registerCommand(DISCARD_ALL, {
      execute: async () => {
        if (
          await this.confirm(
            'Discard ALL uncommitted changes in the working tree? This cannot be undone.'
          )
        ) {
          this.run(
            ['checkout', '--', '.'],
            'Discarded all working-tree changes.'
          );
        }
      },
    });
    commands.registerCommand(GENERATE_MESSAGE, {
      isEnabled: () => !this.generating,
      execute: () => this.trigger(),
    });
    commands.registerCommand(COMMIT_EMPTY, {
      execute: () => this.commitEmpty(),
    });
    commands.registerCommand(ADD_TO_GITIGNORE, {
      execute: () => this.addToGitignore(),
    });
  }

  registerMenus(menus: MenuModelRegistry): void {
    menus.registerSubmenu(GIT_MENU, 'Git');
    for (const command of [
      GENERATE_MESSAGE,
      COMMIT_EMPTY,
      UNDO_SOFT,
      UNDO_HARD,
      UNSTAGE_ALL,
      DISCARD_ALL,
    ]) {
      menus.registerMenuAction(GIT_MENU, {
        commandId: command.id,
        label: (command.label ?? command.id).replace(/^Git: /, ''),
      });
    }

    // "Commit Empty…" in the Source Control UI: the "Changes" group context
    // menu (right-click the group) and the view's "…" title menu, beside the
    // built-in Commit/Refresh actions.
    menus.registerMenuAction(ScmTreeWidget.RESOURCE_GROUP_CONTEXT_MENU, {
      commandId: COMMIT_EMPTY.id,
      label: 'Commit Empty…',
      order: 'z',
    });
    menus.registerMenuAction(SCM_TITLE_MENU, {
      commandId: COMMIT_EMPTY.id,
      label: 'Commit Empty…',
      order: 'z',
    });

    // "Add to .gitignore": right-click a file or folder in the Explorer. The
    // command reads the Explorer selection itself (see `addToGitignore`).
    menus.registerMenuAction(NAVIGATOR_NAVIGATION_MENU, {
      commandId: ADD_TO_GITIGNORE.id,
      order: 'z',
    });
  }

  registerToolbarItems(registry: TabBarToolbarRegistry): void {
    // A sparkle button in the Source Control view's title toolbar.
    //
    // Registered as a self-contained React item (render, not icon +
    // onDidChange). The stock icon/onDidChange approach makes the registry
    // re-render the WHOLE TabBarToolbar; Theia 1.76 then crashes rendering the
    // vscode.git menu items (renderMenuItem reads `widget.node` while the
    // toolbar's current widget is undefined), leaving the spinner stuck. A
    // React item re-renders only itself.
    registry.registerItem({
      id: GENERATE_MESSAGE.id,
      command: GENERATE_MESSAGE.id,
      isVisible: (widget?: Widget) => widget instanceof ScmWidget,
      render: () => renderCommitMessageButton(this),
    });
  }
}
