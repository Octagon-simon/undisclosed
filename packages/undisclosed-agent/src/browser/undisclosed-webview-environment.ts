// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { injectable } from '@theia/core/shared/inversify';
import { WebviewEnvironment } from '@theia/plugin-ext/lib/main/browser/webview/webview-environment';

/**
 * Fixes an upstream @theia/plugin-ext defect that breaks every webview resource
 * (the "blue background" seen in Capibara Pet / VS Code Pets, and broken media
 * previews).
 *
 * `WebviewEnvironment.resourceRoot()` builds the webview resource URL with
 * `URI.resolve('theia-resource/{{scheme}}//{{authority}}/{{path}}')`. The `//`
 * before `{{authority}}` is deliberate: it separates the scheme from the (often
 * empty) authority so the downstream parser can rebuild the original URI. But
 * `URI.resolve()` normalises the path and collapses that empty segment to a
 * single `/`, so the emitted template loses one slash.
 *
 * For a local `file:` resource (empty authority) the collapsed template emits
 * `.../theia-resource/file//Users/...`. `normalizeRequestUri()` then parses that
 * as scheme `file`, authority `Users`, path `/octagon/...`, which is outside the
 * extension's `localResourceRoots`, so `loadResource()` returns 404 for every
 * asset. `pixelart.js`, `chiptune.js` and all the sprite PNGs never load, and
 * the pet falls back to its CSS stage colour (Capibara: `#93cbf4`, a sky blue).
 *
 * The bug is still present in Theia 1.75.0 and on `master`, so upgrading does
 * not fix it. We rebuild the same template by string concatenation instead,
 * which preserves the `//` and makes `normalizeRequestUri()` produce the correct
 * `file:///abs/path`.
 */
@injectable()
export class UndisclosedWebviewEnvironment extends WebviewEnvironment {

    async resourceRoot(host: string): Promise<string> {
        // The `frontend` branch uses `withPath()` and has no authority segment to
        // preserve, so the upstream behaviour is already correct there.
        if (host === 'frontend') {
            return super.resourceRoot(host);
        }

        const endpoint = (await this.externalEndpointUrl()).toString(true);
        const base = endpoint.endsWith('/') ? endpoint.slice(0, -1) : endpoint;
        return `${base}/theia-resource/{{scheme}}//{{authority}}/{{path}}`;
    }
}
