/**
 * Native media preview widget.
 *
 * Renders images, audio and video straight from the workspace file system:
 * read the bytes through Theia's `FileService`, wrap them in a Blob, and hand
 * the Blob URL to `<img>` / `<audio>` / `<video>`. No webview is involved, so
 * it is not affected by the (broken) `theia-resource` URL plumbing that makes
 * the `vscode.media-preview` plugin fail with "An error occurred while loading
 * the image." It works identically on the browser and Electron builds.
 */
import { inject, injectable } from '@theia/core/shared/inversify';
import URI from '@theia/core/lib/common/uri';
import { BaseWidget } from '@theia/core/lib/browser/widgets/widget';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { MediaKind, mediaTypeOf } from './media-types';

export interface MediaPreviewWidgetOptions {
    readonly uri: string;
}

@injectable()
export class MediaPreviewWidget extends BaseWidget {

    static readonly ID = 'undisclosed-media-preview';
    static readonly LABEL = 'Media Preview';

    @inject(FileService)
    protected readonly fileService!: FileService;

    protected uri: URI | undefined;
    protected objectUrl: string | undefined;
    /** Guards against re-loading the same file on every attach. */
    protected loadedUri: string | undefined;

    constructor() {
        super();
        this.id = MediaPreviewWidget.ID;
        this.title.label = MediaPreviewWidget.LABEL;
        this.title.closable = true;
        this.title.caption = MediaPreviewWidget.LABEL;
        this.node.tabIndex = 0;
        // Base class the stylesheet keys off. Without it the layout/clip rules
        // (`.undisclosed-media-preview…`) never matched, so a zoomed image had
        // no `overflow:hidden` container and spilled past the editor canvas.
        this.addClass('undisclosed-media-preview');
        // Suppress the browser/Electron NATIVE pinch-zoom (trackpad pinch fires
        // `wheel` with ctrlKey in Chromium; the OS gesture would scale the whole
        // renderer, escaping our clip box). Capture-phase + preventDefault stops
        // it before Chromium zooms; the image viewer's own wheel handler still
        // drives our transform zoom. Scoped to this widget only.
        this.node.addEventListener(
            'wheel',
            (e: WheelEvent) => {
                if (e.ctrlKey) {
                    e.preventDefault();
                }
            },
            { capture: true, passive: false }
        );
    }

    /** Set the file this widget previews. Safe to call before the widget is attached. */
    setInput(uri: URI): void {
        this.uri = uri;
        // Give every file its own widget id so opening two images gives two tabs
        // instead of reusing one.
        this.id = `${MediaPreviewWidget.ID}::${uri.toString()}`;
        this.title.label = uri.path.base;
        this.title.caption = uri.path.toString();
        void this.load();
    }

    protected override onActivateRequest(): void {
        this.node.focus();
    }

    /** Read the file and render it. Re-entrant calls for the same URI are ignored. */
    protected async load(): Promise<void> {
        const uri = this.uri;
        if (!uri) {
            return;
        }
        const descriptor = mediaTypeOf(uri);
        if (!descriptor) {
            this.showMessage(`No preview available for ${uri.path.base}.`);
            return;
        }
        const key = uri.toString();
        this.loadedUri = key;
        this.setKindClass(descriptor.kind);
        this.showMessage('Loading\u2026');

        try {
            const content = await this.fileService.readFile(uri);
            if (this.loadedUri !== key) {
                // A different file was requested while we were reading.
                return;
            }
            this.revokeObjectUrl();
            const blob = new Blob([content.value.buffer], { type: descriptor.mime });
            const url = URL.createObjectURL(blob);
            this.objectUrl = url;
            this.renderMedia(descriptor.kind, url, uri.path.base);
        } catch (error) {
            if (this.loadedUri !== key) {
                return;
            }
            const detail = error instanceof Error ? error.message : String(error);
            this.showError(`Failed to open ${uri.path.base}: ${detail}`);
        }
    }

    protected renderMedia(kind: MediaKind, url: string, name: string): void {
        this.node.textContent = '';
        if (kind === 'image') {
            this.renderImage(url, name);
            return;
        }
        let element: HTMLElement;
        if (kind === 'audio') {
            const audio = document.createElement('audio');
            audio.src = url;
            audio.controls = true;
            audio.autoplay = false;
            element = audio;
        } else {
            const video = document.createElement('video');
            video.src = url;
            video.controls = true;
            video.autoplay = false;
            element = video;
        }
        this.node.appendChild(element);
    }

    /**
     * Interactive image viewer. Zoom is done by SIZING THE IMAGE IN PIXELS
     * inside a scroll container (NOT a CSS transform): an oversized in-flow
     * image in an `overflow:auto` box is physically bounded by that box, so it
     * can never spill past the editor canvas (a transform can). Wheel zooms
     * toward the cursor, drag pans, click toggles fit <-> 100%, +/-/0 keys.
     */
    protected renderImage(url: string, name: string): void {
        const MIN = 0.05;
        const MAX = 40;
        let scale = 1;      // natural-size multiplier (1 == 100% actual pixels)
        let fitMode = true; // image scaled to fit the viewport

        const viewport = document.createElement('div');
        viewport.className = 'undisclosed-media-image-viewport';

        const img = document.createElement('img');
        img.src = url;
        img.alt = name;
        img.draggable = false;
        img.className = 'undisclosed-media-image';
        viewport.appendChild(img);

        const bar = document.createElement('div');
        bar.className = 'undisclosed-media-image-bar';
        const mkBtn = (label: string, title: string, on: () => void): HTMLButtonElement => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.title = title;
            b.className = 'undisclosed-media-image-btn';
            b.addEventListener('click', e => { e.stopPropagation(); on(); });
            return b;
        };
        const pct = document.createElement('span');
        pct.className = 'undisclosed-media-image-pct';

