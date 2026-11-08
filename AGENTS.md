# AGENTS.md

## Core rules
- Diagnose first, fix second
- Do not break per-user isolation (alice, bob — каждый пользователь изолирован)
- No large refactoring — только точечные правки
- Max 3 files per change
- No direct push to main
- Перед правкой — читай PROJECT_MAP.md, затем только нужный файл

## Modes
- Automation: diagnostics only (не менять логику бота)
- Manual: targeted fixes only

## Routing
- Debug / ошибки бота    -> ai/rules/debug.md
- Deploy / деплой на VPS -> ai/rules/git-deploy.md
- Coding / правки кода   -> ai/rules/coding.md
- Automation / cron/ci   -> ai/rules/automation.md
- Users / пользователи   -> ai/rules/user.md

## Secret handling — mandatory

- Never commit or push real API keys, access tokens, passwords, private keys, credential URLs, or production configuration.
- Keep secrets in ignored local environment files or the GitHub Actions secrets store. Example/template files must contain placeholders only.
- Before every commit, scan the staged diff with Gitleaks using --pre-commit --staged --redact=100.
- Before every push or PR, scan every commit being published with Gitleaks using --log-opts=--all --redact=100.
- If the scanner is missing, fails, or finds a secret, stop. Never use --no-verify, bypass push protection, or add an allowlist to conceal a real secret.
- Stage explicit paths only. Never stage .env files, key files, private credential backups, or cleanup bundles.
- Never print secret values in logs, commands, reviews, screenshots, or PR descriptions.
- If a secret was committed, remove it from reachable history and report that revocation/rotation and GitHub cache/PR cleanup may still be required.
