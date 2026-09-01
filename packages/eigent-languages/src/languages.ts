/**
 * Registration metadata for the popular languages supported by Eigent's editor.
 *
 * The `conf` and `language` (Monarch tokenizer) payloads live in the generated
 * modules under `src/generated` (see `script/generate.js`). This table maps each
 * language to the Monaco `ILanguageExtensionPoint` used to register it.
 */
import * as monaco from '@theia/monaco-editor-core';

export interface LanguageDescriptor extends monaco.languages.ILanguageExtensionPoint {
    /** Name of the generated module under src/generated. */
    module: string;
}

// The "start string" of the .ts source that will be used for the generated language metadata.
export const LANGUAGE_DESCRIPTORS: LanguageDescriptor[] = [
    { module: 'javascript', id: 'javascript', aliases: ['JavaScript', 'js', 'node'], extensions: ['.js', '.es6', '.mjs', '.cjs'], mimetypes: ['text/javascript'] },
    { module: 'typescript', id: 'typescript', aliases: ['TypeScript', 'ts', 'tsx'], extensions: ['.ts', '.tsx', '.mts', '.cts'] },
    { module: 'python', id: 'python', aliases: ['Python', 'py'], extensions: ['.py', '.pyw', '.rpy', '.cpy', '.gyp', '.gypi'], firstLine: '^#!/.*\\bpython[0-9.-]*\\b' },
    { module: 'java', id: 'java', aliases: ['Java'], extensions: ['.java', '.jav'], firstLine: '^package' },
    { module: 'cpp', id: 'cpp', aliases: ['C++'], extensions: ['.cpp', '.hh', '.cc', '.cxx', '.hpp', '.hxx', '.h', '.inl', '.ino'] },
    { module: 'csharp', id: 'csharp', aliases: ['C#', 'cs'], extensions: ['.cs', '.csx', '.cake'], firstLine: '^#!\\s*/.*\\bcsharp\\b' },
    { module: 'go', id: 'go', aliases: ['Go'], extensions: ['.go'], firstLine: '^\\s*(//.*)?package\\s+[a-zA-Z_]' },
    { module: 'rust', id: 'rust', aliases: ['Rust'], extensions: ['.rs'] },
    { module: 'ruby', id: 'ruby', aliases: ['Ruby'], extensions: ['.rb', '.rbx', '.rjs', '.gemspec', '.pp'], firstLine: '^#!/.*\\bruby\\b' },
    { module: 'php', id: 'php', aliases: ['PHP'], extensions: ['.php', '.php4', '.php5', '.phtml', '.ctp'] },
    { module: 'html', id: 'html', aliases: ['HTML'], extensions: ['.html', '.htm', '.shtml', '.xhtml', '.mdoc', '.jsp', '.asp', '.aspx', '.jshtml'], mimetypes: ['text/html', 'text/x-jshtm', 'text/template', 'text/ng-template'] },
    { module: 'css', id: 'css', aliases: ['CSS'], extensions: ['.css'], mimetypes: ['text/css'] },
    { module: 'sql', id: 'sql', aliases: ['SQL'], extensions: ['.sql'], mimetypes: ['text/x-sql'] },
    { module: 'shell', id: 'shell', aliases: ['Shell', 'sh', 'bash'], extensions: ['.sh', '.bash'], firstLine: '^#!.*\\b(bash|sh|zsh)$' },
];
