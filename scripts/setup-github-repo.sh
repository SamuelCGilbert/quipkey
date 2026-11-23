#!/usr/bin/env bash
# One-time (and re-runnable) GitHub repository setup: description, topics, Discussions, labels.
#   scripts/setup-github-repo.sh OWNER/REPO
# Needs the GitHub CLI (gh), logged in with admin rights on the repository.
set -euo pipefail
REPO="${1:?usage: $0 OWNER/REPO}"

gh repo edit "$REPO" \
  --description "Press a hotkey, speak, and the text is typed into any app. Local, private speech recognition for Windows and Linux." \
  --enable-discussions --enable-issues --enable-wiki=false --enable-projects=false \
  --delete-branch-on-merge \
  --add-topic dictation --add-topic speech-to-text --add-topic voice-typing \
  --add-topic push-to-talk --add-topic parakeet --add-topic onnx --add-topic wayland \
  --add-topic windows --add-topic linux --add-topic kde

label() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force; }
label "bug"              "d73a4a" "Something isn't working"
label "enhancement"      "a2eeef" "New feature or improvement"
label "needs-triage"     "fbca04" "Not looked at yet"
label "question"         "d876e3" "Needs more information, or is a question"
label "documentation"    "0075ca" "README, docs, comments"
label "good first issue" "7057ff" "A good place to start contributing"
label "help wanted"      "008672" "Contributions welcome"
label "duplicate"        "cfd3d7" "Already reported"
label "wontfix"          "ffffff" "Won't be worked on"
label "windows"          "0e8a16" "Windows-specific"
label "linux"            "0e8a16" "Linux-specific"
label "macos"            "0e8a16" "macOS-specific"
label "kde"              "c5def5" "KDE Plasma"
label "gnome"            "c5def5" "GNOME"
label "packaging"        "bfd4f2" "Installers, builds, releases"
label "speech-model"     "bfd4f2" "Recognition quality, models, GPU/CPU"
label "typing"           "bfd4f2" "Getting the text into apps: paste, keys, clipboard"
echo "Done. Discussions: https://github.com/$REPO/discussions"
