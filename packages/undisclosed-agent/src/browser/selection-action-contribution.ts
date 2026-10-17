// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  FrontendApplicationContribution,
} from '@theia/core/lib/browser';
import { CommandRegistry } from '@theia/core/lib/common';
import {
  Disposable,
  DisposableCollection,
} from '@theia/core/lib/common/disposable';
import { EditorManager, EditorWidget } from '@theia/editor/lib/browser';
import { UNDISCLOSED_SEND_SELECTION_COMMAND_ID } from './undisclosed-agent-contribution';

const BUTTON_CLASS = 'undisclosed-selection-action';
const STYLE_ID = 'undisclosed-selection-action-style';
const SHOW_DELAY_MS = 140;
const EDGE_GAP_PX = 8;
const GAP_AFTER_TEXT_PX = 12;

/** Minimal shape of the Monaco control we need; avoids a hard Monaco import. */
interface MonacoControl {
  getDomNode(): HTMLElement;
  getScrolledVisiblePosition(position: {
    lineNumber: number;
    column: number;
  }): { top: number; left: number; height: number } | null;
  getLayoutInfo?(): { contentLeft: number; contentWidth: number };
  getModel?(): { getLineMaxColumn(lineNumber: number): number } | null;
  onMouseUp?(listener: () => void): Disposable;
  onKeyUp?(listener: () => void): Disposable;
}

/**
 * Floating "Send to Agent" action shown next to a non-empty editor selection.
 * Replaces the old editor context-menu entry: select code, click the button,
 * and the composer receives a file + line-range pill.
 */
