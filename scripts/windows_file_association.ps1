<#
.SYNOPSIS
    Register (or unregister) this PDF Editor as a handler for .pdf files on
    Windows, under the current user only (HKCU - no admin required).

.DESCRIPTION
    The "Open with" list takes an app's name and icon from the EXECUTABLE, not
    from the file-type ProgID. Our real interpreter is pythonw.exe, which would
    show up as "Python". To get a recognizable "PDF Editor (reiya)" entry with
    our own icon, we copy pythonw.exe to a uniquely-named launcher

        .venv\Scripts\pdf_editor.exe

    and register it under HKCU\Software\Classes\Applications\pdf_editor.exe with
    a FriendlyAppName, DefaultIcon, open command, and SupportedTypes(.pdf).

    A ProgID (PDFEditor.Document) + Capabilities are also registered so the app
    appears in Settings > Apps > Default apps and carries the file icon once it
    becomes the default.

    Safe re-registration: required assets (pythonw.exe, main.py, the icon) are
    validated up front and the script aborts with a nonzero exit code BEFORE
    touching anything if any is missing. Before mutating, it SNAPSHOTS the prior
    managed registry keys and launcher; if any step fails, it RESTORES that
    snapshot (returning to the pre-run state) instead of deleting everything.
    This matters because the script never changes the protected UserChoice, so
    deleting a previously-working registration would leave the user's default
    pointing at a removed handler. The launcher is also swapped atomically
    (write temp, then rename) so the old launcher survives a failed copy.

    Windows 10/11 protect the actual default-handler choice (UserChoice) with a
    per-user hash, so this script CANNOT silently seize the default. After
    running it, make it the default with one click (see the printed hint).

.PARAMETER Unregister
    Remove everything this script created (and delete the launcher copy).

.PARAMETER IconPath
    Path to the .ico used for the file/app icon. Defaults to the vendored
    appearance_design\app_icon.ico. Pass another path to use a different icon.

.PARAMETER SimulateMidwayFailure
    TEST ONLY. Throw partway through registration (after the first key block) to
    exercise the snapshot-restore path. Not for normal use.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows_file_association.ps1
    powershell -ExecutionPolicy Bypass -File scripts\windows_file_association.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [switch]$Unregister,
    [string]$IconPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'appearance_design\app_icon.ico'),
    [switch]$SimulateMidwayFailure
)

$ErrorActionPreference = 'Stop'

# --- Resolve paths -----------------------------------------------------------
$ProjectDir = Split-Path -Parent $PSScriptRoot
$ScriptsDir = Join-Path $ProjectDir '.venv\Scripts'
$Pythonw    = Join-Path $ScriptsDir 'pythonw.exe'
$Launcher   = Join-Path $ScriptsDir 'pdf_editor.exe'   # uniquely-named copy
$MainPy     = Join-Path $ProjectDir 'main.py'

$ProgId     = 'PDFEditor.Document'
$AppExe     = 'pdf_editor.exe'                          # Applications\<this>
$AppName    = 'PDF Editor (reiya)'
$AppRegName = 'PDFEditorReiya'                          # key under HKCU\Software

$AppsKey    = "HKCU:\Software\Classes\Applications\$AppExe"
$ProgIdKey  = "HKCU:\Software\Classes\$ProgId"
$PdfProgids = 'HKCU:\Software\Classes\.pdf\OpenWithProgids'
$CapKey     = "HKCU:\Software\$AppRegName\Capabilities"
$RegAppsKey = 'HKCU:\Software\RegisteredApplications'

# The three registry subtrees this script owns outright (safe to export/delete
# wholesale). The .pdf\OpenWithProgids and RegisteredApplications keys are
# shared with the rest of the system - we only own a single VALUE in each, so
# those are snapshotted value-by-value, not as subtrees.
$OwnedKeyPsPaths = @($AppsKey, $ProgIdKey, "HKCU:\Software\$AppRegName")

function Invoke-ShellAssocRefresh {
    # Tell the shell associations changed, then nudge the icon cache.
    try {
        if (-not ('Shell.Notify' -as [type])) {
            Add-Type -Namespace Shell -Name Notify -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@ -ErrorAction Stop
        }
        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0
        [Shell.Notify]::SHChangeNotify(0x08000000, 0x0, [System.IntPtr]::Zero, [System.IntPtr]::Zero)
    } catch {
        Write-Warning "Could not call SHChangeNotify: $($_.Exception.Message)"
    }
    try { & ie4uinit.exe -show } catch {}
}

