/**
 * Frontend module for the `eigent-languages` Theia extension.
 */
import { ContainerModule } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { EigentLanguagesContribution } from './eigent-languages-contribution';

export default new ContainerModule(bind => {
    bind(EigentLanguagesContribution).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(EigentLanguagesContribution);
});
