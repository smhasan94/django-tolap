#!/usr/bin/env bash
# Adoption signals in one screen: PyPI downloads, this repo, the upstream issue.
# Needs curl, python3 and gh (logged in). pypistats lags a day or two and has no data
# for a package until its first full day.
set -u
for p in django-tolap sqlalchemy-tolap; do
  printf '%-17s' "$p"
  curl -sf "https://pypistats.org/api/packages/$p/recent" | python3 -c '
import json, sys
d = json.load(sys.stdin).get("data", {})
print("downloads day/week/month:", d.get("last_day"), d.get("last_week"), d.get("last_month"))' \
    2>/dev/null || echo "no pypistats data yet"
done
gh api repos/smhasan94/django-tolap \
  --jq '"repo: stars \(.stargazers_count) forks \(.forks_count) watchers \(.subscribers_count) open issues \(.open_issues_count)"'
gh api "repos/smhasan94/django-tolap/issues?state=open&per_page=10" \
  --jq '.[] | "  open #\(.number) \(.title) (\(.user.login))"'
gh api repos/awslabs/tolap/issues/31 \
  --jq '"upstream #31: \(.state), \(.comments) comments, updated \(.updated_at[0:10])"'
gh api repos/awslabs/tolap/issues/31/comments --jq '.[] | select(.user.login != "smhasan94") | "  reply from \(.user.login) \(.created_at[0:10])"'
gh api repos/awslabs/tolap --jq '"upstream tolap: stars \(.stargazers_count), open issues \(.open_issues_count)"'
curl -s https://pypi.org/pypi/tolap-core/json | python3 -c 'import json,sys; print("tolap-core on PyPI:", json.load(sys.stdin)["info"]["version"])'
