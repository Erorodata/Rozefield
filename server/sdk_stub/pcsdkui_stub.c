/* Rozefield SDK stub — drop-in replacement for OverField's PCSDKUI.exe (QuickSDK PC login window).
 * The game starts PCSDKUI.exe with "gameName||qgpc&action||callLogin&url||..." and listens on
 * \\.\pipe\quickpc<gameName>. The real SDK opens a web login and then writes one JSON message per pipe
 * connection. This stub skips the web page and immediately reports a successful login with the
 * uid/username from rozefield_sdk.ini (next to the exe). The token is ignored by the Rozefield server. */
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <string.h>

static char g_dir[MAX_PATH];
static FILE *g_log;
static char g_pipe[256] = "\\\\.\\pipe\\quickpc";

static void logf_(const char *fmt, const char *a) {
    if (!g_log) return;
    SYSTEMTIME t; GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
    fprintf(g_log, fmt, a); fputc('\n', g_log); fflush(g_log);
}

static int send_msg(const char *json) {
    for (int i = 0; i < 100; i++) {
        HANDLE h = CreateFileA(g_pipe, GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
        if (h != INVALID_HANDLE_VALUE) {
            DWORD w = 0;
            BOOL ok = WriteFile(h, json, (DWORD)strlen(json), &w, NULL);
            FlushFileBuffers(h);
            CloseHandle(h);
            logf_(ok ? "sent %s" : "write failed %s", json);
            return ok;
        }
        DWORD err = GetLastError();
        if (i == 0 || i == 99) { char b[64]; snprintf(b, sizeof b, "%lu", err); logf_("open pipe error %s", b); }
        if (err == ERROR_PIPE_BUSY) WaitNamedPipeA(g_pipe, 2000);
        else Sleep(100);
    }
    logf_("could not open pipe for %s", json);
    return 0;
}

static DWORD parent_pid(void) {
    DWORD me = GetCurrentProcessId(), pp = 0;
    HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 e; e.dwSize = sizeof e;
    if (Process32First(s, &e)) do { if (e.th32ProcessID == me) { pp = e.th32ParentProcessID; break; } } while (Process32Next(s, &e));
    CloseHandle(s);
    return pp;
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    GetModuleFileNameA(NULL, g_dir, MAX_PATH);
    char *sl = strrchr(g_dir, '\\'); if (sl) sl[1] = 0;
    char path[MAX_PATH * 2];
    snprintf(path, sizeof path, "%srozefield_sdk.log", g_dir); g_log = fopen(path, "a");
    logf_("started: %s", cmd);
    snprintf(path, sizeof path, "%srozefield_sdk.ini", g_dir);
    char uid[64], user[128];
    GetPrivateProfileStringA("account", "uid", "10000001", uid, sizeof uid, path);
    GetPrivateProfileStringA("account", "username", "rozefield", user, sizeof user, path);

    /* real PCSDKUI uses "\\.\pipe\quickpc" + gameName (game passes gameName||qgpc) */
    const char *gn = strstr(cmd, "gameName||");
    if (gn) {
        gn += 10; size_t n = strcspn(gn, "& \"");
        size_t L = strlen(g_pipe); if (n > sizeof g_pipe - L - 1) n = sizeof g_pipe - L - 1;
        memcpy(g_pipe + L, gn, n); g_pipe[L + n] = 0;
    }
    logf_("pipe %s", g_pipe);
    if (strstr(cmd, "action||callLogin")) {
        char msg[1024];
        send_msg("{\"action\":\"init\",\"params\":{}}");
        Sleep(500);
        snprintf(msg, sizeof msg,
                 "{\"action\":\"loginSuccess\",\"params\":{\"authToken\":\"@114@111@122@101@\",\"timeleft\":\"-1\","
                 "\"uid\":\"%s\",\"userToken\":\"@114@111@122@101@\",\"username\":\"%s\"}}", uid, user);
        send_msg(msg);
    } else if (strstr(cmd, "action||callPay")) {
        send_msg("{\"action\":\"payCancel\",\"params\":{}}");
        return 0;
    } else {
        logf_("action not handled, exiting: %s", cmd);
        return 0;
    }
    /* stay alive like the real SDK window until the game exits */
    HANDLE g = OpenProcess(SYNCHRONIZE, FALSE, parent_pid());
    if (g) { WaitForSingleObject(g, INFINITE); CloseHandle(g); }
    logf_("game exited%s", "");
    return 0;
}
