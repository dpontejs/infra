#!/usr/bin/env bash
# Smoke tests for the live sites: run after every deploy (make smoke).
set -uo pipefail

domain="${1:?usage: smoke.sh <domain>}"
failures=0

check() {
  local description="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  ok    %s\n' "$description"
  else
    printf '  FAIL  %s (expected %s, got %s)\n' "$description" "$expected" "$actual"
    failures=$((failures + 1))
  fi
}

status() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@"; }
header() { curl -sI --max-time 15 "$1" | tr -d '\r' | awk -v h="$2" 'tolower($1) == tolower(h)":" {sub(/^[^:]+: /, ""); print}'; }

echo "Smoke tests for $domain"
check "https://$domain responds 200"            200 "$(status "https://$domain/")"
check "http://$domain redirects to HTTPS"        308 "$(status "http://$domain/")"
check "www redirects to apex (301)"              301 "$(status "https://www.$domain/")"
check "www redirect target"                      "https://$domain/" "$(header "https://www.$domain/" location)"
check "HSTS header present"                      "max-age=31536000; includeSubDomains; preload" "$(header "https://$domain/" strict-transport-security)"
check "Server header hidden"                     "" "$(header "https://$domain/" server)"
check "certificate valid (curl verifies TLS)"    0  "$(curl -s -o /dev/null --max-time 15 "https://$domain/"; echo $?)"
check "status panel reachable from admin IP"     200 "$(status -L "https://status.$domain/")"

if ((failures > 0)); then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
