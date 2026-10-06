/**
 * This file can be edited to customize webpack configuration.
 * To reset delete this file and rerun theia build again.
 */
// @ts-check
const configs = require('./gen-webpack.config.js');
const nodeConfig = require('./gen-webpack.node.config.js');

/**
 * Webview "full width" fix (same as the repo-root webpack.config.js).
 *
 * `theia build` copies @theia/plugin-ext's webview host into `lib/webview/pre`,
 * served by the backend at `/webview`. `main.js` injects `body { padding: 0 20px }`
 * into every webview; that Theia-only padding (VS Code uses `padding: 0`) insets
 * webview content by 20px per side, so self-sizing webviews (Capibara Pet stage)
 * render 40px narrower than their panel. Rewrite the declaration during copy.
 */
function applyWebviewFullWidth(configs) {
    for (const config of configs) {
        for (const plugin of (config.plugins || [])) {
            if (!Array.isArray(plugin.patterns)) {
                continue;
            }
            for (const pattern of plugin.patterns) {
                if (typeof pattern.from !== 'string' || !/[\\/]webview[\\/]pre$/.test(pattern.from)) {
                    continue;
                }
                const previous = pattern.transform;
                pattern.transform = (content, absoluteFrom) => {
                    const text = content.toString();
                    const next = absoluteFrom.endsWith('main.js') && text.includes('padding: 0 20px;')
                        ? text.replace('padding: 0 20px;', 'padding: 0;')
                        : text;
                    if (!previous) {
                        return next;
                    }
                    return typeof previous === 'function' ? previous(next, absoluteFrom) : previous.transformer(next, absoluteFrom);
                };
            }
        }
    }
}
applyWebviewFullWidth(configs);

/**
 * Expose bundled modules on window.theia.moduleName namespace, e.g.
 * window['theia']['@theia/core/lib/common/uri'].
 * Such syntax can be used by external code, for instance, for testing.
configs[0].module.rules.push({
    test: /\.js$/,
    loader: require.resolve('@theia/application-manager/lib/expose-loader')
}); */

const all = [...configs, nodeConfig.config];

// Deduplicate @theia/core. The undisclosed-* extensions are `file:`-linked
// (symlinks in node_modules). By default webpack follows the symlink and
// resolves THEIR `@theia/core` from the repo-root node_modules — a SECOND copy
// distinct from apps/desktop/node_modules/@theia/core. Two copies means two
// singletons: `index.js` sets FrontendApplicationConfigProvider on one, the app
// reads the other → "The configuration is not set" and the frontend never
// starts (blank spinner). Not following symlinks makes linked packages resolve
// their deps from apps/desktop/node_modules, so there's a single @theia/core.
for (const c of all) {
    c.resolve = c.resolve || {};
    c.resolve.symlinks = false;
}

module.exports = all;
