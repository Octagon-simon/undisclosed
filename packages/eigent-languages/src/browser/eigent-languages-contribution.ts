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
import { conf as javascriptConf, language as javascriptLang } from '../generated/javascript';
import { conf as typescriptConf, language as typescriptLang } from '../generated/typescript';
import { conf as pythonConf, language as pythonLang } from '../generated/python';
import { conf as javaConf, language as javaLang } from '../generated/java';
import { conf as cppConf, language as cppLang } from '../generated/cpp';
import { conf as csharpConf, language as csharpLang } from '../generated/csharp';
import { conf as goConf, language as goLang } from '../generated/go';
import { conf as rustConf, language as rustLang } from '../generated/rust';
import { conf as rubyConf, language as rubyLang } from '../generated/ruby';
import { conf as phpConf, language as phpLang } from '../generated/php';
import { conf as htmlConf, language as htmlLang } from '../generated/html';
import { conf as cssConf, language as cssLang } from '../generated/css';
import { conf as sqlConf, language as sqlLang } from '../generated/sql';
import { conf as shellConf, language as shellLang } from '../generated/shell';

type LanguagePair = {
    conf: monaco.languages.LanguageConfiguration;
    // The vendored Monarch tokenizers are untyped: several rely on rule shapes
    // looser than Theia's `IMonarchLanguage` (e.g. single-element rules), so we
    // keep them as `any`. `setMonarchTokensProvider` accepts them fine.
    language: any;
};

@injectable()
export class EigentLanguagesContribution implements FrontendApplicationContribution {

    protected readonly languages = new Map<string, LanguagePair>([
        ['javascript', { conf: javascriptConf, language: javascriptLang }],
        ['typescript', { conf: typescriptConf, language: typescriptLang }],
        ['python', { conf: pythonConf, language: pythonLang }],
        ['java', { conf: javaConf, language: javaLang }],
        ['cpp', { conf: cppConf, language: cppLang }],
        ['csharp', { conf: csharpConf, language: csharpLang }],
        ['go', { conf: goConf, language: goLang }],
        ['rust', { conf: rustConf, language: rustLang }],
        ['ruby', { conf: rubyConf, language: rubyLang }],
        ['php', { conf: phpConf, language: phpLang }],
        ['html', { conf: htmlConf, language: htmlLang }],
        ['css', { conf: cssConf, language: cssLang }],
        ['sql', { conf: sqlConf, language: sqlLang }],
        ['shell', { conf: shellConf, language: shellLang }]
    ]);

    initialize(): void {
        this.registerAll();
    }

    protected registerAll(): void {
        for (const descriptor of LANGUAGE_DESCRIPTORS) {
            this.doRegister(descriptor);
        }
    }

    protected doRegister(descriptor: LanguageDescriptor): void {
        const pair = this.languages.get(descriptor.module);
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
