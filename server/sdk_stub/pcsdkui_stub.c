/* Rozefield SDK stub — drop-in replacement for OverField's PCSDKUI.exe (QuickSDK PC login window).
 * The game starts PCSDKUI.exe with "gameName||qgpc&action||callLogin&url||..." and listens on
 * \\.\pipe\quickpc<gameName>. The real SDK opens a web login and then writes one JSON message per pipe
 * connection. This stub skips the web page and immediately reports a successful login with the
 * name the player types in a small window; the name travels in the token, uid = "rz_<lower-case name>". */
#include <winsock2.h>
#include <windows.h>
#include <tlhelp32.h>
#include <commdlg.h>
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


/* ---- account picker window: lists accounts from the Rozefield server, or creates a new one ---- */
#include <winsock2.h>
static char g_name[128], g_uid[160];
static char g_list_uid[64][160], g_list_name[64][128];
static int g_n, g_done;
static HWND g_lb, g_edit;
static char g_host[64] = "127.0.0.1";
static void add_row(int i, const char *lv);

static void fetch_accounts(const char *host) {
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18881); a.sin_addr.s_addr = inet_addr(host);
    DWORD to = 2000; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    if (connect(s, (struct sockaddr *)&a, sizeof a) != 0) { closesocket(s); return; }
    const char *req = "GET /rozefield/accounts HTTP/1.0\r\nHost: rozefield\r\n\r\n";
    send(s, req, (int)strlen(req), 0);
    static char buf[65536]; int len = 0, r;
    while (len < (int)sizeof buf - 1 && (r = recv(s, buf + len, sizeof buf - 1 - len, 0)) > 0) len += r;
    buf[len] = 0; closesocket(s);
    char *body = strstr(buf, "\r\n\r\n"); if (!body) return; body += 4;
    for (char *line = strtok(body, "\n"); line && g_n < 64; line = strtok(NULL, "\n")) {
        char *bar = strchr(line, '|'); if (!bar) continue; *bar = 0;
        char *bar2 = strchr(bar + 1, '|'); char lv[16] = "";
        if (bar2) { *bar2 = 0; snprintf(lv, sizeof lv, "%s", bar2 + 1); }
        snprintf(g_list_uid[g_n], 160, "%s", line);
        snprintf(g_list_name[g_n], 128, "%s", bar + 1);
        g_n++;
        (void)lv;
    }
}
/* Upload a .rzsave backup (made with RozefieldBackup.exe on the official server) to the Rozefield server.
 * Reply: "OK|uid|name" or "ERR|reason". */