@injectable()
export class UndisclosedSelectionActionContribution
  implements FrontendApplicationContribution
{
  @inject(EditorManager)
  protected readonly editorManager!: EditorManager;

  @inject(CommandRegistry)
  protected readonly commands!: CommandRegistry;

  protected button: HTMLButtonElement | undefined;
  protected showTimer: number | undefined;
  protected resizeObserver: ResizeObserver | undefined;
  protected observedControl: MonacoControl | undefined;
  protected readonly globalSubscriptions = new DisposableCollection();
  protected readonly editorSubscriptions = new DisposableCollection();
  protected currentEditor: EditorWidget | undefined;

  protected readonly onDocumentMouseDown = (event: MouseEvent): void => {
    if (
      this.button &&
      event.target instanceof Node &&
      !this.button.contains(event.target)
    ) {
      this.hide();
    }
  };

  protected readonly onDocumentKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') this.hide();
  };

  onStart(): void {
    this.installStyles();
    this.globalSubscriptions.push(
      this.editorManager.onCurrentEditorChanged((editor) => this.attach(editor))
    );
    this.attach(this.editorManager.currentEditor);
    document.addEventListener('mousedown', this.onDocumentMouseDown, true);
    document.addEventListener('keydown', this.onDocumentKeyDown, true);
  }

  onStop(): void {
    this.globalSubscriptions.dispose();
    this.editorSubscriptions.dispose();
    this.disconnectResizeObserver();
    document.removeEventListener('mousedown', this.onDocumentMouseDown, true);
    document.removeEventListener('keydown', this.onDocumentKeyDown, true);
    this.clearShowTimer();
    this.button?.remove();
    this.button = undefined;
  }

  protected attach(editor: EditorWidget | undefined): void {
    this.editorSubscriptions.dispose();
    this.disconnectResizeObserver();
    this.hide();
    this.currentEditor = editor;
    if (!editor) return;

    this.editorSubscriptions.pushAll([
      editor.editor.onSelectionChanged(() => this.scheduleShow()),
      editor.editor.onScrollChanged(() => this.scheduleShow()),
      editor.editor.onFocusChanged((focused) => {
        if (!focused) this.hide();
        else this.scheduleShow();
      }),
    ]);

    const control = this.control(editor);
    if (control?.onMouseUp) {
      this.editorSubscriptions.push(
        control.onMouseUp(() => this.scheduleShow(0))
      );
    }
    if (control?.onKeyUp) {
      this.editorSubscriptions.push(control.onKeyUp(() => this.scheduleShow(0)));
    }
    this.scheduleShow();
  }

  protected scheduleShow(delay = SHOW_DELAY_MS): void {
    this.clearShowTimer();
    this.showTimer = window.setTimeout(() => {
      this.showTimer = undefined;
      this.update();
    }, delay);
  }

  protected clearShowTimer(): void {
    if (this.showTimer !== undefined) {
      window.clearTimeout(this.showTimer);
      this.showTimer = undefined;
    }
  }

  protected update(): void {
    const editor = this.currentEditor;
    if (!editor || editor.isDisposed) {
      this.hide();
      return;
    }
    if (!this.hasSelection(editor)) {
      this.hide();
      return;
    }
    const control = this.control(editor);
    if (!control || typeof control.getScrolledVisiblePosition !== 'function') {
      this.hide();
      return;
    }
    const selection = editor.editor.selection;
    const firstLine = Math.min(selection.start.line, selection.end.line) + 1;
    const lineMaxColumn =
      control.getModel?.()?.getLineMaxColumn(firstLine) ?? 1;
    const anchor = control.getScrolledVisiblePosition({
      lineNumber: firstLine,
      column: lineMaxColumn,
    });
    if (!anchor) {
      this.hide();
      return;
    }

    this.observeControl(control);

    const button = this.ensureButton();
    button.style.visibility = 'hidden';
    button.style.display = 'inline-flex';

    const domRect = control.getDomNode().getBoundingClientRect();
    const width = button.offsetWidth || 116;
    const height = button.offsetHeight || 24;
    // A line scrolled past the viewport edge has no meaningful anchor; clamping
    // it would pin the pill to the edge and detach it from the selection.
    if (anchor.top < 0 || anchor.top > domRect.height - height) {
      this.hide();
      return;
    }
    const layout = control.getLayoutInfo?.();
    const contentLeft = layout
      ? domRect.left + layout.contentLeft
      : domRect.left;
    const contentRight = layout
      ? contentLeft + layout.contentWidth
      : domRect.right;
    // Sit immediately right of the FIRST selected line's text, then clamp into
    // the text area so a long line or a narrow editor can't push it off-screen.
    const left = Math.min(
      Math.max(
        domRect.left + anchor.left + GAP_AFTER_TEXT_PX,
        contentLeft + EDGE_GAP_PX
      ),
      Math.max(contentLeft + EDGE_GAP_PX, contentRight - width - EDGE_GAP_PX)
    );
    const top = Math.max(
      EDGE_GAP_PX,
      Math.min(
        domRect.top + anchor.top + (anchor.height - height) / 2,
        window.innerHeight - height - EDGE_GAP_PX
      )
    );

    button.style.left = `${Math.round(left)}px`;
    button.style.top = `${Math.round(top)}px`;
    button.style.visibility = 'visible';
  }

  protected observeControl(control: MonacoControl): void {
    if (this.observedControl === control) return;
    this.disconnectResizeObserver();
    this.observedControl = control;
    if (typeof ResizeObserver === 'undefined') return;
    // Opening/closing the agent panel resizes the editor without a scroll or
    // selection event, which used to leave the pill at the old layout position.
    this.resizeObserver = new ResizeObserver(() => this.scheduleShow(0));
    this.resizeObserver.observe(control.getDomNode());
  }

  protected disconnectResizeObserver(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = undefined;
    this.observedControl = undefined;
  }

  protected hasSelection(editor: EditorWidget): boolean {
    const { start, end } = editor.editor.selection;
    if (start.line === end.line && start.character === end.character) {
      return false;
    }
    const text = editor.editor.document.getText(editor.editor.selection);
    return text.trim().length > 0;
  }

  protected control(editor: EditorWidget): MonacoControl | undefined {
    const candidate = editor.editor as unknown as {
      getControl?: () => MonacoControl;
    };
    try {
      return candidate.getControl?.();
    } catch {
      return undefined;
    }
  }

  protected ensureButton(): HTMLButtonElement {
    if (this.button) return this.button;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = BUTTON_CLASS;
    button.title = 'Send selection to Agent';
    button.setAttribute('aria-label', 'Send selection to Agent');
    button.innerHTML = `
      <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
        <path d="M8 1.5l1.45 3.55L13 6.5l-3.55 1.45L8 11.5 6.55 7.95 3 6.5l3.55-1.45L8 1.5z"
          fill="currentColor"/>
        <path d="M12.5 10.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z"
          fill="currentColor"/>
      </svg>
      <span>Send to Agent</span>`;
    // Keep the editor selection alive: without this the button steals focus
    // and the command runs against an empty selection.
    button.addEventListener('mousedown', (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.hide();
      void this.commands.executeCommand(
        UNDISCLOSED_SEND_SELECTION_COMMAND_ID
      );
    });
    document.body.appendChild(button);
    this.button = button;
    return button;
  }

  protected hide(): void {
    this.clearShowTimer();
    if (this.button) this.button.style.display = 'none';
  }

  protected installStyles(): void {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
.${BUTTON_CLASS} {
  position: fixed;
  z-index: 100000;
  display: none;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid var(--theia-editorWidget-border, var(--theia-contrastBorder, rgba(127, 127, 127, 0.35)));
  background: var(--theia-editorWidget-background, var(--theia-sideBar-background, #ffffff));
  color: var(--theia-editorWidget-foreground, var(--theia-foreground, #1f1f1f));
  font-family: var(--theia-ui-font-family, system-ui, sans-serif);
  font-size: 11px;
  line-height: 1;
  font-weight: 500;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
  cursor: pointer;
  user-select: none;
}
.${BUTTON_CLASS}:hover {
  background: var(--theia-toolbar-hoverBackground, var(--theia-list-hoverBackground, rgba(127, 127, 127, 0.14)));
}
.${BUTTON_CLASS} svg {
  color: var(--theia-textLink-foreground, var(--theia-focusBorder, #3b82f6));
  flex-shrink: 0;
}`;
    document.head.appendChild(style);
  }
}
