/**
 * Frontend module for the `undisclosed-languages` Theia extension.
 *
 * Besides the Monaco language registrations, this package also hosts the
 * native media preview (images / audio / video), which is why the bindings
 * below register a widget factory + open handler.
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import URI from '@theia/core/lib/common/uri';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { OpenHandler, WidgetFactory } from '@theia/core/lib/browser';
import { UndisclosedLanguagesContribution } from './undisclosed-languages-contribution';
import { MediaPreviewWidget, MediaPreviewWidgetOptions } from './media-preview/media-preview-widget';
import { MediaPreviewOpenHandler } from './media-preview/media-preview-open-handler';

export default new ContainerModule(bind => {
    bind(UndisclosedLanguagesContribution).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(UndisclosedLanguagesContribution);

    // Native media preview: a widget factory keyed by file URI plus an opener
    // that claims image/audio/video files ahead of the text editor.
    bind(MediaPreviewWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(context => ({
        id: MediaPreviewWidget.ID,
        createWidget: (options: MediaPreviewWidgetOptions) => {
            const widget = context.container.get<MediaPreviewWidget>(MediaPreviewWidget);
            widget.setInput(new URI(options.uri));
            return widget;
        }
    }));
    bind(MediaPreviewOpenHandler).toSelf().inSingletonScope();
    bind(OpenHandler).toService(MediaPreviewOpenHandler);
});
