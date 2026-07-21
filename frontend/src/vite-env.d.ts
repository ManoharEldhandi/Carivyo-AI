/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CARIVYO_BOOTSTRAP_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
