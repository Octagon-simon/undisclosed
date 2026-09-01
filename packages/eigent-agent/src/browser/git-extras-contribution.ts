// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Extra git commands that Theia's built-in Git extension doesn't ship but
// developers expect (Antigravity-style): "Undo Last Commit", unstage-all,
// discard-all. Theia already provides stage/unstage/commit/amend, the merge
// editor, dirty-diff, stash, pull/push/sync and history — this just fills the
// gaps. Runs real git via the Git service against the selected repository.

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  Command,
  CommandContribution,
  CommandRegistry,
  MAIN_MENU_BAR,
  MenuContribution,
  MenuModelRegistry,
  MenuPath,
  MessageService,
} from '@theia/core/lib/common';
import { Widget } from '@theia/core/lib/browser';
import {
  TabBarToolbarContribution,
  TabBarToolbarRegistry,
} from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import { Git } from '@theia/git/lib/common';
import { GitRepositoryProvider } from '@theia/git/lib/browser/git-repository-provider';
import { ScmService } from '@theia/scm/lib/browser/scm-service';
import { ScmWidget } from '@theia/scm/lib/browser/scm-widget';

/** The Brain (agent backend) — the AI commit-message endpoint lives here. */
const BRAIN_BASE_URL = 'http://localhost:5001';

/** A "Git" submenu in the main menu bar (discoverable; also in the palette). */
const GIT_MENU: MenuPath = [...MAIN_MENU_BAR, '8_git_extras'];

const UNDO_SOFT: Command = {
  id: 'eigent.git.undoLastCommit',
  label: 'Git: Undo Last Commit (keep changes)',
};
const UNDO_HARD: Command = {
  id: 'eigent.git.undoLastCommitHard',
  label: 'Git: Undo Last Commit (discard changes)',
};
const UNSTAGE_ALL: Command = {
  id: 'eigent.git.unstageAll',
  label: 'Git: Unstage All',
};
const DISCARD_ALL: Command = {
  id: 'eigent.git.discardAll',
  label: 'Git: Discard All Changes',
};
const GENERATE_MESSAGE: Command = {
  id: 'eigent.git.generateCommitMessage',
  label: 'Git: Generate Commit Message (AI)',
  iconClass: 'codicon codicon-sparkle',
};

@injectable()
export class GitExtrasContribution
  implements CommandContribution, MenuContribution, TabBarToolbarContribution
{
  @inject(Git) protected readonly git!: Git;
  @inject(GitRepositoryProvider)
  protected readonly repositories!: GitRepositoryProvider;
  @inject(MessageService) protected readonly messages!: MessageService;
  @inject(ScmService) protected readonly scm!: ScmService;

  /** Generate a Conventional-Commits message from the staged diff via the Brain
   *  (which uses the model the user is chatting with), and drop it into the
   *  Source Control commit box. */
  protected async generateCommitMessage(): Promise<void> {
    const repository = this.repositories.selectedRepository;
    if (!repository) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    let diff = '';
    try {
      const staged = await this.git.exec(repository, [
        'diff',
        '--cached',
        '--no-color',
      ]);
      diff = staged.stdout || '';
      if (!diff.trim()) {
        // Nothing staged — fall back to the working-tree diff.
        const unstaged = await this.git.exec(repository, [
          'diff',
          '--no-color',
        ]);
        diff = unstaged.stdout || '';
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

  protected async run(args: string[], okMessage: string): Promise<void> {
    const repository = this.repositories.selectedRepository;
    if (!repository) {
      this.messages.warn('No git repository is selected.');
      return;
    }
    try {
      const result = await this.git.exec(repository, args);
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
      execute: () => this.generateCommitMessage(),
    });
  }

  registerMenus(menus: MenuModelRegistry): void {
    menus.registerSubmenu(GIT_MENU, 'Git');
    for (const command of [
      GENERATE_MESSAGE,
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
  }

  registerToolbarItems(registry: TabBarToolbarRegistry): void {
    // A ✨ button in the Source Control view's title toolbar.
    registry.registerItem({
      id: GENERATE_MESSAGE.id,
      command: GENERATE_MESSAGE.id,
      tooltip: 'Generate a commit message from the staged changes (AI)',
      icon: 'codicon codicon-sparkle',
      isVisible: (widget?: Widget) => widget instanceof ScmWidget,
    });
  }
}
