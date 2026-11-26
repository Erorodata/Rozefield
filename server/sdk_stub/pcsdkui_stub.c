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
#include <time.h>

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


/* ---- login card: a dark see-through card centred over the game's intro screen ---------------------
 * Log in / Create account tabs, account name + password (+ confirm), "Remember me", accounts saved on this
 * PC, Import official backup, Forgot password. The server checks the password (POST /rozefield/login or
 * /rozefield/register) and hands back a one-time key that goes to the game inside the login token. */
static char g_name[128], g_uid[160], g_key[64];
static int g_done, g_tab;            /* 0 = log in, 1 = create account */
static HWND g_win, g_ename, g_epw, g_epw2, g_btn;
static char g_host[64] = "127.0.0.1", g_ini[MAX_PATH * 2];
static wchar_t g_err[256];
static int g_remember = 1;
static char g_saved[8][128]; static int g_nsaved;
static HFONT g_ftitle, g_fbody, g_fsmall, g_fbtn;
static HBRUSH g_brcard, g_brfield;
#define C_CARD RGB(20, 22, 30)
#define C_FIELD RGB(36, 39, 50)
#define C_TEXT RGB(236, 238, 244)
#define C_MUTED RGB(150, 155, 170)
#define C_ACCENT RGB(236, 110, 150)
#define C_ERR RGB(255, 120, 120)
#define CW 380
#define CH 520
static RECT r_close = {CW - 44, 14, CW - 14, 44}, r_tab0 = {28, 70, 120, 100}, r_tab1 = {136, 70, 280, 100};
static RECT r_rem = {28, 0, 220, 0}, r_import = {28, CH - 46, 200, CH - 22}, r_forgot = {CW - 150, CH - 46, CW - 28, CH - 22};
static RECT r_chip[8];

static int http_post(const char *path, const char *body, int blen, char *out, int outsz, int timeout_ms) {
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18881); a.sin_addr.s_addr = inet_addr(g_host);
    DWORD to = timeout_ms; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    out[0] = 0;
    if (connect(s, (struct sockaddr *)&a, sizeof a) != 0) { closesocket(s); return 0; }
    char hdr[256];
    int hl = snprintf(hdr, sizeof hdr, "POST %s HTTP/1.0\r\nHost: rozefield\r\nContent-Type: application/octet-stream\r\nContent-Length: %d\r\n\r\n", path, blen);
    send(s, hdr, hl, 0);
    for (int off = 0; off < blen;) { int n = send(s, body + off, blen - off > 65536 ? 65536 : blen - off, 0); if (n <= 0) break; off += n; }
    int len = 0, r;
    static char resp[8192];
    while (len < (int)sizeof resp - 1 && (r = recv(s, resp + len, sizeof resp - 1 - len, 0)) > 0) len += r;
    resp[len] = 0; closesocket(s);
    char *b = strstr(resp, "\r\n\r\n"); if (!b) return 0;
    snprintf(out, outsz, "%s", b + 4);
    return 1;
}

static void load_saved(void) {
    char buf[1024]; GetPrivateProfileStringA("account", "saved", "", buf, sizeof buf, g_ini);
    g_nsaved = 0;
    for (char *t = strtok(buf, "|"); t && g_nsaved < 8; t = strtok(NULL, "|")) snprintf(g_saved[g_nsaved++], 128, "%s", t);
}
static void remember_name(const char *nm) {
    char buf[1100] = ""; int has = 0;
    for (int i = 0; i < g_nsaved; i++) if (_stricmp(g_saved[i], nm) == 0) has = 1;
    snprintf(buf, sizeof buf, "%s", nm);
    for (int i = 0; i < g_nsaved && i < 7; i++) if (_stricmp(g_saved[i], nm) != 0) { strcat(buf, "|"); strcat(buf, g_saved[i]); }
    (void)has;
    WritePrivateProfileStringA("account", "saved", buf, g_ini);
}

static void layout(void) {
    int y = 122;
    MoveWindow(g_ename, 28, y + 22, CW - 56, 30, TRUE); y += 64;
    MoveWindow(g_epw, 28, y + 22, CW - 56, 30, TRUE); y += 64;
    ShowWindow(g_epw2, g_tab ? SW_SHOW : SW_HIDE);
    if (g_tab) { MoveWindow(g_epw2, 28, y + 22, CW - 56, 30, TRUE); y += 64; }
    r_rem.top = y + 2; r_rem.bottom = y + 24; y += 34;
    MoveWindow(g_btn, 28, y, CW - 56, 42, TRUE);
    SetWindowTextW(g_btn, g_tab ? L"Create account" : L"Enter game");
    InvalidateRect(g_win, NULL, TRUE);
}

