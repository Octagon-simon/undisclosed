/**
 * Frontend module for the `undisclosed-git` Theia extension.
 *
 * HISTORY: this package used to patch `@theia/git`'s
 * `GitScmProvider.getUriToOpen` so staged changes opened against the writable
 * working-tree file instead of read-only `gitrev:` blobs (the "can't save a
 * staged file" fix). Theia 1.76 removed `@theia/git` (npm: deprecated, "use the
 * built-in VS Code Git extension"), which retired that hook.
 *
 * The equivalent behaviour is now restored for the vscode.git-based Source
 * Control by `StagedChangesOpenContribution`, which patches
 * `PluginScmResource.open()` so a staged change opens a diff of
 * `git:<index>` (read-only) vs the working-tree file (writable) instead of the
 * read-only HEAD-vs-index diff. See staged-changes-open-contribution.ts.
 *
 * `installEmptyDiffInlineOverride` additionally forces diffs against an empty
 * original (untracked files) to render unified instead of side-by-side, so an
 * untracked file no longer opens with a large blank left pane.
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { StagedChangesOpenContribution } from './staged-changes-open-contribution';
import { installEmptyDiffInlineOverride } from './empty-diff-inline-contribution';

// Tint the inline-diff hunk gutter so an untracked file's diff no longer reads as
// a blank strip before the content. Importing the stylesheet here (rather than
// relying on a `theiaExtensions.style` field, which this Theia build does not
// consume) is how @theia/core itself loads its CSS. See style/undisclosed-git.css.
import '../../style/undisclosed-git.css';

// Install at MODULE-LOAD time, not in a FrontendApplicationContribution.onStart:
// Theia restores previously-open editors (including a diff tab, e.g. an
// untracked file you had open before a reload) during start-up, and that can
// happen before our contribution's onStart runs. Patching the provider prototype
// as a side effect of loading this module guarantees the wrapper is in place
// before ANY editor is created.
installEmptyDiffInlineOverride();

export default new ContainerModule((bind) => {
  bind(StagedChangesOpenContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(
    StagedChangesOpenContribution
  );
});
