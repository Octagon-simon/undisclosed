// Allow importing plain stylesheets from TypeScript. The frontend bundler
// (esbuild / webpack css+style loaders) resolves them; tsc only needs to know
// they are valid modules. Without this, `import '../../style/undisclosed-git.css'`
// fails typecheck with TS2307.
declare module '*.css';
