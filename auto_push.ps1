# ============================================================
#  auto_push.ps1 — фоновый авто-пуш на GitHub каждые 30 сек
#  Запуск: .\auto_push.ps1
#  Остановить: Ctrl+C
# ============================================================

$BOT_DIR = "C:\Users\midori\Desktop\Trading_Bot"
$INTERVAL = 30   # секунд между проверками

Write-Host "🤖 Авто-пуш запущен. Интервал: $INTERVAL сек. Для остановки — Ctrl+C" -ForegroundColor Cyan
Write-Host "Папка: $BOT_DIR`n" -ForegroundColor Gray

Set-Location $BOT_DIR

while ($true) {
    # Удаляем lock если завис
    if (Test-Path ".git\index.lock") {
        Remove-Item ".git\index.lock" -Force
    }

    # Проверяем есть ли изменения
    $changes = git status --porcelain 2>$null
    if ($changes) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] Найдены изменения:" -ForegroundColor Yellow
        $changes | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

        git add -A 2>$null
        $msg = "auto: $timestamp"
        git commit -m $msg 2>$null | Out-Null

        $push = git push origin master 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[$timestamp] ✅ Запушено в GitHub" -ForegroundColor Green
        } else {
            Write-Host "[$timestamp] ❌ Push не удался: $push" -ForegroundColor Red
        }
    }

    Start-Sleep -Seconds $INTERVAL
}