        // The fit scale = how much the browser shrank the image to fit, so % is
        // honest. Measured while in fit mode.
        let fitScale = 1;
        const measureFit = (): void => {
            if (img.naturalWidth && img.clientWidth) {
                fitScale = img.clientWidth / img.naturalWidth;
            }
        };

        const apply = (): void => {
            if (fitMode) {
                // Let CSS (max-width/height:100%) size it; clear explicit px.
                img.style.width = '';
                img.style.height = '';
                img.classList.add('fit');
                viewport.style.overflow = 'hidden';
                img.style.cursor = 'zoom-in';
                measureFit();
                pct.textContent = `${Math.round(fitScale * 100)}%`;
                return;
            }
            img.classList.remove('fit');
            // Explicit pixel size == natural * scale. In-flow, so the scroll
            // container clips + scrolls it; it cannot escape the viewport box.
            img.style.width = `${Math.round(img.naturalWidth * scale)}px`;
            img.style.height = 'auto';
            viewport.style.overflow = 'auto';
            img.style.cursor = 'grab';
            pct.textContent = `${Math.round(scale * 100)}%`;
        };

        const setScale = (next: number, cx?: number, cy?: number): void => {
            const clamped = Math.min(MAX, Math.max(MIN, next));
            const prev = scale;
            const wasFit = fitMode;
            fitMode = false;
            scale = clamped;
            // Keep the point under the cursor stable: adjust scroll by how much
            // that point moved when the image resized.
            const rect = viewport.getBoundingClientRect();
            const px = cx !== undefined ? cx - rect.left : rect.width / 2;
            const py = cy !== undefined ? cy - rect.top : rect.height / 2;
            const baseScale = wasFit ? fitScale : prev;
            const ratio = clamped / baseScale;
            apply();
            viewport.scrollLeft = (viewport.scrollLeft + px) * ratio - px;
            viewport.scrollTop = (viewport.scrollTop + py) * ratio - py;
        };

        const reset = (): void => { fitMode = true; scale = 1; apply(); };

        viewport.addEventListener('wheel', e => {
            e.preventDefault();
            const base = fitMode ? fitScale : scale;
            const factor = Math.exp(-e.deltaY * 0.0015);
            setScale(base * factor, e.clientX, e.clientY);
        }, { passive: false });

        // Click toggles fit <-> 100% (unless it was a drag).
        let moved = false;
        img.addEventListener('click', () => {
            if (moved) { return; }
            if (fitMode) { setScale(1); } else { reset(); }
        });

        // Drag to pan via the scroll container.
        let dragging = false;
        let sx = 0, sy = 0;
        img.addEventListener('pointerdown', e => {
            if (fitMode) { return; }
            dragging = true; moved = false;
            sx = e.clientX; sy = e.clientY;
            img.setPointerCapture(e.pointerId);
            img.style.cursor = 'grabbing';
        });
        img.addEventListener('pointermove', e => {
            if (!dragging) { return; }
            const dx = e.clientX - sx, dy = e.clientY - sy;
            if (Math.abs(dx) + Math.abs(dy) > 3) { moved = true; }
            sx = e.clientX; sy = e.clientY;
            viewport.scrollLeft -= dx;
            viewport.scrollTop -= dy;
        });
        const endDrag = (e: PointerEvent): void => {
            if (!dragging) { return; }
            dragging = false;
            try { img.releasePointerCapture(e.pointerId); } catch { /* released */ }
            img.style.cursor = 'grab';
            setTimeout(() => (moved = false), 0);
        };
        img.addEventListener('pointerup', endDrag);
        img.addEventListener('pointercancel', endDrag);

        this.node.addEventListener('keydown', e => {
            const base = fitMode ? fitScale : scale;
            if (e.key === '+' || e.key === '=') { setScale(base * 1.2); }
            else if (e.key === '-' || e.key === '_') { setScale(base / 1.2); }
            else if (e.key === '0') { reset(); }
        });

        bar.appendChild(mkBtn('−', 'Zoom out (-)', () => setScale((fitMode ? fitScale : scale) / 1.2)));
        bar.appendChild(mkBtn('↺', 'Reset / fit (0)', reset));
        bar.appendChild(mkBtn('+', 'Zoom in (+)', () => setScale((fitMode ? fitScale : scale) * 1.2)));
        bar.appendChild(pct);

        img.addEventListener('load', () => { measureFit(); apply(); });
        this.node.appendChild(viewport);
        this.node.appendChild(bar);
        apply();
    }

    protected showMessage(text: string): void {
        this.renderMessage(text, false);
    }

    protected showError(text: string): void {
        this.renderMessage(text, true);
    }

    protected renderMessage(text: string, isError: boolean): void {
        this.node.textContent = '';
        const message = document.createElement('div');
        message.className = 'undisclosed-media-preview-message';
        if (isError) {
            message.classList.add('undisclosed-media-preview-error');
        }
        message.textContent = text;
        this.node.appendChild(message);
    }

    protected setKindClass(kind: MediaKind): void {
        this.removeClass('undisclosed-media-preview-image');
        this.removeClass('undisclosed-media-preview-audio');
        this.removeClass('undisclosed-media-preview-video');
        this.addClass(`undisclosed-media-preview-${kind}`);
    }

    protected revokeObjectUrl(): void {
        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = undefined;
        }
    }

    override dispose(): void {
        this.revokeObjectUrl();
        super.dispose();
    }
}
