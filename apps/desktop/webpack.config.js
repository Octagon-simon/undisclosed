/**
 * This file can be edited to customize webpack configuration.
 * To reset delete this file and rerun theia build again.
 */
// @ts-check
const configs = require('./gen-webpack.config.js');
const nodeConfig = require('./gen-webpack.node.config.js');

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
