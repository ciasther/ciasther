#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

fail() { printf 'BŁĄD: %s\n' "$*" >&2; exit 1; }
for command in git gh python3; do
  command -v "$command" >/dev/null || fail "Brak polecenia $command. Publikacja przez przeglądarkę: START.md."
done
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || fail 'Wymagany Python 3.11 lub nowszy.'
[[ "$(gh api user --jq .login)" == 'ciasther' ]] || fail 'Zaloguj GitHub CLI na konto ciasther: gh auth login.'
[[ ! -d .git ]] || fail 'Ten katalog ma już historię Git. Skrypt publikuje wyłącznie nową paczkę, bez nadpisywania repozytorium.'
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  fail 'Rozpakuj paczkę poza innym repozytorium Git.'
fi

printf '%s\n' 'Powstanie PUBLICZNE repozytorium ciasther/ciasther z plikami tej paczki.'
printf '%s\n' 'Dodaj token classic z JEDYNYM zakresem read:user. Nie używaj głównego tokenu do repozytoriów.'
printf '%s\n' 'Najpierw włącz na profilu: Contribution settings → Private contributions.'
read -r -s -p 'Wklej dedykowany token (wpis jest ukryty): ' PROFILE_TOKEN
printf '\n'
[[ -n "$PROFILE_TOKEN" ]] || fail 'Token jest pusty.'
export PROFILE_TOKEN
trap 'unset PROFILE_TOKEN' EXIT
python3 -m unittest discover -s tests -q
python3 scripts/update_profile.py --fetch

# Utworzenie zakończy się błędem, jeśli repozytorium już istnieje. Bez force-push.
gh repo create ciasther/ciasther --public --description 'Od piksela do procesu. Profil GitHub Sebastiana Górskiego.'
printf '%s' "$PROFILE_TOKEN" | gh secret set PROFILE_TOKEN --repo ciasther/ciasther
unset PROFILE_TOKEN

git init -b main
git config user.name 'Sebastian Górski'
git config user.email '219615476+ciasther@users.noreply.github.com'
git add -- README.md START.md profile.json assets scripts tests docs .github .gitignore publish.sh
if [[ -f podglad.html ]]; then git add -- podglad.html; fi
git commit -m 'Dodanie profilu GitHub'
git remote add origin https://github.com/ciasther/ciasther.git
# Osobna autoryzacja zapisu: sesja gh, nie token statystyk.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main
printf '\n%s\n' 'Gotowe: https://github.com/ciasther'
printf '%s\n' 'Postęp pierwszego workflow znajdziesz w zakładce Actions repozytorium ciasther/ciasther.'
