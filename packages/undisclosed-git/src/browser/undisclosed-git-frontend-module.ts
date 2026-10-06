/**
 * Frontend module for the `undisclosed-git` Theia extension.
 *
 * It re-binds the git SCM provider factory so that staged changes open against
 * the working-tree file (writable) instead of read-only `gitrev:` blobs. This
 * module is loaded after `@theia/git/lib/browser/git-frontend-module`, so the
 * re-bind wins.
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import { GitScmProvider } from '@theia/git/lib/browser/git-scm-provider';
import { createWritableGitScmProviderFactory } from './writable-git-scm-provider';

export default new ContainerModule((bind, _unbind, isBound, rebind) => {
    if (isBound(GitScmProvider.Factory)) {
        rebind(GitScmProvider.Factory).toFactory(createWritableGitScmProviderFactory);
    } else {
        bind(GitScmProvider.Factory).toFactory(createWritableGitScmProviderFactory);
    }
});
