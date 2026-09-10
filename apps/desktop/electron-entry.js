// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Electron main ENTRY WRAPPER (package.json "main").
//
// Theia's plugin deployer only deploys LOCAL plugins named in
// THEIA_DEFAULT_PLUGINS / THEIA_PLUGINS / --plugins (see plugin-deployer-impl.js:
// there is NO relative-"plugins"-dir fallback). In dev, `theia start` arranges
// this; a packaged Electron app does NOT. We bundle the VS Code builtin language
// servers under <app>/plugins (electron-builder `files`), so without this the
// shipped app has zero language intelligence — Cmd+Click / go-to-definition /
// references / hover all silently do nothing even though the plugins are present.
//
// Point the deployer at the bundled dir BEFORE requiring the generated main (so
// the deployer, which runs early in the forked backend, inherits it). Set only
// if unset, so an explicit override still wins.
const path = require('path');

if (!process.env.THEIA_DEFAULT_PLUGINS) {
  // This file sits at the app root (Resources/app) in the packaged app, next to
  // the bundled `plugins/` dir (matches THEIA_APP_PROJECT_PATH the generated
  // main derives as resolve(lib/backend, '..', '..')).
  const pluginsDir = path.resolve(__dirname, 'plugins');
  process.env.THEIA_DEFAULT_PLUGINS = `local-dir:${pluginsDir}`;
}

require('./lib/backend/electron-main.js');
