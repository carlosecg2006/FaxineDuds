# Cria (ou atualiza) o atalho "Faxineiro" na Area de Trabalho, apontando para dist\Faxineiro\Faxineiro.exe.
# A Area de Trabalho deste PC fica dentro do OneDrive: o atalho (1 KB) e sincronizado, sem problema.
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\criar_atalho.ps1

$raiz = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $raiz "dist\Faxineiro\Faxineiro.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Nao achei $exe. Rode antes: .venv\Scripts\python ferramentas\gerar_exe.py"
    exit 1
}
$area = [Environment]::GetFolderPath("Desktop")
$atalho = Join-Path $area "Faxineiro.lnk"
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($atalho)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = Split-Path -Parent $exe
$lnk.Description = "Faxineiro - organizador pessoal de arquivos"
$lnk.IconLocation = "$exe,0"
$lnk.Save()
Write-Output "Atalho criado: $atalho -> $exe"
