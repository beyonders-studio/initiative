#!/usr/bin/env bash
# Print the two ids CI files a tested tree under, one per line:
#
#   raw   the checked-out tree itself (git's tree id)
#   tree  the same tree without the files a release rewrites: the version
#         stamps, the changelog and the API client regenerated for the new
#         version
#
# A run that has tested every line of a tree records both, and a later run of
# the same tree finds them instead of testing it again (ci.yml, Detect Changes).
set -euo pipefail

release_files=$'\t(VERSION|CHANGELOG\\.md|MIN_NATIVE_VERSION|MIN_DESKTOP_VERSION|frontend/src/api/generated/.*)$'

git rev-parse 'HEAD^{tree}'
git ls-tree -r --full-tree HEAD | { grep -Ev "$release_files" || true; } | sha256sum | cut -c1-40