static void text(HDC dc, HFONT f, COLORREF c, int x, int y, const wchar_t *s) {
    SelectObject(dc, f); SetTextColor(dc, c); SetBkMode(dc, TRANSPARENT); TextOutW(dc, x, y, s, (int)wcslen(s));
}

static void paint(HWND h) {
    PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
    RECT rc; GetClientRect(h, &rc); FillRect(dc, &rc, g_brcard);
    text(dc, g_ftitle, C_TEXT, 28, 22, L"Rozefield");
    text(dc, g_fbody, C_MUTED, CW - 36, 18, L"\x00D7");
    text(dc, g_fbody, g_tab ? C_MUTED : C_TEXT, 28, 74, L"Log in");
    text(dc, g_fbody, g_tab ? C_TEXT : C_MUTED, 136, 74, L"Create account");
    HBRUSH acc = CreateSolidBrush(C_ACCENT);
    RECT ul = g_tab ? (RECT){136, 98, 254, 100} : (RECT){28, 98, 76, 100}; FillRect(dc, &ul, acc);
    HBRUSH line = CreateSolidBrush(RGB(48, 52, 64)); RECT ln = {28, 100, CW - 28, 101}; FillRect(dc, &ln, line); DeleteObject(line);
    int y = 122;
    text(dc, g_fsmall, C_MUTED, 28, y, L"Account name"); y += 64;
    text(dc, g_fsmall, C_MUTED, 28, y, L"Password"); y += 64;
    if (g_tab) { text(dc, g_fsmall, C_MUTED, 28, y, L"Confirm password"); }
    /* remember me: a small box */
    RECT bx = {r_rem.left, r_rem.top + 4, r_rem.left + 14, r_rem.top + 18};
    HBRUSH fb = CreateSolidBrush(g_remember ? C_ACCENT : C_FIELD); FillRect(dc, &bx, fb); DeleteObject(fb);
    text(dc, g_fsmall, C_MUTED, r_rem.left + 22, r_rem.top + 2, L"Remember me on this PC");
    if (g_err[0]) text(dc, g_fsmall, C_ERR, 28, r_rem.top + 82, g_err);
    /* saved accounts as chips */
    int cy = r_rem.top + 104, cx = 28;
    if (g_nsaved && !g_tab) {
        text(dc, g_fsmall, C_MUTED, 28, cy, L"Saved on this PC"); cy += 22;
        for (int i = 0; i < g_nsaved; i++) {
            wchar_t w[128]; MultiByteToWideChar(CP_UTF8, 0, g_saved[i], -1, w, 128);
            SIZE sz; SelectObject(dc, g_fsmall); GetTextExtentPoint32W(dc, w, (int)wcslen(w), &sz);
            int wdt = sz.cx + 22;
            if (cx + wdt > CW - 28) break;
            r_chip[i] = (RECT){cx, cy, cx + wdt, cy + 26};
            HBRUSH cb = CreateSolidBrush(C_FIELD); HRGN rg = CreateRoundRectRgn(cx, cy, cx + wdt, cy + 26, 10, 10); FillRgn(dc, rg, cb); DeleteObject(rg); DeleteObject(cb);
            text(dc, g_fsmall, C_TEXT, cx + 11, cy + 5, w);
            cx += wdt + 8;
        }
        for (int i = g_nsaved; i < 8; i++) r_chip[i] = (RECT){0};
    } else for (int i = 0; i < 8; i++) r_chip[i] = (RECT){0};
    text(dc, g_fsmall, C_ACCENT, r_import.left, r_import.top, L"Import official backup");
    text(dc, g_fsmall, C_MUTED, r_forgot.left + 12, r_forgot.top, L"Forgot password");
    DeleteObject(acc);
    EndPaint(h, &ps);
}

static int in(RECT r, int x, int y) { return x >= r.left && x < r.right && y >= r.top && y < r.bottom; }

