@echo off
REM Publish the loopback port through Cloudflare. Install once with:
REM   winget install --id Cloudflare.cloudflared
REM Copy the printed https URL, then append /<token>/mcp from run-http.cmd output.
cloudflared tunnel --url http://127.0.0.1:18765
