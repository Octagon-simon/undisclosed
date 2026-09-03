// The absolute path of the folder currently open in the host editor (Theia).
// The agent-embed mount receives it as `config.workspaceRoot`; we stash it here
// so the chat-start request can ALWAYS forward it as `space_root_path`,
// independent of the (sometimes wrong / rootless) active Space. This guarantees
// the agent operates in the open folder instead of the legacy per-task dir.

let openFolderRoot: string | undefined;

export function setOpenFolderRoot(root: string | undefined | null): void {
  const normalized =
    typeof root === 'string' && root.trim() ? root.replace(/\/+$/, '') : undefined;
  openFolderRoot = normalized;
}

export function getOpenFolderRoot(): string | undefined {
  return openFolderRoot;
}
