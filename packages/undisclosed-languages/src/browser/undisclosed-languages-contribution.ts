/**
 * Registers the popular languages with Theia's Monaco instance at startup.
 *
 * Each language gets:
 *  1. A Monaco language contribution (`monaco.languages.register`) so the editor
 *     knows the language id, aliases and file associations.
 *  2. A Monarch tokenizer (`monaco.languages.setMonarchTokensProvider`) for
 *     syntax highlighting.
 *  3. A language configuration (`monaco.languages.setLanguageConfiguration`)
 *     for comments, auto-closing brackets, indentation rules, folding, etc.
 */
import { injectable } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import * as monaco from '@theia/monaco-editor-core';
import { LANGUAGE_DESCRIPTORS, LanguageDescriptor } from '../languages';
// Pull every vendored tokenizer as `<module>Conf` / `<module>Language` from the
// generated registry, so adding a language only means editing generate.js +
// languages.ts — no per-language import/Map entry to keep in sync here.
import * as generated from '../generated';

type LanguagePair = {
    conf: monaco.languages.LanguageConfiguration;
    // The vendored Monarch tokenizers are untyped: several rely on rule shapes
    // looser than Theia's `IMonarchLanguage` (e.g. single-element rules), so we
    // keep them as `any`. `setMonarchTokensProvider` accepts them fine.
    language: any;
};

@injectable()
export class UndisclosedLanguagesContribution implements FrontendApplicationContribution {

    initialize(): void {
        this.registerAll();
    }

    protected registerAll(): void {
        for (const descriptor of LANGUAGE_DESCRIPTORS) {
            this.doRegister(descriptor);
        }
    }

    /** Look up the vendored `{ conf, language }` for a descriptor's module. */
    protected pairFor(module: string): LanguagePair | undefined {
        const registry = generated as Record<string, unknown>;
        const conf = registry[`${module}Conf`] as
            | monaco.languages.LanguageConfiguration
            | undefined;
        const language = registry[`${module}Language`];
        if (!conf && !language) {
            return undefined;
        }
        return { conf: conf as monaco.languages.LanguageConfiguration, language };
    }

    protected doRegister(descriptor: LanguageDescriptor): void {
        const pair = this.pairFor(descriptor.module);
        if (!pair) {
            return;
        }
        const { id, aliases, extensions, mimetypes, firstLine } = descriptor;

        // 1) Monaco language contribution (id, aliases, file associations).
        monaco.languages.register({ id, extensions, aliases, mimetypes, firstLine });
        // 2) Syntax highlighting tokenizer.
        monaco.languages.setMonarchTokensProvider(id, pair.language);
        // 3) Language configuration (comments, brackets, indentation, folding).
        if (pair.conf) {
            monaco.languages.setLanguageConfiguration(id, pair.conf);
        }
    }
}
