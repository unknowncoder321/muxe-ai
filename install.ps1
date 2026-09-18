<#
  MUXE installer - Windows 10 / 11
  =====================================================================
  Paste ONE line into PowerShell:

      irm https://raw.githubusercontent.com/unknowncoder321/muxe-ai/main/install.ps1 | iex

  It will:
    1. ask for the password   (checked against a SHA-256 hash, never stored)
    2. find or install Python 3
    3. download the MUXE source code
    4. create a private virtualenv and install the 4 dependencies
    5. detect your RAM and download the biggest model you can actually run
    6. create a portable `muxe` launcher and put it on your PATH

  Re-running it is safe: it upgrades in place and keeps your models.
#>

$ErrorActionPreference = 'Stop'

# ======================= EDIT THESE =========================
$REPO   = 'unknowncoder321/muxe-ai'   # <-- your GitHub user/repo (no https://)
$BRANCH = 'main'
# SHA-256 of the password. To change the password, run:
#   [BitConverter]::ToString([Security.Cryptography.SHA256]::Create()
#     .ComputeHash([Text.Encoding]::UTF8.GetBytes('newpassword'))).Replace('-','').ToLower()
$PWHASH = '05e3dc22232e446300960f9edd8f070ec214ffc83f05d3c7cd9a18db8099430b'
# ============================================================

$INSTALL = Join-Path $env:LOCALAPPDATA 'MUXE'
$VENV    = Join-Path $INSTALL '.venv'
$PYEXE   = Join-Path $VENV 'Scripts\python.exe'
$PYINDEX = 'https://abetlen.github.io/llama-cpp-python/whl/cpu'

