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
        let element: HTMLElement;
        if (kind === 'image') {
            const img = document.createElement('img');
            img.src = url;
            img.alt = name;
            img.draggable = false;
            element = img;
        } else if (kind === 'audio') {
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
