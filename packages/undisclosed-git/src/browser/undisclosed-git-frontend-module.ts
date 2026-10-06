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
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { StagedChangesOpenContribution } from './staged-changes-open-contribution';

export default new ContainerModule((bind) => {
  bind(StagedChangesOpenContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(
    StagedChangesOpenContribution
  );
});
