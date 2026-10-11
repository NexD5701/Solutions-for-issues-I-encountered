# Windows Codex Mobile Remote-Control Pairing Timeout

**Status:** Resolved in one Windows setup  
**Affected setup:** Windows, Microsoft Store (MSIX) version of Codex  
**Observed package build:** 26.1002.7124.0  
**Local proxy used in the report:** `http://127.0.0.1:7892`

[中文概要](#中文概要) · [Related upstream report](https://github.com/openai/codex/issues/31387)

## Symptom

The Codex desktop app could be opened, but setting up remote control for the ChatGPT mobile app did not complete. The pairing-code flow reported:

> Pairing code unavailable: Timed out waiting for remote control to connect

This note covers the mobile remote-control pairing failure in the setup above. It does not document a separate workaround for web-page access.

## Confirmed workaround

The decisive change was providing the proxy environment variables to the Codex process. Launch Codex from the same PowerShell session after setting them, so the app inherits them.

1. Start the local proxy and confirm its listening address and port. The example below uses port `7892`; replace it if your proxy uses another port.
2. Fully exit Codex. A process that is already running will not inherit environment variables set later.
3. Open PowerShell and run:

```powershell
$env:HTTP_PROXY = "http://127.0.0.1:7892"
$env:HTTPS_PROXY = "http://127.0.0.1:7892"
$env:NO_PROXY = "localhost,127.0.0.1,::1"

$package = Get-AppxPackage -Name "OpenAI.Codex" | Select-Object -First 1
if (-not $package) {
    throw "Microsoft Store version of Codex was not found."
}

$exe = Join-Path $package.InstallLocation "app\ChatGPT.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "ChatGPT.exe was not found in the installed package."
}

Start-Process -FilePath $exe
```

4. In Codex, retry the remote-control setup and pair from the ChatGPT mobile app.

The package lookup avoids hard-coding the versioned folder under `C:\Program Files\WindowsApps`. If your installed package layout differs, locate its actual `ChatGPT.exe` and launch that executable from the same PowerShell session.

## Why this worked

In this case, setting `HTTP_PROXY` and `HTTPS_PROXY` before starting Codex was the effective fix. Starting the app from that PowerShell session passes those variables to its process. `NO_PROXY` leaves local loopback addresses out of the proxy path.

The environment variables set this way apply to processes launched from that PowerShell session; they do not permanently change the Windows-wide proxy settings.

## Verification

The reported success criterion was that Codex generated the pairing code and mobile remote-control setup completed after launch with the proxy variables set.

If pairing still times out, first confirm the proxy is running at the address and port configured above, then confirm Codex was fully exited before relaunching. This report does not establish a fix for enrollment, authentication, backend, or other network failures.

## Scope and notes

- This is a user-reported workaround for a Windows Store/MSIX setup, not an official or universal Codex fix.
- The local proxy port and MSIX install path vary by machine.
- The separate `system_proxy_fallback = true` configuration discussed during troubleshooting addressed a different web-access/proxy issue; it is not the mobile pairing fix documented here.
- Related upstream discussion: [openai/codex issue #31387](https://github.com/openai/codex/issues/31387). This repository entry records the tested environment-specific workaround.

## 中文概要

**现象：** Windows Microsoft Store（MSIX）版 Codex 的手机远程控制配对一直超时，无法生成配对码。

**解决方式：** 在 PowerShell 中先设置 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`，再从同一个 PowerShell 会话启动 `ChatGPT.exe`。决定性因素是让 Codex 进程在启动时继承代理环境变量。示例端口为 `7892`，需要按本机代理设置调整。

**验证：** 用户报告设置环境变量并从该会话启动后，配对恢复正常。此记录只适用于该 Windows/MSIX 与代理场景；它不是所有配对失败的通用修复。

**区分：** 排查中提到的 `system_proxy_fallback = true` 属于另一个网页访问/代理问题，不是这里的手机配对解决方案。
