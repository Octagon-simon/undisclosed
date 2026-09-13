/**
 * Media type registry for the native media preview.
 *
 * Maps a file extension to the render kind (image/audio/video) and the MIME type
 * we hand to the browser via a Blob URL. Kept as plain data so the OpenHandler
 * (`canHandle`) and the widget (`render`) agree on exactly which extensions are
 * previewed and how.
 */
import URI from '@theia/core/lib/common/uri';

export type MediaKind = 'image' | 'audio' | 'video';

export interface MediaTypeDescriptor {
    readonly kind: MediaKind;
    readonly mime: string;
}

const IMAGE_TYPES: Record<string, string> = {
    png: 'image/png',
    apng: 'image/apng',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    jpe: 'image/jpeg',
    gif: 'image/gif',
    webp: 'image/webp',
    bmp: 'image/bmp',
    ico: 'image/x-icon',
    cur: 'image/x-icon',
    avif: 'image/avif',
    svg: 'image/svg+xml',
    tif: 'image/tiff',
    tiff: 'image/tiff'
};

const AUDIO_TYPES: Record<string, string> = {
    mp3: 'audio/mpeg',
    wav: 'audio/wav',
    wave: 'audio/wav',
    ogg: 'audio/ogg',
    oga: 'audio/ogg',
    opus: 'audio/ogg',
    m4a: 'audio/mp4',
    aac: 'audio/aac',
    flac: 'audio/flac'
};

const VIDEO_TYPES: Record<string, string> = {
    mp4: 'video/mp4',
    m4v: 'video/x-m4v',
    webm: 'video/webm',
    ogv: 'video/ogg',
    mov: 'video/quicktime'
};

/** The lower-cased extension of a URI path, without the leading dot. */
export function extensionOf(uri: URI): string {
    return uri.path.ext.toLowerCase().replace(/^\./, '');
}

/** Resolve the media descriptor for a URI, or `undefined` if we can't preview it. */
export function mediaTypeOf(uri: URI): MediaTypeDescriptor | undefined {
    const ext = extensionOf(uri);
    if (ext in IMAGE_TYPES) {
        return { kind: 'image', mime: IMAGE_TYPES[ext] };
    }
    if (ext in AUDIO_TYPES) {
        return { kind: 'audio', mime: AUDIO_TYPES[ext] };
    }
    if (ext in VIDEO_TYPES) {
        return { kind: 'video', mime: VIDEO_TYPES[ext] };
    }
    return undefined;
}

/** All extensions the preview can handle, used for diagnostics/tests. */
export function supportedExtensions(): string[] {
    return [
        ...Object.keys(IMAGE_TYPES),
        ...Object.keys(AUDIO_TYPES),
        ...Object.keys(VIDEO_TYPES)
    ];
}
