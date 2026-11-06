/*
 * ClipBridge.exe for the portable Windows package.
 *
 * Starts  runtime\pythonw.exe app\ClipBridge.pyw  from the folder this exe lives in, passing any
 * arguments through (e.g. --tray), and sets CLIPBRIDGE_LAUNCHER so "Start with Windows" points here.
 * Build (any OS):  zig build-exe launcher.c launcher.rc -target x86_64-windows-gnu -lc -O ReleaseSmall
 *                  --subsystem windows -femit-bin=ClipBridge.exe
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

#define BUF 4096

static const wchar_t *skip_program_name(const wchar_t *cmd) {
    /* GetCommandLineW() starts with our own (maybe quoted) path; return what follows it. */
    if (*cmd == L'"') {
        cmd++;
        while (*cmd && *cmd != L'"') cmd++;
        if (*cmd == L'"') cmd++;
    } else {
        while (*cmd && *cmd != L' ' && *cmd != L'\t') cmd++;
    }
    while (*cmd == L' ' || *cmd == L'\t') cmd++;
    return cmd;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR ansi_cmd, int show) {
    (void)inst; (void)prev; (void)ansi_cmd; (void)show;
    wchar_t self[BUF], dir[BUF], python[BUF], script[BUF], cmdline[BUF * 3];

    DWORD n = GetModuleFileNameW(NULL, self, BUF);
    if (n == 0 || n >= BUF) return 1;
    wcscpy(dir, self);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    wcscpy(python, dir);
    wcscat(python, L"\\runtime\\pythonw.exe");
    wcscpy(script, dir);
    wcscat(script, L"\\app\\ClipBridge.pyw");

    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL,
                    L"ClipBridge can't find its \"runtime\" and \"app\" folders.\n\n"
                    L"Unzip the whole ClipBridge folder first (right-click the zip \x2192 Extract All), "
                    L"then run ClipBridge.exe from inside it.",
                    L"ClipBridge", MB_ICONERROR | MB_OK);
        return 1;
    }

    SetEnvironmentVariableW(L"CLIPBRIDGE_LAUNCHER", self);

    const wchar_t *args = skip_program_name(GetCommandLineW());
    wcscpy(cmdline, L"\"");
    wcscat(cmdline, python);
    wcscat(cmdline, L"\" \"");
    wcscat(cmdline, script);
    wcscat(cmdline, L"\"");
    if (*args && wcslen(args) < BUF) {
        wcscat(cmdline, L" ");
        wcscat(cmdline, args);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(python, cmdline, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"ClipBridge couldn't start its runtime. Try extracting the zip again.",
                    L"ClipBridge", MB_ICONERROR | MB_OK);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
