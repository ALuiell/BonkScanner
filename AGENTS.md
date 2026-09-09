# BonkScanner repository workflow

## Repository map

- This directory is the BonkScanner application repository.
- `docs/` is a separate Git repository whose remote is
  `https://github.com/ALuiell/bonkscanner-docs.git`.
- The documentation repository is checked out directly at `docs/`; do not add
  another `docs/` level inside it and do not turn it into a submodule.
- The application repository ignores `docs/`. Never stage documentation files
  through the application repository.

## Route changes to the owning repository

- Application code, tests, build files, packaged assets, and the public project
  README belong to the application repository.
- Maintainer documentation, research, plans, feature histories, recovery notes,
  mechanics, and wiki pages belong to the documentation repository.
- `docs/help/help_eng.txt`, `help_ru.txt`, and `help_ukr.txt` are the canonical
  in-app help sources. Their byte-for-byte packaged mirrors live in
  `src/media/help/` in the application repository.
- Never edit only the packaged help mirror. Edit the canonical file under
  `docs/help/`, then run `powershell -NoProfile -ExecutionPolicy Bypass -File
  scripts/sync_help.ps1` from the application repository.

## Start and validate work

- When a task may affect documentation, inspect both repositories separately:
  `git status --short --branch` and `git -C docs status --short --branch`.
- Application branch operations affect only the application repository. Keep
  the documentation repository on `main` unless the user explicitly requests a
  documentation branch.
- After changing help, run `scripts/sync_help.ps1 -Check` and the relevant
  application tests. A local build also synchronizes help automatically when a
  documentation checkout is present.
- Preserve recovered documents and research artifacts exactly unless the user
  explicitly asks to rewrite them. Keep configured large-file patterns in Git
  LFS and run `git lfs fsck` before publishing large documentation changes.

## Commit and publish

- Stage paths explicitly and create separate commits in each affected
  repository. Do not combine their histories or remotes.
- A request to commit or push documentation applies to the documentation
  repository. A request to commit or push code applies to the application
  repository.
- A request to commit and push all changes applies to both repositories when
  both contain task-related changes. Report both commit hashes and each
  repository's final upstream divergence.
- Before pushing the application repository, inspect its unpublished commits.
  Do not publish unrelated pre-existing commits as a side effect of a
  documentation task; report that condition and leave the application commit
  local unless the user explicitly includes that history.
- Use each repository's configured `origin` with normal Git commands. Do not use
  GitHub-specific publishing tools unless the user asks for a pull request.
