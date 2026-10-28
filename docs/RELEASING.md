# Publication and releases

Use the repository skill at [mklink-remote-publish](../.agents/skills/mklink-remote-publish/SKILL.md). The destination is `MicroKeen/Mklink-Remote`; new project code is MIT.

1. Preserve local work and experiment history in a bundle/source backup.
2. Curate `tools/public-files.json`, review licenses and run `tools/check-public.py` plus a secret scanner. Keep specific private identifiers in a local `--private-markers` file, never in the published scanner rules. Inspect the actual staged tree and every commit to be pushed. Do not `git add .`, `push --all`, `push --mirror` or use unconditional force-push. The publishing skill documents the narrow, SHA-guarded exception for correcting this task's own just-created initial publication.
3. Verify a clean export/clone using [BUILD](BUILD.md); record tested tool versions and results. Check the browser with automation. HIL is separately documented.
4. Push the reviewed commit to the intended branch. Confirm the remote SHA, public visibility, default branch and CI results. Keep raw scan/build logs local.

## Binary artifacts

Installer EXE, portable ZIP and firmware ZIP belong to GitHub Releases, not source commits. Do not attach an arbitrary local build to a qualified version. Prepare real resource binaries, preserve required third-party notices/corresponding source, verify target Pack/algorithm redistribution terms, and compare every binary against its qualification hashes.

`desktop/mklink-wireless-config/tools/package-release.py` requires a qualification JSON covering all three wireless routes, original-client boundary, binary hashes and hardware restoration. It does not manufacture hardware evidence. The historical user-deferred C6 Companion startup is a separate status and must not be recorded as running.

The desktop and S3 firmware have independent versions. For the initial source publication these are 0.8.0 and 0.7.2. A successful source CI does not by itself authorize declaring a new binary release hardware-qualified. Keep previous releases intact; publish checksums and change notes with any later artifact release.
