// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// "Keep the API, kill the duplicate UI."
//
// The VS Code git built-ins (vscode.git / vscode.git-base) make the Source
// Control view show a SECOND set of inline actions (Add / Discard / ...) next to
// Theia's native `@theia/git` ones. We want to stop that duplication WITHOUT
// removing the extension, because other extensions (GitLens, ruby-lsp, ...) call
// `vscode.git`'s API.
//
// Why this is a *menu* problem, not a *provider* problem — verified against
// Theia 1.60 in node_modules:
//
//   * `ScmService.registerScmProvider` keys repositories by `id + ':' + rootUri`
//     and throws on a collision (`node_modules/@theia/scm/lib/browser/scm-service.js`).
//     The native provider is id `git` (`@theia/git/lib/browser/git-scm-provider.js`),
//     and vscode.git also registers id `git` for the same folder. So its provider
//     registration is rejected ("provider ... already exists") and no second tree
//     is created. Suppressing the provider would therefore change nothing.
//
//   * Plugin *menus*, however, do not depend on provider registration. Theia maps
//     VS Code's `scm/resourceState/context` contribution point onto
//     `ScmTreeWidget.RESOURCE_CONTEXT_MENU`, and the item's `inline` group onto
//     `ScmTreeWidget.RESOURCE_INLINE_MENU` (see
//     `@theia/plugin-ext/.../menus/vscode-theia-menu-mappings.js`). Those menu
//     paths are global — every SCM resource renders them, whichever provider owns
//     it. So vscode.git's inline actions duplicate `@theia/git`'s on the native
//     git resources.
//
// Fix: keep the built-ins deployed and active (API intact) but withhold *only*
// their SCm-contribution-point menus before they reach the menu registry. Their
// command-palette and editor menus are left alone.
//
// Wiring note: rebinding `MenusContributionPointHandler` is safe because the
// generated frontend module loads `undisclosed-agent/...-frontend-module` AFTER
// `@theia/plugin-ext/...-frontend-module` (see apps/desktop/src-gen/frontend/
// index.js), so our binding is the last one and wins.

import { injectable } from '@theia/core/shared/inversify';
import { Disposable } from '@theia/core/lib/common';
import { DeployedPlugin } from '@theia/plugin-ext/lib/common';
import { MenusContributionPointHandler } from '@theia/plugin-ext/lib/main/browser/menus/menus-contribution-handler';

/**
 * VS Code extension ids whose Source Control menus we withhold. These are the
 * VS Code git built-ins: Theia already serves Source Control through @theia/git,
 * so their contributed actions are pure duplication. The extensions themselves
 * stay deployed, so their API remains available to consumers like GitLens.
 */
const HOST_PROVIDED_IDS = new Set(['vscode.git', 'vscode.git-base']);

/** VS Code menu contribution points that drive the Source Control UI. */
const SCM_CONTRIBUTION_POINT = /^scm\//;

/**
 * A `MenusContributionPointHandler` that drops the Source Control menus of the
 * host-provided VS Code git built-ins. Their API stays live; their duplicate
 * Source Control actions do not show up.
 */
@injectable()
export class UndisclosedMenusContributionHandler extends MenusContributionPointHandler {
  override handle(plugin: DeployedPlugin): Disposable {
    const id = plugin.metadata?.model?.id?.toLowerCase();
    const menus = plugin.contributes?.menus;
    if (!id || !menus || !HOST_PROVIDED_IDS.has(id)) {
      return super.handle(plugin);
    }

    const filteredMenus: typeof menus = {};
    let droppedSomething = false;
    for (const [contributionPoint, items] of Object.entries(menus)) {
      if (SCM_CONTRIBUTION_POINT.test(contributionPoint)) {
        droppedSomething = true;
      } else {
        filteredMenus[contributionPoint] = items;
      }
    }
    if (!droppedSomething) {
      return super.handle(plugin);
    }

    // eslint-disable-next-line no-console
    console.info(
      `[undisclosed-agent] suppressed Source Control menus from host-provided ${id}`
    );
    return super.handle({
      ...plugin,
      contributes: { ...plugin.contributes, menus: filteredMenus },
    });
  }
}
