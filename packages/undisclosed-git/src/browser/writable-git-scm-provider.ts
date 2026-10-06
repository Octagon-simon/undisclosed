/**
 * Fix for the "can't save a staged file" bug.
 *
 * Theia 1.60's `GitScmProvider.getUriToOpen` opens *staged* changes against
 * `gitrev:` URIs (the staged `index` blob and/or `HEAD`). Those documents live
 * on a read-only file system (`GitFileSystemProvider` advertises `Readonly`
 * and `writeFile` throws), so the editor buffer counts as dirty but every save
 * is silently rejected. Cmd+S, File > Save and the close-all "save" prompt all
 * do nothing, and the change never lands.
 *
 * The cure is to make a staged change open the *working-tree* file on the
 * writable side, exactly like the unstaged "Working tree" entries already do:
 *
 *   - Modified/copied/renamed, staged -> diff `index` (left, read-only) vs the
 *     real `file:` URI (right, editable).
 *   - New file, staged                 -> the real `file:` URI (editable).
 *
 * Deleted files stay as-is: there is nothing on the working tree to write to,
 * so the read-only `HEAD`/`index` blob is the only sensible thing to show.
 *
 * Rather than subclassing `GitScmProvider` (which the git DI factory builds in
 * a private child container), we let the original factory do all the wiring and
 * then override the single method on the produced instance.
 */
import URI from '@theia/core/lib/common/uri';
import { DiffUris } from '@theia/core/lib/browser/diff-uris';
import { nls } from '@theia/core/lib/common/nls';
import { interfaces } from '@theia/core/shared/inversify';
import { GitScmProvider, GitScmProviderOptions } from '@theia/git/lib/browser/git-scm-provider';
import { GIT_RESOURCE_SCHEME } from '@theia/git/lib/browser/git-resource';
import { createGitScmProviderFactory } from '@theia/git/lib/browser/git-frontend-module';
import { GitFileChange, GitFileStatus } from '@theia/git/lib/common';

/** The staged-vs-working-tree `index` blob URI. */
function indexRev(uri: URI): URI {
    return uri.withScheme(GIT_RESOURCE_SCHEME).withQuery('index');
}

/** The `HEAD` blob URI. */
function headRev(uri: URI): URI {
    return uri.withScheme(GIT_RESOURCE_SCHEME).withQuery('HEAD');
}

function workingTreeTitle(uri: URI): string {
    return nls.localize('theia/git/tabTitleWorkingTree', '{0} (Working tree)', uri.path.base);
}

/**
 * Drop-in replacement for `GitScmProvider.getUriToOpen` that keeps the writable
 * working-tree file on the right-hand side of staged diffs.
 */
export function getWritableUriToOpen(provider: GitScmProvider, change: GitFileChange): URI {
    const changeUri = new URI(change.uri);
    const fromFileUri = change.oldUri ? new URI(change.oldUri) : changeUri; // set oldUri on renamed and copied

    if (change.status === GitFileStatus.Deleted) {
        // Nothing on the working tree to save into: keep the read-only blob.
        return change.staged ? headRev(changeUri) : indexRev(changeUri);
    }

    if (change.status !== GitFileStatus.New) {
        if (change.staged) {
            // Was: index(HEAD) vs index(index), both read-only. Now: staged content
            // on the left, the writable working-tree file on the right.
            return DiffUris.encode(indexRev(changeUri), changeUri, workingTreeTitle(changeUri));
        }
        if (provider.stagedChanges.find(c => c.uri === change.uri)) {
            return DiffUris.encode(indexRev(fromFileUri), changeUri, workingTreeTitle(changeUri));
        }
        if (provider.mergeChanges.find(c => c.uri === change.uri)) {
            return changeUri;
        }
        return DiffUris.encode(headRev(fromFileUri), changeUri, workingTreeTitle(changeUri));
    }

    if (change.staged) {
        // Was: the read-only `index` blob. New file -> open the real file.
        return changeUri;
    }
    if (provider.stagedChanges.find(c => c.uri === change.uri)) {
        return DiffUris.encode(indexRev(changeUri), changeUri, workingTreeTitle(changeUri));
    }
    return changeUri;
}

/**
 * Wraps Theia's `createGitScmProviderFactory`: run the original factory (so all
 * injections + history wiring stay intact), then swap in our `getUriToOpen`.
 */
export function createWritableGitScmProviderFactory(ctx: interfaces.Context): GitScmProvider.Factory {
    const delegate = createGitScmProviderFactory(ctx);
    return (options: GitScmProviderOptions): GitScmProvider => {
        const provider = delegate(options);
        provider.getUriToOpen = (change: GitFileChange) => getWritableUriToOpen(provider, change);
        return provider;
    };
}
