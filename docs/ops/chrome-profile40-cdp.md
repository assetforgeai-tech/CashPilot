# Chrome Profile 40 CDP Runbook

Use the dedicated copy of Chrome profile 40. Do not attach CDP to the default Chrome `User Data` directory.

## Start

Close the dedicated CDP Chrome window before restarting it. Keep unrelated Chrome profiles untouched.

```powershell
$chromeExe = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$chromeArgs = '--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="C:\Users\KALINH\AppData\Local\Google\Chrome\User Data CDP" --profile-directory="Profile 40" --no-first-run'
Start-Process -FilePath $chromeExe -ArgumentList $chromeArgs
```

## Verify

```powershell
Test-NetConnection 127.0.0.1 -Port 9222
Invoke-RestMethod -Uri 'http://127.0.0.1:9222/json/version'
Invoke-RestMethod -Uri 'http://127.0.0.1:9222/json/list' |
  Select-Object title, url, webSocketDebuggerUrl
```

Expected: `TcpTestSucceeded` is `True`, and `/json/version` contains `webSocketDebuggerUrl`.

## Safety

- Bind CDP to `127.0.0.1` only; never expose port `9222` to LAN or Internet.
- Do not copy cookies, passwords, provider tokens, or API keys into evidence or chat.
- Use read-only navigation/snapshot first. Confirm before any provider mutation.
- The CDP copy is separate from the normal Chrome profile and may require a one-time provider login.
