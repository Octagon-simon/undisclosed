// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/** HTTP route (served by the backend module) that reports a detected VS Code
 *  install's settings + extensions for import. */
export const VSCODE_IMPORT_ROUTE = '/undisclosed-import/vscode';

/** What the backend reports about a detected VS Code install. */
export interface VscodeImportData {
  /** True when a VS Code (or variant) user directory was found. */
  found: boolean;
  /** Which variant was detected, e.g. "Code", "Code - Insiders", "VSCodium". */
  variant?: string;
  /** The resolved User directory the data came from. */
  userDir?: string;
  /** Parsed settings.json (JSONC tolerated). Empty object when absent. */
  settings: Record<string, unknown>;
  /** Installed extension ids ("publisher.name"). */
  extensions: string[];
}
