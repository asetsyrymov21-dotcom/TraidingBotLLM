# ============================================================
#  deploy.ps1 — скрипт деплоя для PowerShell (Windows)
#  Использование:
#    .\deploy.ps1                      # коммит с авто-сообщением
#    .\deploy.ps1 "описание правки"    # коммит с твоим сообщением
# ============================================================

param(
    [string]$CommitMsg = ""
)

# ── НАСТРОЙКИ ─────────────────────────────────────────────
$VPS_USER = "root"
$VPS_HOST = "178.104.156.114"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"
$BOT_DIR  = "/opt/trading-bot/TraidingBotLLM"
# ──────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

Write-Host "`n🚀 Деплой бота..." -ForegroundColor Yellow

# ── Удаляем зависший lock-файл ──
if (Test-Path ".git\index.lock") {
    Write-Host "⚠️  Найден git lock — удаляю..." -ForegroundColor Yellow
    Remove-Item ".git\index.lock" -Force
}

# ── 1. Git commit + push ──
Write-Host "`n[1/4] Git..." -ForegroundColor Yellow
git add -A -- . ':!.claude'

git diff --staged --quiet
if ($LASTEXITCODE -ne 0) {
    if ($CommitMsg -eq "") {
        $CommitMsg = "update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }
    git commit -m $CommitMsg
    if ($LASTEXITCODE -ne 0) { Write-Host "❌ Коммит провалился" -ForegroundColor Red; exit 1 }
    Write-Host "✅ Коммит: $CommitMsg" -ForegroundColor Green
} else {
    Write-Host "Нет новых изменений." -ForegroundColor Gray
}

git push origin master
if ($LASTEXITCODE -ne 0) { Write-Host "❌ Push провалился — проверь токен" -ForegroundColor Red; exit 1 }
Write-Host "✅ Запушено в GitHub" -ForegroundColor Green

# ── 2. SSH: git pull ──
Write-Host "`n[2/4] Обновляем код на VPS..." -ForegroundColor Yellow
ssh -i $SSH_KEY -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "cd $BOT_DIR && git pull origin master"
Write-Host "✅ Код обновлён" -ForegroundColor Green

# ── 3. SSH: обновить зависимости ──
Write-Host "`n[3/4] Обновляем зависимости..." -ForegroundColor Yellow
ssh -i $SSH_KEY -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "cd $BOT_DIR && .venv/bin/pip install -r requirements.txt -q"
Write-Host "✅ Зависимости обновлены" -ForegroundColor Green

# ── 4. SSH: перезапустить сервис ──
Write-Host "`n[4/4] Перезапускаем бота..." -ForegroundColor Yellow
ssh -i $SSH_KEY -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "systemctl restart tradingbot"
Write-Host "✅ Бот перезапущен!" -ForegroundColor Green

Write-Host "`n🎉 Деплой завершён!" -ForegroundColor Green
Write-Host "Логи: ssh $VPS_USER@$VPS_HOST 'journalctl -u tradingbot -f'" -ForegroundColor Cyan
