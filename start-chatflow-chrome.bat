@echo off
REM ===============================================================
REM  Start Chrome for ChatBot Automator
REM
REM  Opens Chrome on a DEDICATED profile (C:\chatflow-chrome) with the
REM  DevTools port the app connects to. Your everyday Chrome profile,
REM  tabs and extensions are NOT touched, and this works even when
REM  Chrome is already running. Log in to the chat once in this window;
REM  the login is remembered in the profile folder.
REM
REM  See README section 2 "Start Chrome with Remote Debugging".
REM ===============================================================
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chatflow-chrome" https://ru.virt-chat.com/chat
