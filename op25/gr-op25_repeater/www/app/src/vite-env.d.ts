/// <reference types="vite/client" />

/** Version from package.json, substituted by vite's `define` at build time.
 *  Kept equal to the add-on's config.yaml version by scripts/bump-version.py. */
declare const __APP_VERSION__: string;