static void submit(void) {
    wchar_t wn[64], wp[128], wp2[128];
    GetWindowTextW(g_ename, wn, 64); GetWindowTextW(g_epw, wp, 128); GetWindowTextW(g_epw2, wp2, 128);
    g_err[0] = 0;
    if (!wn[0]) { wcscpy(g_err, L"Enter your account name."); InvalidateRect(g_win, NULL, TRUE); return; }
    if (!wp[0]) { wcscpy(g_err, L"Enter your password."); InvalidateRect(g_win, NULL, TRUE); return; }
    if (g_tab && wcscmp(wp, wp2) != 0) { wcscpy(g_err, L"The two passwords don't match."); InvalidateRect(g_win, NULL, TRUE); return; }
    char n8[192], p8[384], body[600], out[600];
    WideCharToMultiByte(CP_UTF8, 0, wn, -1, n8, sizeof n8, NULL, NULL);
    WideCharToMultiByte(CP_UTF8, 0, wp, -1, p8, sizeof p8, NULL, NULL);
    int bl = snprintf(body, sizeof body, "%s\n%s", n8, p8);
    SetCursor(LoadCursor(NULL, IDC_WAIT));
    int ok = http_post(g_tab ? "/rozefield/register" : "/rozefield/login", body, bl, out, sizeof out, 8000);
    SetCursor(LoadCursor(NULL, IDC_ARROW));
    if (!ok) { wcscpy(g_err, L"The Rozefield server didn't answer. Is it running?"); InvalidateRect(g_win, NULL, TRUE); return; }
    if (strncmp(out, "OK|", 3) == 0) {
        char *uid = out + 3, *nm = strchr(uid, '|'), *key = NULL;
        if (nm) { *nm++ = 0; key = strchr(nm, '|'); if (key) *key++ = 0; }
        snprintf(g_uid, sizeof g_uid, "%s", uid); snprintf(g_name, sizeof g_name, "%s", nm ? nm : n8); snprintf(g_key, sizeof g_key, "%s", key ? key : "");
        if (g_remember) remember_name(g_name);
        g_done = 1; DestroyWindow(g_win); return;
    }
    MultiByteToWideChar(CP_UTF8, 0, strncmp(out, "ERR|", 4) == 0 ? out + 4 : out, -1, g_err, 256);
    InvalidateRect(g_win, NULL, TRUE);
}