# model tiers, biggest first: need = free RAM in GB required
$MODELS = @(
  @{ need = 3.4; file = 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
     label = 'Qwen3 4B   - smartest'
     url   = 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf' }
  @{ need = 1.9; file = 'qwen2.5-coder-1.5b-instruct-q4_k_m.gguf'
     label = 'Qwen2.5-Coder 1.5B - balanced'
     url   = 'https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf' }
  @{ need = 0.0; file = 'qwen2.5-0.5b-instruct-q4_k_m.gguf'
     label = 'Qwen2.5 0.5B - fastest'
     url   = 'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf' }
)

function Say  ($m) { Write-Host "  $m" }
function Ok   ($m) { Write-Host "  [ok] $m"   -ForegroundColor Green }
function Warn ($m) { Write-Host "  [!]  $m"  -ForegroundColor Yellow }
function Die  ($m) { Write-Host "  [x]  $m"  -ForegroundColor Red; exit 1 }
function Head ($m) { Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  MUXE - local AI coding partner" -ForegroundColor Magenta
Write-Host "  ---------------------------------------------" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. password
Head "Password"
$sec  = Read-Host -Prompt '  Password' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try     { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

$sha = [BitConverter]::ToString(
         [Security.Cryptography.SHA256]::Create().ComputeHash(
           [Text.Encoding]::UTF8.GetBytes($plain))).Replace('-','').ToLower()

if ($sha -ne $PWHASH) {
  Write-Host ""
  Die "Wrong password. Nothing was installed."
}
Ok "Welcome."

New-Item -ItemType Directory -Force -Path $INSTALL | Out-Null

# ---------------------------------------------------------------- 2. python
Head "Python"
$PY = $null
foreach ($cand in @(@('py','-3'), @('python',''))) {
  $exe = $cand[0]; $pre = $cand[1]
  try {
    $v = & $exe $pre -c "import sys;print(sys.version_info[0])" 2>$null
    if ("$v".Trim() -eq '3') { $PY = @($exe, $pre); break }
  } catch { }
}

if (-not $PY) {
  Warn "Python 3 not found. Trying winget..."
  try {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements | Out-Null
  } catch { }
  foreach ($cand in @(@('py','-3'), @('python',''))) {
    try {
      $v = & $cand[0] $cand[1] -c "import sys;print(sys.version_info[0])" 2>$null
      if ("$v".Trim() -eq '3') { $PY = @($cand[0], $cand[1]); break }
    } catch { }
  }
}
if (-not $PY) {
  Die "Python 3 is required. Install it from https://python.org and re-run."
}
$pyver = & $PY[0] $PY[1] --version 2>&1
Ok "$pyver found."

# ---------------------------------------------------------------- 3. source
Head "Source code"
$tmp = Join-Path $env:TEMP ("muxe_src_" + [Guid]::NewGuid().ToString('N').Substring(0,8))
$zip = "$tmp.zip"
try {
  $url = "https://github.com/$REPO/archive/refs/heads/$BRANCH.zip"
  Say "downloading $REPO ..."
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $root = Get-ChildItem $tmp -Directory | Select-Object -First 1
  if (-not $root) { Die "Downloaded archive was empty." }
  Copy-Item (Join-Path $root.FullName 'gully') $INSTALL -Recurse -Force
  Ok "source installed."
} catch {
  Die "Could not download the source from GitHub. Check the internet, then re-run. ($($_.Exception.Message))"
} finally {
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 4. deps
Head "Dependencies"
if (-not (Test-Path $PYEXE)) {
  Say "creating virtualenv ..."
  & $PY[0] $PY[1] -m venv $VENV
}
if (-not (Test-Path $PYEXE)) { Die "Could not create the virtualenv." }

& $PYEXE -m pip install --upgrade pip --quiet --disable-pip-version-check
Say "installing pyyaml, rich, psutil ..."
& $PYEXE -m pip install --quiet --disable-pip-version-check pyyaml rich psutil
if ($LASTEXITCODE -ne 0) { Die "Failed installing base dependencies." }

Say "installing llama-cpp-python (prebuilt CPU wheel) ..."
& $PYEXE -m pip install --quiet --disable-pip-version-check `
    --extra-index-url $PYINDEX --only-binary=:all: llama-cpp-python
if ($LASTEXITCODE -ne 0) {
  Warn "prebuilt wheel failed - trying plain install (may need build tools)"
  & $PYEXE -m pip install --quiet --disable-pip-version-check llama-cpp-python
  if ($LASTEXITCODE -ne 0) { Die "Could not install llama-cpp-python." }
}
Ok "dependencies ready."

# ---------------------------------------------------------------- 5. model
Head "Model"
$freeGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Say "free RAM: $freeGB GB"
$pick = $MODELS | Where-Object { $freeGB -ge $_.need } | Select-Object -First 1
Say "selected: $($pick.label)"

$mdir  = Join-Path $INSTALL 'models'
New-Item -ItemType Directory -Force -Path $mdir | Out-Null
$mfile = Join-Path $mdir $pick.file

if (Test-Path $mfile) {
  Ok "model already present, skipping download."
  [Environment]::SetEnvironmentVariable('MUXE_MODEL', $mfile, 'User')
} else {
  Say "downloading $($pick.file)  (this is the big one)"
  $dl = Join-Path $INSTALL '_download.py'
  @'
import sys, urllib.request, os
url, dest = sys.argv[1], sys.argv[2]
have = os.path.getsize(dest) if os.path.exists(dest) else 0
req = urllib.request.Request(url, headers={"User-Agent": "muxe-installer"})
if have:
    req.add_header("Range", f"bytes={have}-")
try:
    r = urllib.request.urlopen(req, timeout=60)
except Exception as e:
    print(f"\n  download failed: {e}"); sys.exit(1)
total = int(r.headers.get("Content-Length", 0)) + have
mode = "ab" if have and r.status == 206 else "wb"
if mode == "wb":
    have = 0
got = have
with open(dest, mode) as f:
    while True:
        chunk = r.read(1024 * 256)
        if not chunk:
            break
        f.write(chunk)
        got += len(chunk)
        if total:
            pct = got * 100 // total
            bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
            print(f"\r  [{bar}] {pct:3d}%  {got/1024**3:.2f}/{total/1024**3:.2f} GB", end="")
print("\n  done")
'@ | Set-Content -Path $dl -Encoding ASCII

  & $PYEXE $dl $pick.url $mfile
  Remove-Item $dl -Force -ErrorAction SilentlyContinue
  if (-not (Test-Path $mfile) -or (Get-Item $mfile).Length -lt 10MB) {
    Die "Model download failed or was incomplete. Re-run the installer to resume."
  }
  Ok "model ready."
  [Environment]::SetEnvironmentVariable('MUXE_MODEL', $mfile, 'User')
}

# point config.yaml at whatever we downloaded
$cfg = Join-Path $INSTALL 'gully\config.yaml'
if (Test-Path $cfg) {
  # NOTE: must use .NET ReadAllText/WriteAllText with UTF8 (no BOM).
  # Set-Content would re-encode as ANSI and corrupt the em-dashes in config.yaml.
  $rel  = "gully/models/$($pick.file)"
  $text = [IO.File]::ReadAllText($cfg)
  foreach ($k in @('model_id','model_file')) {
    $text = [regex]::Replace($text, ('(?m)^' + $k + ':.*'), ($k + ': ' + $rel))
  }
  [IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding($false)))
  Ok "config points at $($pick.file)"
}

# ---------------------------------------------------------------- 6. launcher
Head "Launcher"
[Environment]::SetEnvironmentVariable('MUXE_HOME', $INSTALL, 'User')

$l1 = Join-Path $INSTALL 'muxe.cmd'
@"
@echo off
cd /d "%~dp0"
"$PYEXE" -m gully.muxe %*
"@ | Set-Content -Path $l1 -Encoding ASCII

$l2 = Join-Path $INSTALL 'muxe.ps1'
@"
Set-Location "$INSTALL"
& "$PYEXE" -m gully.muxe @args
exit `$LASTEXITCODE
"@ | Set-Content -Path $l2 -Encoding ASCII
Ok "launchers written."

$userPath = [Environment]::GetEnvironmentVariable('Path','User')
if ($userPath -notlike "*$INSTALL*") {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$INSTALL", 'User')
  Ok "added to PATH."
} else {
  Ok "already on PATH."
}

# ---------------------------------------------------------------- verify
Head "Verify"
& $PYEXE -c "import llama_cpp, yaml, rich, psutil; print('  all imports ok')"
if ($LASTEXITCODE -ne 0) { Warn "import check failed - MUXE may not start." }

Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host "  Open a NEW terminal and type:  " -NoNewline
Write-Host "muxe" -ForegroundColor Magenta
Write-Host ""
