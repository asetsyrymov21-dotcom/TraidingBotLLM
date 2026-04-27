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
