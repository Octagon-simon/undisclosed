/**
 * This file can be edited to adjust the ESBuild build process.
 * To reset, delete this file and rerun theia build again.
 *
 * Theia 1.75+ replaced webpack with esbuild. This file ports our one build-time
 * customization, the webview "full width" padding fix (B13), which previously
 * lived in webpack.config.js. See docs/features/theia-overrides.md (B13).
 */
import { browserOptions, watch, __dirname } from './gen-esbuild.browser.mjs';
import { nodeOptions } from './gen-esbuild.node.mjs';
import fs from 'node:fs';
import path from 'node:path';

import esbuild from 'esbuild';

/**
 * Webview "full width" fix (B13).
 *
 * `theia build` copies @theia/plugin-ext's webview host into `lib/webview/pre`
 * (the backend serves it at `/webview`). `main.js` there injects a default
 * stylesheet into every webview whose `body` rule carries `padding: 0 20px;`.
 * That padding is a Theia-only deviation (modern VS Code uses `padding: 0`) and
 * insets webview content by 20px per side, so a webview sized to `100%` (the
 * Capibara Pet stage) renders 40px narrower than its panel.
 *
 * Runs after the copy plugin has written lib/webview/pre/main.js and rewrites
 * just that one declaration. Not a DI rebind, so if the literal moves it no-ops
 * loudly (warns) instead of failing the build.
 */
const webviewFullWidthPlugin = {
    name: 'undisclosed-webview-full-width',
    setup(build) {
        build.onEnd((result) => {
            if (result.errors.length) {
                return;
            }
            const target = path.join(__dirname, 'lib', 'webview', 'pre', 'main.js');
            if (!fs.existsSync(target)) {
                return;
            }
            const text = fs.readFileSync(target, 'utf8');
            if (!text.includes('padding: 0 20px;')) {
                // eslint-disable-next-line no-console
                console.warn(
                    '[undisclosed] webview full-width (B13): "padding: 0 20px;" not found in '
                    + 'lib/webview/pre/main.js — the transform may be obsolete or the upstream literal moved.'
                );
                return;
            }
            fs.writeFileSync(target, text.replace('padding: 0 20px;', 'padding: 0;'));
            // eslint-disable-next-line no-console
            console.log('[undisclosed] webview full-width (B13): rewrote padding in lib/webview/pre/main.js');
        });
    }
};

// Insert before the trailing compressAssetsPlugin so the rewrite runs AFTER the
// copy plugin's onEnd writes main.js, but before assets are compressed.
browserOptions.plugins.splice(browserOptions.plugins.length - 1, 0, webviewFullWidthPlugin);

const browserContext = await esbuild.context(browserOptions);
const nodeContext = await esbuild.context(nodeOptions);


if (watch) {
    await Promise.all([
        browserContext.watch(),
        nodeContext.watch(),
    ]);
} else {
    try {
        await browserContext.rebuild();
        await browserContext.dispose();
        await nodeContext.rebuild();
        await nodeContext.dispose();
    } catch {
        process.exit(1);
    }
}
