/**
 * Frontend module for the `undisclosed-languages` Theia extension.
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { UndisclosedLanguagesContribution } from './undisclosed-languages-contribution';

export default new ContainerModule(bind => {
    bind(UndisclosedLanguagesContribution).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(UndisclosedLanguagesContribution);
});
