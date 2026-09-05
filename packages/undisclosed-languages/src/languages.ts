/**
 * Registration metadata for the popular languages supported by Undisclosed's editor.
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
    { module: 'typescript', id: 'typescript', aliases: ['TypeScript', 'ts'], extensions: ['.ts', '.mts', '.cts'] },
    // TSX reuses the vendored TypeScript tokenizer (no separate monaco module),
    // but gets its own language id + `.tsx` association (VS Code parity).
    { module: 'typescript', id: 'typescriptreact', aliases: ['TypeScript React', 'tsx'], extensions: ['.tsx'] },
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
    // Config / markup formats and more popular developer languages.
    { module: 'yaml', id: 'yaml', aliases: ['YAML', 'yml'], extensions: ['.yaml', '.yml'], mimetypes: ['application/x-yaml', 'text/yaml'] },
    { module: 'markdown', id: 'markdown', aliases: ['Markdown', 'md'], extensions: ['.md', '.markdown', '.mdown', '.mkdn', '.mkd', '.mdwn', '.mdtxt', '.mdtext'], mimetypes: ['text/markdown'] },
    { module: 'xml', id: 'xml', aliases: ['XML'], extensions: ['.xml', '.xsd', '.dtd', '.ascx', '.csproj', '.config', '.props', '.targets', '.svg', '.wsdl'], mimetypes: ['text/xml', 'application/xml'], firstLine: '^<\\?xml' },
    { module: 'dockerfile', id: 'dockerfile', aliases: ['Dockerfile'], extensions: ['.dockerfile'], filenames: ['Dockerfile'] },
    { module: 'kotlin', id: 'kotlin', aliases: ['Kotlin', 'kt'], extensions: ['.kt', '.kts'] },
    { module: 'swift', id: 'swift', aliases: ['Swift'], extensions: ['.swift'] },
    { module: 'dart', id: 'dart', aliases: ['Dart'], extensions: ['.dart'] },
    { module: 'scala', id: 'scala', aliases: ['Scala'], extensions: ['.scala', '.sc', '.sbt'] },
    { module: 'graphql', id: 'graphql', aliases: ['GraphQL', 'gql'], extensions: ['.graphql', '.gql'] },
    { module: 'lua', id: 'lua', aliases: ['Lua'], extensions: ['.lua'] },
    { module: 'perl', id: 'perl', aliases: ['Perl'], extensions: ['.pl', '.pm'], firstLine: '^#!/.*\\bperl\\b' },
    { module: 'r', id: 'r', aliases: ['R'], extensions: ['.r', '.rhistory', '.rprofile', '.rt'] },
    { module: 'powershell', id: 'powershell', aliases: ['PowerShell', 'ps1'], extensions: ['.ps1', '.psm1', '.psd1'] },
    { module: 'ini', id: 'ini', aliases: ['Ini'], extensions: ['.ini', '.properties', '.gitconfig'] },
    { module: 'hcl', id: 'hcl', aliases: ['HCL', 'Terraform', 'tf'], extensions: ['.tf', '.tfvars', '.hcl'] },
    { module: 'protobuf', id: 'protobuf', aliases: ['Protocol Buffers', 'proto'], extensions: ['.proto'] },
    // <ADD-LANGUAGE:descriptors> new language descriptors go above this line
];
