# Repository Indexing

The ingestion pipeline scans repositories and breaks source files into
semantic chunks for retrieval and context generation.  Important
infrastructure files such as `Dockerfile`, `.dockerignore`,
`Makefile`, **`Procfile`**, `pyproject.toml`, any
`requirements*.txt` file, `package.json`, **`tsconfig.json`**,
`hardhat.config.*`, `foundry.toml` and `truffle-config.*` are
included alongside source code.  These extensionless and
configuration files capture container definitions, build commands,
dependency specifications and project metadata.  Binary files,
secrets (`.env`), virtual environments, build artefacts and large
files are excluded.

## File Discovery

`RepositoryService.get_repository_files()` performs a recursive
directory walk applying the following rules:

* Files in ignored directories (`.git`, `node_modules`, `venv`,
  `__pycache__`, `dist`, `build`, etc.) are skipped.
* Extensions in `allowed_extensions` are always indexed (e.g. `.py`,
  `.js`, `.ts`, `.cpp`, `.java`, `.json`, `.yaml`, `.toml`, etc.).
* Certain extensionless names (`Dockerfile`, `.dockerignore`,
  `Makefile`, `Procfile`) and common build/run config files (`package.json`,
  `tsconfig.json`, any `requirements*.txt`, `pyproject.toml`,
  `hardhat.config.*`, `foundry.toml`, `truffle-config.*`) are
  explicitly allowed.
* Files larger than the configured `CODE_EDITOR_MAX_FILE_SIZE` are
  skipped.
* A repository size limit (`CODE_EDITOR_MAX_REPOSITORY_SIZE`) and a
  maximum number of indexed files (`CODE_EDITOR_MAX_INDEXED_FILES`)
  can be enforced via environment variables.

## Chunking

During ingestion the `IngestionService` splits each file into
language‑aware chunks.  Python files are divided on function and class
definitions, docstrings and comments.  Brace‑based languages such as
JavaScript and C++ are split on block boundaries and declarations.
Files with unknown structure are split by line count and maximum
character count with overlap.  Symbol names and chunk types
(function, class, import, code, comment) are recorded for improved
retrieval.

## Incremental Updates

When ingestion runs, the service computes a hash of each file and
compares it to the stored `file_hash` of the corresponding
`IndexedFile`.  Unchanged files are skipped, while changed files are
re‑chunked and reindexed.  Stale chunks from deleted files are
removed.  The ingestion status (`pending`, `running`, `completed`,
`failed`) and error message are recorded on the `IngestionJob`.