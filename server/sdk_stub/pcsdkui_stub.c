/* Rozefield SDK stub — drop-in replacement for OverField's PCSDKUI.exe (QuickSDK PC login window).
 * The game starts PCSDKUI.exe with "gameName||qgpc&action||callLogin&url||..." and listens on
 * \\.\pipe\quickpc<gameName>. The real SDK opens a web login and then writes one JSON message per pipe
 * connection. This stub skips the web page and immediately reports a successful login with the
 * name the player types in a small window; the name travels in the token, uid = "rz_<lower-case name>". */
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


/* ---- tiny "enter your name" window (no resource file needed) ---- */
static char g_name[64];
static HWND g_edit;
static int g_done;
static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_COMMAND && (LOWORD(w) == 1 || LOWORD(w) == IDOK)) {
        GetWindowTextA(g_edit, g_name, sizeof g_name);
        if (g_name[0]) { g_done = 1; DestroyWindow(h); }
        return 0;
    }
    if (m == WM_CLOSE) { g_done = -1; DestroyWindow(h); return 0; }
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcA(h, m, w, l);
}
static int ask_name(const char *def) {
    WNDCLASSA wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "RozefieldLogin"; wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1); wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassA(&wc);
    int W = 360, Hh = 170, x = (GetSystemMetrics(SM_CXSCREEN) - W) / 2, y = (GetSystemMetrics(SM_CYSCREEN) - Hh) / 2;
    HWND h = CreateWindowExA(WS_EX_TOPMOST, "RozefieldLogin", "Rozefield - OverField login", WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                             x, y, W, Hh, NULL, NULL, wc.hInstance, NULL);
    CreateWindowA("STATIC", "Player name (a new name creates a new account):", WS_CHILD | WS_VISIBLE, 16, 14, 320, 20, h, NULL, NULL, NULL);
    g_edit = CreateWindowExA(WS_EX_CLIENTEDGE, "EDIT", def, WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 16, 40, 312, 26, h, NULL, NULL, NULL);
    SendMessageA(g_edit, EM_LIMITTEXT, 20, 0);
    CreateWindowA("BUTTON", "Log in", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON, 228, 80, 100, 30, h, (HMENU)1, NULL, NULL);
    SetForegroundWindow(h); SetFocus(g_edit); SendMessageA(g_edit, EM_SETSEL, 0, -1);
    MSG msg;
    while (GetMessageA(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN) { SendMessageA(h, WM_COMMAND, 1, 0); continue; }
        TranslateMessage(&msg); DispatchMessageA(&msg);
    }
    return g_done == 1;
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

    /* The game (C#) creates the pipe as "\\quickpc" + its process id. Find it by listing all pipes. */
    {
        WIN32_FIND_DATAA fd; HANDLE f = FindFirstFileA("\\\\.\\pipe\\*", &fd);
        DWORD pp = parent_pid(); char want[64]; snprintf(want, sizeof want, "quickpc%lu", pp);
        int found = 0;
        for (int tries = 0; tries < 50 && !found; tries++) {
            f = FindFirstFileA("\\\\.\\pipe\\*", &fd);
            if (f != INVALID_HANDLE_VALUE) {
                do {
                    if (strstr(fd.cFileName, "quickpc")) {
                        snprintf(g_pipe, sizeof g_pipe, "\\\\.\\pipe\\%s", fd.cFileName);
                        found = 1;
                        if (strstr(fd.cFileName, want)) break;
                    }
                } while (FindNextFileA(f, &fd));
                FindClose(f);
            }
            if (!found) Sleep(200);
        }
        logf_("pipe search done (parent %s)", want);
    }
    logf_("pipe %s", g_pipe);
    if (strstr(cmd, "action||callLogin")) {
        char msg[1024], tok[512] = "@", uidbuf[96];
        GetPrivateProfileStringA("account", "last_name", user, g_name, sizeof g_name, path);
        if (!ask_name(g_name)) {
            send_msg("{\"action\":\"init\",\"params\":{}}");
            send_msg("{\"action\":\"loginCancel\",\"params\":{}}");
            return 0;
        }
        WritePrivateProfileStringA("account", "last_name", g_name, path);
        /* the account key is the lower-cased name; the name itself travels in the token */
        snprintf(uidbuf, sizeof uidbuf, "rz_%s", g_name);
        for (char *c = uidbuf; *c; c++) { if (*c >= 'A' && *c <= 'Z') *c += 32; if (*c == '"' || *c == '\\') *c = '_'; }
        for (unsigned char *c = (unsigned char *)g_name; *c && strlen(tok) < sizeof tok - 6; c++) {
            char b[8]; snprintf(b, sizeof b, "%u@", *c); strcat(tok, b);
        }
        send_msg("{\"action\":\"init\",\"params\":{}}");
        Sleep(300);
        snprintf(msg, sizeof msg,
                 "{\"action\":\"loginSuccess\",\"params\":{\"authToken\":\"%s\",\"timeleft\":\"-1\","
                 "\"uid\":\"%s\",\"userToken\":\"%s\",\"username\":\"%s\"}}", tok, uidbuf, tok, uidbuf);
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