static void do_import(void) {
    wchar_t fn[MAX_PATH] = L"";
    OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win;
    of.lpstrFilter = L"Rozefield backup (*.rzsave)\0*.rzsave\0All files\0*.*\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH;
    of.Flags = OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR; of.lpstrTitle = L"Choose your backup (.rzsave)";
    if (!GetOpenFileNameW(&of)) return;
    HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) { wcscpy(g_err, L"Couldn't open that file."); InvalidateRect(g_win, NULL, TRUE); return; }
    DWORD size = GetFileSize(f, NULL), got = 0;
    char *data = (char *)malloc(size ? size : 1);
    ReadFile(f, data, size, &got, NULL); CloseHandle(f);
    char out[600];
    SetCursor(LoadCursor(NULL, IDC_WAIT));
    int ok = http_post("/rozefield/import", data, (int)got, out, sizeof out, 120000);
    SetCursor(LoadCursor(NULL, IDC_ARROW));
    free(data);
    if (!ok) { wcscpy(g_err, L"The Rozefield server didn't answer. Is it running?"); InvalidateRect(g_win, NULL, TRUE); return; }
    if (strncmp(out, "OK|", 3) == 0) {
        char *uid = out + 3, *nm = strchr(uid, '|'); if (nm) *nm++ = 0; else nm = uid;
        wchar_t w[128]; MultiByteToWideChar(CP_UTF8, 0, nm, -1, w, 128);
        g_tab = 0; layout();
        SetWindowTextW(g_ename, w); SetWindowTextW(g_epw, L""); SetFocus(g_epw);
        swprintf(g_err, 256, L"Imported \"%ls\". Choose a password and press Enter game.", w);
    } else {
        wchar_t w[256]; MultiByteToWideChar(CP_UTF8, 0, strncmp(out, "ERR|", 4) == 0 ? out + 4 : out, -1, w, 256);
        swprintf(g_err, 256, L"Import failed: %ls", w);
    }
    InvalidateRect(g_win, NULL, TRUE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: paint(h); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLOREDIT: SetTextColor((HDC)w, C_TEXT); SetBkColor((HDC)w, C_FIELD); return (LRESULT)g_brfield;
    case WM_NCHITTEST: {   /* drag the card by its empty areas */
        LRESULT r = DefWindowProcW(h, m, w, l);
        if (r == HTCLIENT) {
            POINT pt = {(short)LOWORD(l), (short)HIWORD(l)}; ScreenToClient(h, &pt);
            if (pt.y < 60 && !in(r_close, pt.x, pt.y)) return HTCAPTION;
        }
        return r; }
    case WM_LBUTTONDOWN: {
        int x = (short)LOWORD(l), y = (short)HIWORD(l);
        if (in(r_close, x, y)) { g_done = -1; DestroyWindow(h); return 0; }
        if (in(r_tab0, x, y) && g_tab) { g_tab = 0; g_err[0] = 0; layout(); return 0; }
        if (in(r_tab1, x, y) && !g_tab) { g_tab = 1; g_err[0] = 0; layout(); return 0; }
        if (in(r_rem, x, y)) { g_remember = !g_remember; InvalidateRect(h, NULL, TRUE); return 0; }
        if (in(r_import, x, y)) { do_import(); return 0; }
        if (in(r_forgot, x, y)) { wcscpy(g_err, L"Ask the server owner to reset it (tools\\reset_password.py)."); InvalidateRect(h, NULL, TRUE); return 0; }
        for (int i = 0; i < 8; i++) if (r_chip[i].right && in(r_chip[i], x, y)) {
            wchar_t wn[128]; MultiByteToWideChar(CP_UTF8, 0, g_saved[i], -1, wn, 128);
            SetWindowTextW(g_ename, wn); SetFocus(g_epw); return 0; }
        return 0; }
    case WM_SETCURSOR: {
        POINT pt; GetCursorPos(&pt); ScreenToClient(h, &pt);
        int hot = in(r_close, pt.x, pt.y) || in(r_tab0, pt.x, pt.y) || in(r_tab1, pt.x, pt.y) || in(r_rem, pt.x, pt.y) || in(r_import, pt.x, pt.y) || in(r_forgot, pt.x, pt.y);
        for (int i = 0; i < 8; i++) if (r_chip[i].right && in(r_chip[i], pt.x, pt.y)) hot = 1;
        if (hot && LOWORD(l) == HTCLIENT) { SetCursor(LoadCursor(NULL, IDC_HAND)); return TRUE; }
        break; }
    case WM_DRAWITEM: {
        DRAWITEMSTRUCT *d = (DRAWITEMSTRUCT *)l;
        HBRUSH b = CreateSolidBrush((d->itemState & ODS_SELECTED) ? RGB(210, 90, 128) : C_ACCENT);
        FillRect(d->hDC, &d->rcItem, g_brcard);
        HRGN rg = CreateRoundRectRgn(d->rcItem.left, d->rcItem.top, d->rcItem.right + 1, d->rcItem.bottom + 1, 12, 12);
        FillRgn(d->hDC, rg, b); DeleteObject(rg); DeleteObject(b);
        wchar_t t[64]; GetWindowTextW(d->hwndItem, t, 64);
        SelectObject(d->hDC, g_fbtn); SetTextColor(d->hDC, RGB(255, 255, 255)); SetBkMode(d->hDC, TRANSPARENT);
        DrawTextW(d->hDC, t, -1, &d->rcItem, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        return TRUE; }
    case WM_COMMAND: if (LOWORD(w) == 1) { submit(); return 0; } break;
    case WM_CLOSE: g_done = -1; DestroyWindow(h); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

static HWND g_found;
static BOOL CALLBACK find_win(HWND h, LPARAM pid) {
    DWORD p = 0; GetWindowThreadProcessId(h, &p);
    RECT r;
    if (p == (DWORD)pid && IsWindowVisible(h) && GetWindowRect(h, &r) && r.right - r.left > 400) { g_found = h; return FALSE; }
    return TRUE;
}

static DWORD parent_pid(void);
static int pick_account(const char *host, const char *last) {
    snprintf(g_host, sizeof g_host, "%s", host);
    load_saved();
    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"RozefieldLogin"; wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);
    g_brcard = CreateSolidBrush(C_CARD); g_brfield = CreateSolidBrush(C_FIELD);
    g_ftitle = CreateFontW(-26, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_fbody = CreateFontW(-17, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_fsmall = CreateFontW(-14, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_fbtn = CreateFontW(-17, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    /* centre over the game window (the intro screen), or the screen */
    RECT gr = {0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    g_found = NULL; EnumWindows(find_win, (LPARAM)parent_pid());
    if (g_found) GetWindowRect(g_found, &gr);
    int x = (gr.left + gr.right - CW) / 2, y = (gr.top + gr.bottom - CH) / 2;
    g_win = CreateWindowExW(WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TOOLWINDOW, L"RozefieldLogin", L"Rozefield", WS_POPUP | WS_VISIBLE,
                            x, y, CW, CH, NULL, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(g_win, 0, 232, LWA_ALPHA);   /* see-through, the intro art shows behind */
    SetWindowRgn(g_win, CreateRoundRectRgn(0, 0, CW + 1, CH + 1, 22, 22), TRUE);
    g_ename = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 0, 0, 10, 10, g_win, NULL, NULL, NULL);
    g_epw = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL | ES_PASSWORD, 0, 0, 10, 10, g_win, NULL, NULL, NULL);
    g_epw2 = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_TABSTOP | ES_AUTOHSCROLL | ES_PASSWORD, 0, 0, 10, 10, g_win, NULL, NULL, NULL);
    g_btn = CreateWindowW(L"BUTTON", L"Enter game", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW, 0, 0, 10, 10, g_win, (HMENU)1, NULL, NULL);
    HWND ed[] = {g_ename, g_epw, g_epw2};
    for (int i = 0; i < 3; i++) { SendMessageW(ed[i], WM_SETFONT, (WPARAM)g_fbody, TRUE); SendMessageW(ed[i], EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(8, 8)); }
    SendMessageW(g_ename, EM_LIMITTEXT, 24, 0);
    layout();
    char lastname[128]; GetPrivateProfileStringA("account", "last_name", "", lastname, sizeof lastname, g_ini);
    if (lastname[0]) { wchar_t w[128]; MultiByteToWideChar(CP_UTF8, 0, lastname, -1, w, 128); SetWindowTextW(g_ename, w); }
    else if (g_nsaved) { wchar_t w[128]; MultiByteToWideChar(CP_UTF8, 0, g_saved[0], -1, w, 128); SetWindowTextW(g_ename, w); }
    (void)last;
    SetForegroundWindow(g_win); SetFocus(GetWindowTextLengthW(g_ename) ? g_epw : g_ename);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN) { submit(); continue; }
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_ESCAPE) { g_done = -1; DestroyWindow(g_win); continue; }
        if (!IsDialogMessageW(g_win, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    }
    if (g_done == 1) WritePrivateProfileStringA("account", "last_name", g_name, g_ini);
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
        snprintf(g_ini, sizeof g_ini, "%s", path);
        /* Rozefield.exe already logged in: it leaves the account here for 10 minutes, used once */
        char hu[64] = "", hn[128] = "", hk[64] = "", he[32] = "";
        GetPrivateProfileStringA("handoff", "uid", "", hu, sizeof hu, path);
        GetPrivateProfileStringA("handoff", "name", "", hn, sizeof hn, path);
        GetPrivateProfileStringA("handoff", "key", "", hk, sizeof hk, path);
        GetPrivateProfileStringA("handoff", "expires", "0", he, sizeof he, path);
        int handed = hu[0] && hk[0] && (long long)time(NULL) < _atoi64(he);
        WritePrivateProfileStringA("handoff", NULL, NULL, path);
        if (handed) {
            snprintf(g_uid, sizeof g_uid, "%s", hu); snprintf(g_name, sizeof g_name, "%s", hn); snprintf(g_key, sizeof g_key, "%s", hk);
            logf_("logged in by Rozefield.exe as %s", hu);
        } else if (!pick_account(host, last)) {
            send_msg("{\"action\":\"init\",\"params\":{}}");
            send_msg("{\"action\":\"loginCancel\",\"params\":{}}");
            return 0;
        }
        WritePrivateProfileStringA("account", "last_uid", g_uid, path);
        /* the account key is the uid; the display name travels in the token as @byte@byte@ */
        for (unsigned char *c = (unsigned char *)g_name; *c && strlen(tok) < sizeof tok - 6; c++) {
            char b[8]; snprintf(b, sizeof b, "%u@", *c); strcat(tok, b);
        }
        if (g_key[0] && strlen(tok) + strlen(g_key) + 4 < sizeof tok) { strcat(tok, "0@"); strcat(tok, g_key); strcat(tok, "@"); }
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
