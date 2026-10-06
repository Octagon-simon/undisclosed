/**
 * This file can be edited to customize webpack configuration.
 * To reset delete this file and rerun theia build again.
 */
// @ts-check
const configs = require('./gen-webpack.config.js');
const nodeConfig = require('./gen-webpack.node.config.js');

/**
 * Webview "full width" fix.
 *
 * `theia build` copies @theia/plugin-ext's webview host (`.../webview/pre/*.js`)
 * into `lib/webview/pre`, which the backend serves at `/webview`. `main.js` there
 * injects a default stylesheet into every webview whose `body` rule carries
 * `padding: 0 20px;`. That padding is a Theia-only deviation (modern VS Code uses
 * `padding: 0`) and insets the webview content by 20px on each side, so a webview
 * that sizes itself to `100%` (e.g. the Capibara Pet stage) renders 40px narrower
 * than its panel.
 *
 * We rewrite just that one declaration as the asset is copied. See
 * docs/features/theia-overrides.md (B13) and docs/features/webview-blue-background.md.
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

module.exports = [
    ...configs,
    nodeConfig.config
];
