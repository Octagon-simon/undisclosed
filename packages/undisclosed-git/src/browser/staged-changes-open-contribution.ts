// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Make STAGED Source Control entries open against the writable working-tree file.
//
// Theia 1.76 removed `@theia/git`, so the old `GitScmProvider.getUriToOpen`
// override (which did this for Theia 1.60) no longer exists. Source Control is
// now served by the bundled `vscode.git` extension through plugin-ext. For a
// staged (index-group) change that extension's default open command is a
// `vscode.diff` between two `git:` blob URIs (HEAD vs index); the `git:` file
// system provider is registered read-only, so typing in either pane gives
// "Cannot edit in read-only editor".
//
// We restore the previous behaviour by patching `PluginScmResource.open()`:
// for resources in the git `index` group whose working-tree copy still exists,
// open a diff of  git:<index>  (left, read-only)  vs  <file>  (right, writable)
// instead of the extension's HEAD-vs-index diff. Deleting still shows the HEAD
// blob (there is no working file to edit), and every other group is untouched.
//
// The index blob URI is built exactly the way vscode.git builds it:
//   scheme 'git', same path, query = JSON({ path: fsPath, ref: '' })
// (`ref: ''` is the index; see the extension's `toGitUri` / `readFile` ref map,
// where '' resolves to the staged object).

import { inject, injectable } from '@theia/core/shared/inversify';
import URI from '@theia/core/lib/common/uri';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { DiffService } from '@theia/workspace/lib/browser/diff-service';
import { PluginScmResource } from '@theia/plugin-ext/lib/main/browser/scm-main';

/** The vscode.git resource-group id for staged ("Staged Changes") entries. */
const INDEX_GROUP_ID = 'index';

interface OpenServices {
  readonly diff: DiffService;
  readonly files: FileService;
}

let installed = false;

/**
 * Patches `PluginScmResource.prototype.open` once. Keyed off the resource's
 * group id so only staged changes are redirected.
 */
export function installStagedOpenOverride(services: OpenServices): void {
  if (installed) {
    return;
  }
  installed = true;

  const proto = PluginScmResource.prototype;
  const original = proto.open;
  proto.open = async function (this: PluginScmResource): Promise<void> {
    try {
      if (await openStagedAgainstWorkingTree(this, services)) {
        return;
      }
    } catch (err) {
      // Never make Source Control worse than stock: fall back to the extension.
      // eslint-disable-next-line no-console
      console.warn(
        '[undisclosed-git] staged-open override failed; using default open',
        err
      );
    }
    return original.call(this);
  };
}

/**
 * @returns true when it opened a writable view, false to let the extension's
 * default open run.
 */
async function openStagedAgainstWorkingTree(
  resource: PluginScmResource,
  services: OpenServices
): Promise<boolean> {
  if (resource.group?.id !== INDEX_GROUP_ID) {
    return false;
  }
  const working = resource.sourceUri;
  if (!working || working.scheme !== 'file') {
    return false;
  }
  // A staged deletion has no working-tree copy, so there is nothing to edit;
  // leave it to the extension (it opens the read-only HEAD blob).
  let workingExists = false;
  try {
    const stat = await services.files.resolve(working);
    workingExists = !!stat && !stat.isDirectory;
  } catch {
    workingExists = false;
  }
  if (!workingExists) {
    return false;
  }

  const index = toGitIndexUri(working);
  const label = `${working.path.base} (Index)`;
  await services.diff.openDiffEditor(index, working, label);
  return true;
}

/** Build a `git:` URI pointing at the index (staged) blob, like vscode.git. */
function toGitIndexUri(fileUri: URI): URI {
  const query = JSON.stringify({ path: FileUri.fsPath(fileUri), ref: '' });
  return fileUri.withScheme('git').withQuery(query);
}

/**
 * Installs the override on frontend start. It must run before the user's first
 * click (onStart is well before that) and after plugin-ext has defined
 * `PluginScmResource` (it is loaded with the bundle).
 */
@injectable()
export class StagedChangesOpenContribution
  implements FrontendApplicationContribution
{
  @inject(DiffService) protected readonly diff!: DiffService;
  @inject(FileService) protected readonly files!: FileService;

  onStart(): void {
    installStagedOpenOverride({ diff: this.diff, files: this.files });
  }
}