static int import_backup(HWND h) {
    wchar_t fn[MAX_PATH] = L"";
    OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = h;
    of.lpstrFilter = L"Rozefield backup (*.rzsave)\0*.rzsave\0All files\0*.*\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH;
    of.Flags = OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR; of.lpstrTitle = L"Choose your backup (.rzsave)";
    if (!GetOpenFileNameW(&of)) return 0;
    HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) { MessageBoxW(h, L"Could not open that file.", L"Rozefield", MB_OK); return 0; }
    DWORD size = GetFileSize(f, NULL), got = 0;
    char *data = (char *)malloc(size ? size : 1);
    ReadFile(f, data, size, &got, NULL); CloseHandle(f);
    SetCursor(LoadCursor(NULL, IDC_WAIT));
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18881); a.sin_addr.s_addr = inet_addr(g_host);
    DWORD to = 120000; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    static char resp[4096]; int len = 0, r;
    resp[0] = 0;
    if (connect(s, (struct sockaddr *)&a, sizeof a) == 0) {
        char hdr[256];
        int hl = snprintf(hdr, sizeof hdr, "POST /rozefield/import HTTP/1.0\r\nHost: rozefield\r\nContent-Type: application/octet-stream\r\n"
                                           "Content-Length: %lu\r\n\r\n", (unsigned long)got);
        send(s, hdr, hl, 0);
        for (DWORD off = 0; off < got;) { int n = send(s, data + off, (int)(got - off > 65536 ? 65536 : got - off), 0); if (n <= 0) break; off += n; }
        while (len < (int)sizeof resp - 1 && (r = recv(s, resp + len, sizeof resp - 1 - len, 0)) > 0) len += r;
        resp[len] = 0;
    }
    closesocket(s); free(data);
    SetCursor(LoadCursor(NULL, IDC_ARROW));
    char *body = strstr(resp, "\r\n\r\n"); body = body ? body + 4 : NULL;
    wchar_t msg[600];
    if (!body) { MessageBoxW(h, L"The Rozefield server did not answer. Is it running?", L"Rozefield", MB_OK | MB_ICONWARNING); return 0; }
    if (strncmp(body, "OK|", 3) == 0) {
        char *uid = body + 3, *nm = strchr(uid, '|');
        if (nm) *nm++ = 0; else nm = uid;
        if (g_n < 64) {
            int i = g_n;
            for (int k = 0; k < g_n; k++) if (strcmp(g_list_uid[k], uid) == 0) i = k;
            snprintf(g_list_uid[i], 160, "%s", uid); snprintf(g_list_name[i], 128, "%s", nm);
            if (i == g_n) { g_n++; add_row(i, ""); }
            SendMessageW(g_lb, LB_SETCURSEL, i, 0);
        }
        wchar_t wn[128]; MultiByteToWideChar(CP_UTF8, 0, nm, -1, wn, 128);
        swprintf(msg, 600, L"Imported \"%ls\". Select it and press Play.", wn);
        MessageBoxW(h, msg, L"Rozefield", MB_OK | MB_ICONINFORMATION);
        return 1;
    }
    wchar_t wb[512]; MultiByteToWideChar(CP_UTF8, 0, strncmp(body, "ERR|", 4) == 0 ? body + 4 : body, -1, wb, 512);
    swprintf(msg, 600, L"Import failed: %ls", wb);
    MessageBoxW(h, msg, L"Rozefield", MB_OK | MB_ICONWARNING);
    return 0;
}

