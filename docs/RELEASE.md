# Release

## CI
`ci.yml` runs lint, type-check, and tests on macOS and Windows.

## Tagged release
Push a tag like `v0.1.0`.
`release.yml` will:
- build onefile GUI app with PyInstaller on macOS + Windows
- publish artifacts to GitHub Releases.