function ConvertTo-RegPath([string]$psPath) {
    # "HKCU:\Software\..." -> "HKCU\Software\..." for reg.exe.
    return ($psPath -replace '^HKCU:\\', 'HKCU\')
}

function Remove-Managed {
    # Best-effort removal of every key/file this script manages. Used only by
    # -Unregister (NOT by rollback), so it must never itself throw.
    if (Test-Path $AppsKey)   { Remove-Item -Path $AppsKey -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $ProgIdKey) { Remove-Item -Path $ProgIdKey -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $PdfProgids) {
        Remove-ItemProperty -Path $PdfProgids -Name $ProgId -ErrorAction SilentlyContinue
    }
    $appBase = "HKCU:\Software\$AppRegName"
    if (Test-Path $appBase) { Remove-Item -Path $appBase -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $RegAppsKey) {
        Remove-ItemProperty -Path $RegAppsKey -Name $AppName -ErrorAction SilentlyContinue
    }
    if (Test-Path $Launcher) { Remove-Item -Path $Launcher -Force -ErrorAction SilentlyContinue }
}

function Assert-Prerequisites {
    # Fatal pre-flight: refuse to mutate anything unless every required asset is
    # present. Listing all problems at once saves a round-trip for the user.
    $missing = @()
    if (-not (Test-Path $Pythonw))  { $missing += "pythonw.exe (needed to build the launcher): $Pythonw" }
    if (-not (Test-Path $MainPy))   { $missing += "main.py: $MainPy" }
    if (-not (Test-Path $IconPath)) { $missing += "icon: $IconPath" }
    if ($missing.Count -gt 0) {
        throw ("Cannot register - missing required file(s):`n  - " + ($missing -join "`n  - ") +
               "`nNo registry changes were made.")
    }
}

function Get-RegValueSnapshot([string]$keyPsPath, [string]$name) {
    # Capture one registry value as @{ Kind; Data } (kind preserved so restore is
    # type-faithful, e.g. REG_NONE stays REG_NONE), or $null when key/value absent.
    if (-not (Test-Path $keyPsPath)) { return $null }
    $key = Get-Item -LiteralPath $keyPsPath
    if ($key.GetValueNames() -notcontains $name) { return $null }
    # DoNotExpandEnvironmentNames keeps %VAR% intact for REG_EXPAND_SZ values, so a
    # restore re-writes the original indirection rather than a baked-out literal path.
    $data = $key.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    return @{ Kind = $key.GetValueKind($name); Data = $data }
}

function Restore-RegValue([string]$keyPsPath, [string]$name, $snapVal) {
    # Restore one shared value to its snapshot (preserving kind), or remove it
    # when it was absent before. Returns $true on success, $false (with a
    # warning) on failure so the caller can report rollback completeness.
    try {
        if ($null -eq $snapVal) {
            # Was absent pre-run: remove it only if the failed run actually added it.
            # Use Stop so a genuine removal failure surfaces as $false rather than a
            # falsely-complete rollback.
            if ((Test-Path $keyPsPath) -and ((Get-Item -LiteralPath $keyPsPath).GetValueNames() -contains $name)) {
                Remove-ItemProperty -Path $keyPsPath -Name $name -ErrorAction Stop
            }
        } else {
            if (-not (Test-Path $keyPsPath)) { New-Item -Path $keyPsPath -Force -ErrorAction Stop | Out-Null }
            New-ItemProperty -Path $keyPsPath -Name $name -Value $snapVal.Data -PropertyType ($snapVal.Kind.ToString()) -Force -ErrorAction Stop | Out-Null
        }
        return $true
    } catch {
        Write-Warning "Failed to restore value '$name' under ${keyPsPath}: $($_.Exception.Message)"
        return $false
    }
}

function Backup-State {
    # Snapshot all managed state so a failed registration can be rolled back to
    # the pre-run state (rather than deleted). Mutates nothing under the live
    # keys - only writes into a fresh temp dir, and if the snapshot cannot be
    # completed it deletes that temp dir before re-throwing so it never leaks.
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("pdfassoc_" + [System.Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    try {
        $snap = @{
            Dir          = $dir
            OwnedKeys    = @()      # @{ PsPath; RegPath; File; Existed }
            SharedValues = @{}      # logical -> @{ Kind; Data } (or $null when absent)
            LauncherExisted = (Test-Path $Launcher)
            LauncherBackup  = $null
        }

        $idx = 0
        foreach ($psPath in $OwnedKeyPsPaths) {
            $idx++
            $file = Join-Path $dir ("owned_$idx.reg")
            $existed = Test-Path $psPath
            if ($existed) {
                $regPath = ConvertTo-RegPath $psPath
                & reg.exe export $regPath $file /y | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Failed to back up registry key: $regPath" }
            }
            $snap.OwnedKeys += @{ PsPath = $psPath; RegPath = (ConvertTo-RegPath $psPath); File = $file; Existed = $existed }
        }

        # Shared single values - capture with their original kind ($null = absent).
        $snap.SharedValues['OpenWithProgids'] = Get-RegValueSnapshot $PdfProgids $ProgId
        $snap.SharedValues['RegisteredApp']   = Get-RegValueSnapshot $RegAppsKey $AppName

        if ($snap.LauncherExisted) {
            $snap.LauncherBackup = Join-Path $dir 'pdf_editor.exe.bak'
            Copy-Item -Path $Launcher -Destination $snap.LauncherBackup -Force
        }

        return $snap
    } catch {
        Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Restore-State($snap) {
    # Return every managed item to its snapshot: re-import owned subtrees that
    # existed (delete ones that did not), restore the shared values with their
    # original kind, and restore the launcher. Best-effort and never throws;
    # returns $true only if every step succeeded, so the caller can tell the
    # user honestly whether the rollback was complete.
    $ok = $true

    foreach ($o in $snap.OwnedKeys) {
        if (Test-Path $o.PsPath) {
            try {
                Remove-Item -Path $o.PsPath -Recurse -Force -ErrorAction Stop
            } catch {
                # If we can't clear the live key, a later reg.exe import only MERGES,
                # so stale state from the failed run may survive - report incomplete.
                Write-Warning "Failed to clear '$($o.PsPath)' before restore: $($_.Exception.Message)"
                $ok = $false
                continue
            }
        }
        if ($o.Existed) {
            & reg.exe import $o.File | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Failed to restore registry key from $($o.File)"
                $ok = $false
            }
        }
    }

    if (-not (Restore-RegValue $PdfProgids $ProgId $snap.SharedValues['OpenWithProgids'])) { $ok = $false }
    if (-not (Restore-RegValue $RegAppsKey $AppName $snap.SharedValues['RegisteredApp'])) { $ok = $false }

    if (Test-Path "$Launcher.new") { Remove-Item -Path "$Launcher.new" -Force -ErrorAction SilentlyContinue }
    if ($snap.LauncherExisted) {
        if ($snap.LauncherBackup -and (Test-Path $snap.LauncherBackup)) {
            # Skip the copy only when the current launcher is byte-identical to the
            # backup (the locked-no-op case, or an unchanged pythonw). Compare CONTENT
            # via hash - not just length - so a genuinely-different same-size launcher
            # is still rolled back. Get-FileHash reads with shared access, so it works
            # even on a running/locked launcher.
            $needRestore = $true
            if (Test-Path $Launcher) {
                $curHash = (Get-FileHash -Path $Launcher -Algorithm SHA256).Hash
                $bakHash = (Get-FileHash -Path $snap.LauncherBackup -Algorithm SHA256).Hash
                if ($curHash -eq $bakHash) { $needRestore = $false }
            }
            if ($needRestore) {
                try {
                    Copy-Item -Path $snap.LauncherBackup -Destination $Launcher -Force -ErrorAction Stop
                } catch {
                    Write-Warning "Failed to restore the previous launcher: $($_.Exception.Message)"
                    $ok = $false
                }
            }
        } else {
            Write-Warning "Launcher backup is missing; cannot restore the previous launcher."
            $ok = $false
        }
    } elseif (Test-Path $Launcher) {
        # Fresh install: remove the launcher the failed run created. Track failure so a
        # leaked/locked orphan is not reported as a complete rollback.
        try {
            Remove-Item -Path $Launcher -Force -ErrorAction Stop
        } catch {
            Write-Warning "Failed to remove the newly-created launcher during rollback: $($_.Exception.Message)"
            $ok = $false
        }
    }

    return $ok
}

function Remove-Backup($snap) {
    if ($snap -and $snap.Dir -and (Test-Path $snap.Dir)) {
        Remove-Item -Path $snap.Dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-Launcher {
    # Atomic swap: copy pythonw.exe to a temp sibling, verify the copy via
    # SHA-256 hash, then rename over the target. The existing launcher is only
    # replaced once a verified copy exists, so a failed/locked copy leaves the
    # old launcher intact.
    $srcHash = (Get-FileHash -Path $Pythonw -Algorithm SHA256).Hash
    $tmp     = "$Launcher.new"
    Copy-Item -Path $Pythonw -Destination $tmp -Force
    $tmpHash = (Get-FileHash -Path $tmp -Algorithm SHA256 -ErrorAction SilentlyContinue).Hash
    if ($tmpHash -ne $srcHash) {
        Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue
        throw "Launcher copy failed or is corrupt: $Launcher"
    }
    Move-Item -Path $tmp -Destination $Launcher -Force
}

function Register-Association {
    Assert-Prerequisites    # aborts before any mutation if assets are missing

    $command = '"{0}" "{1}" "%1"' -f $Launcher, $MainPy
    $icon    = "$IconPath,0"

    $snap = Backup-State    # snapshot BEFORE mutating so we can roll back cleanly
    try {
        # 0) Build the launcher FIRST (atomically) so the open command never
        #    points at a missing/partial file.
        New-Launcher

        # 1) Applications\pdf_editor.exe -> the "Open with" entry (name + icon)
        New-Item -Path $AppsKey -Force | Out-Null
        Set-ItemProperty -Path $AppsKey -Name 'FriendlyAppName' -Value $AppName
        New-Item -Path "$AppsKey\DefaultIcon" -Force | Out-Null
        Set-ItemProperty -Path "$AppsKey\DefaultIcon" -Name '(Default)' -Value $icon
        New-Item -Path "$AppsKey\shell\open\command" -Force | Out-Null
        Set-ItemProperty -Path "$AppsKey\shell\open\command" -Name '(Default)' -Value $command
        New-Item -Path "$AppsKey\SupportedTypes" -Force | Out-Null
        New-ItemProperty -Path "$AppsKey\SupportedTypes" -Name '.pdf' -Value '' -PropertyType String -Force | Out-Null

        if ($SimulateMidwayFailure) { throw "Simulated mid-registration failure (test)" }

        # 2) ProgID -> friendly type name, file icon, open command
        New-Item -Path $ProgIdKey -Force | Out-Null
        Set-ItemProperty -Path $ProgIdKey -Name '(Default)' -Value 'PDF Document'
        Set-ItemProperty -Path $ProgIdKey -Name 'FriendlyTypeName' -Value $AppName
        New-Item -Path "$ProgIdKey\DefaultIcon" -Force | Out-Null
        Set-ItemProperty -Path "$ProgIdKey\DefaultIcon" -Name '(Default)' -Value $icon
        New-Item -Path "$ProgIdKey\shell\open\command" -Force | Out-Null
        Set-ItemProperty -Path "$ProgIdKey\shell\open\command" -Name '(Default)' -Value $command

        # Drop any stale OpenWithProgids entry from older runs (showed as "Python").
        if (Test-Path $PdfProgids) {
            Remove-ItemProperty -Path $PdfProgids -Name $ProgId -ErrorAction SilentlyContinue
        }

        # 3) Capabilities so it shows in Settings > Default apps
        New-Item -Path $CapKey -Force | Out-Null
        Set-ItemProperty -Path $CapKey -Name 'ApplicationName' -Value $AppName
        Set-ItemProperty -Path $CapKey -Name 'ApplicationDescription' -Value 'Minimalist PDF editor'
        New-Item -Path "$CapKey\FileAssociations" -Force | Out-Null
        Set-ItemProperty -Path "$CapKey\FileAssociations" -Name '.pdf' -Value $ProgId
        New-Item -Path $RegAppsKey -Force | Out-Null
        Set-ItemProperty -Path $RegAppsKey -Name $AppName -Value "Software\$AppRegName\Capabilities"
    } catch {
        Write-Warning "Registration failed: $($_.Exception.Message)"
        Write-Warning "Restoring the previous registration (snapshot)..."
        $restored = Restore-State $snap
        Remove-Backup $snap
        if ($restored) {
            throw "Registration aborted; the previous registration and launcher were restored. No working handler was lost."
        } else {
            throw "Registration aborted, and rollback was INCOMPLETE (see warnings above) - some managed state may be inconsistent. Re-run with -Unregister, then register again, or check Settings > Default apps."
        }
    }

    Remove-Backup $snap
    Invoke-ShellAssocRefresh

    Write-Host ''
    Write-Host "Registered '$AppName' as a .pdf handler (current user)." -ForegroundColor Green
    Write-Host "Launcher: $Launcher"
    Write-Host "Command:  $command"
    Write-Host "Icon:     $IconPath"
    Write-Host ''
    Write-Host "ONE STEP LEFT - make it the default:" -ForegroundColor Yellow
    Write-Host "  Right-click any .pdf  ->  Open with  ->  Choose another app"
    Write-Host "  ->  pick '$AppName' (now shows with the reiya icon)"
    Write-Host "  ->  tick 'Always use this app'  ->  OK"
    Write-Host "  (or: Settings > Apps > Default apps > type .pdf > pick '$AppName')"
}

function Unregister-Association {
    Remove-Managed
    Invoke-ShellAssocRefresh
    Write-Host "Unregistered '$AppName'. (If it was still the default, reset it in Settings > Default apps.)" -ForegroundColor Green
}

try {
    if ($Unregister) { Unregister-Association } else { Register-Association }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