static void add_row(int i, const char *lv) {
    wchar_t wn[128], row[200]; MultiByteToWideChar(CP_UTF8, 0, g_list_name[i], -1, wn, 128);
    swprintf(row, 200, L"%ls", wn);
    SendMessageW(g_lb, LB_ADDSTRING, 0, (LPARAM)row);
}
static void finish(HWND h, int i) {
    snprintf(g_uid, sizeof g_uid, "%s", g_list_uid[i]); snprintf(g_name, sizeof g_name, "%s", g_list_name[i]);
    g_done = 1; DestroyWindow(h);
}
static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_COMMAND) {
        int id = LOWORD(w);
        if (id == 1 || (id == 10 && HIWORD(w) == LBN_DBLCLK)) {          /* Play selected */
            int i = (int)SendMessageW(g_lb, LB_GETCURSEL, 0, 0);
            if (i >= 0) finish(h, i);
            return 0;
        }
        if (id == 3) { import_backup(h); return 0; }                    /* Import backup */
        if (id == 2) {                                                   /* Create new */
            wchar_t wn[64]; GetWindowTextW(g_edit, wn, 64);
            if (!wn[0]) { MessageBoxW(h, L"Type a name for the new account.", L"Rozefield", MB_OK); return 0; }
            WideCharToMultiByte(CP_UTF8, 0, wn, -1, g_name, sizeof g_name, NULL, NULL);
            for (int i = 0; i < g_n; i++)
                if (_stricmp(g_list_name[i], g_name) == 0) { MessageBoxW(h, L"That name already exists - select it in the list.", L"Rozefield", MB_OK); return 0; }
            char low[128]; snprintf(low, sizeof low, "%s", g_name);
            for (char *c = low; *c; c++) { if (*c >= 'A' && *c <= 'Z') *c += 32; if (*c == '"' || *c == '\\' || *c == '|') *c = '_'; }
            snprintf(g_uid, sizeof g_uid, "rz_%s", low);
            g_done = 1; DestroyWindow(h); return 0;
        }
    }
    if (m == WM_CLOSE) { g_done = -1; DestroyWindow(h); return 0; }
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(h, m, w, l);
}
static int pick_account(const char *host, const char *last) {
    snprintf(g_host, sizeof g_host, "%s", host);
    fetch_accounts(host);
    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"RozefieldLogin"; wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1); wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);
    int W = 380, Hh = 440, x = (GetSystemMetrics(SM_CXSCREEN) - W) / 2, y = (GetSystemMetrics(SM_CYSCREEN) - Hh) / 2;
    HWND h = CreateWindowExW(WS_EX_TOPMOST, L"RozefieldLogin", L"Rozefield - choose your account", WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                             x, y, W, Hh, NULL, NULL, wc.hInstance, NULL);
    HFONT f = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HWND t1 = CreateWindowW(L"STATIC", g_n ? L"Accounts on this server:" : L"No accounts yet - create one below.", WS_CHILD | WS_VISIBLE, 16, 12, 340, 18, h, NULL, NULL, NULL);
    g_lb = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOTIFY | WS_TABSTOP, 16, 34, 240, 220, h, (HMENU)10, NULL, NULL);
    HWND b1 = CreateWindowW(L"BUTTON", L"Play", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON, 266, 34, 90, 32, h, (HMENU)1, NULL, NULL);
    HWND t2 = CreateWindowW(L"STATIC", L"New account name:", WS_CHILD | WS_VISIBLE, 16, 270, 340, 18, h, NULL, NULL, NULL);
    g_edit = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 16, 292, 240, 26, h, NULL, NULL, NULL);
    HWND b2 = CreateWindowW(L"BUTTON", L"Create", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 266, 290, 90, 30, h, (HMENU)2, NULL, NULL);
    HWND b3 = CreateWindowW(L"BUTTON", L"Import backup (.rzsave) from the official server...", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 16, 336, 340, 30, h, (HMENU)3, NULL, NULL);
    HWND ctl[] = {t1, g_lb, b1, t2, g_edit, b2, b3};
    for (int i = 0; i < 7; i++) SendMessageW(ctl[i], WM_SETFONT, (WPARAM)f, TRUE);
    SendMessageW(g_edit, EM_LIMITTEXT, 20, 0);
    int sel = 0;
    for (int i = 0; i < g_n; i++) { add_row(i, ""); if (last && strcmp(g_list_uid[i], last) == 0) sel = i; }
    if (g_n) SendMessageW(g_lb, LB_SETCURSEL, sel, 0);
    SetForegroundWindow(h); SetFocus(g_n ? g_lb : g_edit);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN) { SendMessageW(h, WM_COMMAND, GetFocus() == g_edit ? 2 : 1, 0); continue; }
        if (!IsDialogMessageW(h, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
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
        char msg[1024], tok[512] = "@", host[64], last[160];
        GetPrivateProfileStringA("server", "ip", "127.0.0.1", host, sizeof host, path);
        GetPrivateProfileStringA("account", "last_uid", "", last, sizeof last, path);
        if (!pick_account(host, last)) {
            send_msg("{\"action\":\"init\",\"params\":{}}");
            send_msg("{\"action\":\"loginCancel\",\"params\":{}}");
            return 0;
        }
        WritePrivateProfileStringA("account", "last_uid", g_uid, path);
        /* the account key is the uid; the display name travels in the token as @byte@byte@ */
        for (unsigned char *c = (unsigned char *)g_name; *c && strlen(tok) < sizeof tok - 6; c++) {
            char b[8]; snprintf(b, sizeof b, "%u@", *c); strcat(tok, b);
        }
        send_msg("{\"action\":\"init\",\"params\":{}}");
        Sleep(300);
        snprintf(msg, sizeof msg,
                 "{\"action\":\"loginSuccess\",\"params\":{\"authToken\":\"%s\",\"timeleft\":\"-1\","
                 "\"uid\":\"%s\",\"userToken\":\"%s\",\"username\":\"%s\"}}", tok, g_uid, tok, g_uid);
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
