/**
 * Opens images/audio/video in {@link MediaPreviewWidget}.
 *
 * Priority 500 is deliberately above `EditorManager`'s 100 (text editor) and
 * above the `vscode.media-preview` VS Code plugin's custom editor (~400), so
 * double-clicking a PNG lands in the native preview. The regular text editor
 * still appears under "Open With" for people who want to inspect the bytes.
 */
import { injectable } from '@theia/core/shared/inversify';
import URI from '@theia/core/lib/common/uri';
import { WidgetOpenHandler, WidgetOpenerOptions } from '@theia/core/lib/browser/widget-open-handler';
import { MediaPreviewWidget, MediaPreviewWidgetOptions } from './media-preview-widget';
import { mediaTypeOf } from './media-types';

export const MEDIA_PREVIEW_PRIORITY = 500;

@injectable()
export class MediaPreviewOpenHandler extends WidgetOpenHandler<MediaPreviewWidget> {

    readonly id = MediaPreviewWidget.ID;

    canHandle(uri: URI, _options?: WidgetOpenerOptions): number {
        return mediaTypeOf(uri) ? MEDIA_PREVIEW_PRIORITY : -1;
    }

    protected createWidgetOptions(uri: URI, _options?: WidgetOpenerOptions): MediaPreviewWidgetOptions {
        return { uri: uri.withoutFragment().toString() };
    }
}
