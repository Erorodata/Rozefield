/* Rozefield Server.exe - the server's control panel. Starts rozefield_server.py in the background (no console window)
 * and talks to it through its owner API (/admin/..., this PC only, token in save\admin_token.txt):
 * players online/offline, reset / clear password, rename, GM commands, mail, chat log, kick, ban, mute,
 * reclaim an old official id, import a backup, and the live log with filters.
 * If the server is already running (start_server.bat) the panel attaches to it.
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 rozefield_panel.c panel.rc -o "Rozefield Server.exe"
 *        -lws2_32 -lcomdlg32 -lshell32 -luser32 -lgdi32 -lmsimg32 -Wl,--subsystem,windows
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <commdlg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <ctype.h>
#include <stdarg.h>

#define WW 1180
#define WH 720
#define C_INK RGB(17, 18, 27)
#define C_PANEL RGB(12, 13, 20)
#define C_ACC RGB(242, 127, 163)
#define C_OK RGB(95, 212, 135)
#define C_BAD RGB(240, 108, 108)
#define C_TXT RGB(244, 245, 250)
#define C_MUTE RGB(176, 180, 196)
#define C_WARN RGB(255, 208, 138)
#define C_FIELD RGB(30, 32, 44)
#define WM_DATA (WM_APP + 1)
#ifndef EM_SETCUEBANNER
#define EM_SETCUEBANNER 0x1501
#endif

static HWND g_win, g_list, g_logv, g_find, g_search;
static HFONT f_title, f_h, f_body, f_small, f_btn, f_mono;
static HBRUSH br_panel, br_field;
static char g_dir[MAX_PATH], g_token[64];
static int g_port = 18881;
static HANDLE g_proc;                 /* the server we started (NULL if attached to one started elsewhere) */
static volatile int g_up, g_starting;
static int g_hover, g_filter, g_sel = -1;
static long g_lognext;

/* ---------------------------------------------------------------- players */
struct pl { int pid; char uid[64]; wchar_t name[64]; int level, online, banned, muted, pw, official, label; };
static struct pl g_pl[2000], g_pl_new[2000]; static int g_npl, g_npl_new;
static CRITICAL_SECTION g_cs;

/* ---------------------------------------------------------------- log */
#define LOGMAX 3000
static wchar_t *g_lines[LOGMAX]; static int g_nlines, g_lines_dirty;

static void add_line(const char *s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, NULL, 0);
    wchar_t *w = (wchar_t *)malloc(n * sizeof(wchar_t)); MultiByteToWideChar(CP_UTF8, 0, s, -1, w, n);
    EnterCriticalSection(&g_cs);
    if (g_nlines == LOGMAX) { free(g_lines[0]); memmove(g_lines, g_lines + 1, (LOGMAX - 1) * sizeof *g_lines); g_nlines--; }
    g_lines[g_nlines++] = w; g_lines_dirty = 1;
    LeaveCriticalSection(&g_cs);
}
static void note(const wchar_t *fmt, ...) {
    wchar_t b[600]; va_list ap; va_start(ap, fmt); vswprintf(b, 600, fmt, ap); va_end(ap);
    char u[1800]; SYSTEMTIME t; GetLocalTime(&t);
    char m[1700]; WideCharToMultiByte(CP_UTF8, 0, b, -1, m, sizeof m, NULL, NULL);
    snprintf(u, sizeof u, "%02d:%02d:%02d [panel] %s", t.wHour, t.wMinute, t.wSecond, m);
    add_line(u);
}

/* ---------------------------------------------------------------- HTTP to the server */
static int http(const char *method, const char *path, const char *body, int blen, char **out) {
    *out = NULL;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)g_port); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    DWORD to = 15000; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    if (connect(s, (struct sockaddr *)&a, sizeof a) != 0) { closesocket(s); return 0; }
    char hdr[400];
    int hl = snprintf(hdr, sizeof hdr, "%s %s HTTP/1.0\r\nHost: rozefield\r\nX-Admin-Token: %s\r\nContent-Length: %d\r\n\r\n", method, path, g_token, blen);
    send(s, hdr, hl, 0);
    for (int off = 0; off < blen;) { int n = send(s, body + off, blen - off, 0); if (n <= 0) break; off += n; }
    int cap = 65536, len = 0, r; char *b = (char *)malloc(cap + 1);
    while ((r = recv(s, b + len, cap - len, 0)) > 0) { len += r; if (len == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
    b[len] = 0; closesocket(s);
    int code = 0; sscanf(b, "HTTP/%*s %d", &code);
    char *p = strstr(b, "\r\n\r\n");
    if (!p || code != 200) { free(b); return 0; }
    memmove(b, p + 4, len - (p + 4 - b) + 1);
    *out = b; return 1;
}

static void read_token(void) {
    char p[MAX_PATH]; snprintf(p, sizeof p, "%ssave\\admin_token.txt", g_dir);
    FILE *f = fopen(p, "rb"); g_token[0] = 0;
    if (f) { size_t n = fread(g_token, 1, sizeof g_token - 1, f); g_token[n] = 0; fclose(f); }
    for (char *c = g_token; *c; c++) if (*c == '\r' || *c == '\n') { *c = 0; break; }
}

/* send an action; returns malloc'd UTF-16 result text (after OK| / ERR|), *ok set */
static wchar_t *act(const char *body, int *ok) {
    char *out; *ok = 0;
    if (!http("POST", "/admin/do", body, (int)strlen(body), &out)) {
        wchar_t *w = _wcsdup(L"The server didn't answer. Is it running?"); return w;
    }
    *ok = strncmp(out, "OK|", 3) == 0;
    char *t = strchr(out, '|'); t = t ? t + 1 : out;
    int n = MultiByteToWideChar(CP_UTF8, 0, t, -1, NULL, 0);
    wchar_t *w = (wchar_t *)malloc(n * sizeof(wchar_t)); MultiByteToWideChar(CP_UTF8, 0, t, -1, w, n);
    free(out); return w;
}

/* escape a field value for the key=value body */
static void put_kv(char *b, size_t bs, const char *k, const wchar_t *v) {
    char u[4096]; WideCharToMultiByte(CP_UTF8, 0, v, -1, u, sizeof u, NULL, NULL);
    size_t l = strlen(b); l += snprintf(b + l, bs - l, "\n%s=", k);
    for (char *c = u; *c && l < bs - 3; c++) {
        if (*c == '\r') continue;
        if (*c == '\n') { b[l++] = '\\'; b[l++] = 'n'; } else b[l++] = *c;
    }
    b[l] = 0;
}

/* ---------------------------------------------------------------- server process */
static DWORD WINAPI poller(LPVOID a) {
    for (int tick = 0;; tick++) {
        char *out;
        if (g_token[0] == 0 || tick % 10 == 0) read_token();
        int up = g_token[0] && http("GET", "/admin/players", "", 0, &out);
        if (up) {
            g_npl_new = 0;
            char *save = NULL;
            for (char *line = strtok_s(out, "\n", &save); line && g_npl_new < 2000; line = strtok_s(NULL, "\n", &save)) {
                struct pl *p = &g_pl_new[g_npl_new]; char nm[200] = "";
                char *f[10] = {0}; int k = 0; char *q = line;
                while (k < 10) { f[k++] = q; char *bar = strchr(q, '|'); if (!bar) break; *bar = 0; q = bar + 1; }
                if (k < 10) continue;
                p->pid = atoi(f[0]); snprintf(p->uid, sizeof p->uid, "%s", f[1]); snprintf(nm, sizeof nm, "%s", f[2]);
                MultiByteToWideChar(CP_UTF8, 0, nm, -1, p->name, 64);
                p->level = atoi(f[3]); p->online = atoi(f[4]); p->banned = atoi(f[5]); p->muted = atoi(f[6]); p->pw = atoi(f[7]);
                p->official = atoi(f[8]); p->label = atoi(f[9]);
                g_npl_new++;
            }
            free(out);
            char path[64]; snprintf(path, sizeof path, "/admin/log?since=%ld", g_lognext);
            if (http("GET", path, "", 0, &out)) {
                char *nl = strchr(out, '\n');
                long next = atol(out);
                if (nl && next > g_lognext) {
                    char *save2 = NULL;
                    for (char *l = strtok_s(nl + 1, "\n", &save2); l; l = strtok_s(NULL, "\n", &save2)) add_line(l);
                }
                g_lognext = next;
                free(out);
            }
            PostMessageW(g_win, WM_DATA, 1, 0);
        } else PostMessageW(g_win, WM_DATA, 0, 0);
        g_up = up;
        if (g_proc && WaitForSingleObject(g_proc, 0) == WAIT_OBJECT_0) {
            DWORD code = 0; GetExitCodeProcess(g_proc, &code); CloseHandle(g_proc); g_proc = NULL;
            note(L"The server stopped (exit code %lu).%ls", code, code ? L" Run start_server.bat once to see the error." : L"");
        }
        Sleep(up ? 700 : 1200);
    }
    return 0;
}

static int run_ok(const wchar_t *cmd) {   /* runs a command hidden, returns its exit code == 0 */
    STARTUPINFOW si = {sizeof si}; PROCESS_INFORMATION pi; wchar_t c[1024]; wcsncpy(c, cmd, 1023); c[1023] = 0;
    wchar_t wd[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_dir, -1, wd, MAX_PATH);
    if (!CreateProcessW(NULL, c, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, wd, &si, &pi)) return 0;
    WaitForSingleObject(pi.hProcess, 120000); DWORD code = 1; GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread); return code == 0;
}

static DWORD WINAPI start_thread(LPVOID a) {
    if (g_up) { note(L"The server is already running."); g_starting = 0; return 0; }
    note(L"Starting the server...");
    /* same choice of Python as start_server.bat: an installed 3.13 / 3.12, else py -3, else python */
    static const wchar_t *pys[] = {L"py -3.13", L"py -3.12", L"py -3", L"python"};
    const wchar_t *py = NULL;
    for (int i = 0; i < 4 && !py; i++) { wchar_t c[64]; swprintf(c, 64, L"%ls -c \"1\"", pys[i]); if (run_ok(c)) py = pys[i]; }
    if (!py) { note(L"Python 3 was not found. Install it from python.org (tick \"Add python to PATH\")."); g_starting = 0; return 0; }
    wchar_t c[256]; swprintf(c, 256, L"%ls -c \"import google.protobuf, cramjam\"", py);
    if (!run_ok(c)) { note(L"Installing what the server needs (first start)..."); swprintf(c, 256, L"%ls -m pip install -r requirements.txt", py); run_ok(c); }
    char game[MAX_PATH] = "H:\\Backup\\OverField", gp[MAX_PATH]; snprintf(gp, sizeof gp, "%sgame_path.txt", g_dir);
    FILE *f = fopen(gp, "rb"); if (f) { if (fgets(game, sizeof game, f)) { char *e = game + strlen(game); while (e > game && (e[-1] == '\r' || e[-1] == '\n' || e[-1] == ' ')) *--e = 0; } fclose(f); }
    wchar_t wgame[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, game, -1, wgame, MAX_PATH);
    wchar_t cmd[1024]; swprintf(cmd, 1024, L"%ls rozefield_server.py --res-dir \"%ls\\launcher_Data\\yoo\"", py, wgame);
    STARTUPINFOW si = {sizeof si}; si.dwFlags = STARTF_USESTDHANDLES;
    SECURITY_ATTRIBUTES sa = {sizeof sa, NULL, TRUE};
    HANDLE nul = CreateFileW(L"NUL", GENERIC_WRITE | GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
    si.hStdInput = nul; si.hStdOutput = nul; si.hStdError = nul;
    PROCESS_INFORMATION pi; wchar_t wd[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_dir, -1, wd, MAX_PATH);
    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, wd, &si, &pi)) { note(L"Could not start Python."); CloseHandle(nul); g_starting = 0; return 0; }
    CloseHandle(nul); CloseHandle(pi.hThread); g_proc = pi.hProcess; g_lognext = 0;
    for (int i = 0; i < 60 && !g_up && g_proc; i++) Sleep(500);
    note(g_up ? L"Server is up." : L"The server is taking long to start - check server.log.");
    g_starting = 0;
    return 0;
}
static void start_server(void) { if (!g_starting) { g_starting = 1; CloseHandle(CreateThread(NULL, 0, start_thread, NULL, 0, NULL)); } }
static void stop_server(void) {
    int ok; wchar_t *r = act("stop", &ok); free(r);
    if (g_proc) { if (WaitForSingleObject(g_proc, 4000) != WAIT_OBJECT_0) TerminateProcess(g_proc, 0); }
    note(L"Server stopped.");
}
static DWORD WINAPI restart_thread(LPVOID a) { stop_server(); for (int i = 0; i < 20 && g_up; i++) Sleep(300); Sleep(800); start_server(); return 0; }

/* ---------------------------------------------------------------- dialogs */
static wchar_t g_dlg_out[4][1024]; static int g_dlg_done, g_dlg_n;
static HWND g_dlg_edits[4], g_dlg_combo;

static LRESULT CALLBACK DlgProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CTLCOLOREDIT: case WM_CTLCOLORLISTBOX: SetTextColor((HDC)w, C_TXT); SetBkColor((HDC)w, C_FIELD); return (LRESULT)br_field;
    case WM_CTLCOLORSTATIC: SetTextColor((HDC)w, C_MUTE); SetBkColor((HDC)w, C_PANEL); return (LRESULT)br_panel;
    case WM_ERASEBKGND: { RECT r; GetClientRect(h, &r); FillRect((HDC)w, &r, br_panel); return 1; }
    case WM_COMMAND:
        if (LOWORD(w) == IDOK) { for (int i = 0; i < g_dlg_n; i++) GetWindowTextW(g_dlg_edits[i], g_dlg_out[i], 1024); g_dlg_done = 1; DestroyWindow(h); return 0; }
        if (LOWORD(w) == IDCANCEL) { g_dlg_done = -1; DestroyWindow(h); return 0; }
        break;
    case WM_CLOSE: g_dlg_done = -1; DestroyWindow(h); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

/* fields: label, initial text; flags bit0 = password, bit1 = multiline (last field only). Returns 1 on OK. */
static int ask(const wchar_t *title, const wchar_t *intro, int n, const wchar_t **labels, const wchar_t **init, int flags) {
    int W = 460, rowh = 58, H = 120 + n * rowh + ((flags & 2) ? 90 : 0) + (intro ? 44 : 0);
    RECT pr; GetWindowRect(g_win, &pr);
    HWND d = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, L"RzDlg", title, WS_POPUP | WS_CAPTION | WS_SYSMENU,
                             (pr.left + pr.right - W) / 2, (pr.top + pr.bottom - H) / 2, W, H, g_win, NULL, GetModuleHandleW(NULL), NULL);
    int y = 16;
    if (intro) { HWND s = CreateWindowW(L"STATIC", intro, WS_CHILD | WS_VISIBLE, 18, y, W - 40, 40, d, NULL, NULL, NULL); SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE); y += 44; }
    g_dlg_n = n;
    for (int i = 0; i < n; i++) {
        HWND s = CreateWindowW(L"STATIC", labels[i], WS_CHILD | WS_VISIBLE, 18, y, W - 40, 18, d, NULL, NULL, NULL);
        SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE);
        int multi = (flags & 2) && i == n - 1;
        DWORD st = WS_CHILD | WS_VISIBLE | WS_TABSTOP | (multi ? (ES_MULTILINE | ES_WANTRETURN | WS_VSCROLL) : ES_AUTOHSCROLL) | ((flags & 1) ? ES_PASSWORD : 0);
        g_dlg_edits[i] = CreateWindowExW(0, L"EDIT", init && init[i] ? init[i] : L"", st, 18, y + 20, W - 40, multi ? 110 : 28, d, NULL, NULL, NULL);
        SendMessageW(g_dlg_edits[i], WM_SETFONT, (WPARAM)f_body, TRUE);
        SendMessageW(g_dlg_edits[i], EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6));
        y += rowh + (multi ? 90 : 0);
    }
    HWND ok = CreateWindowW(L"BUTTON", L"OK", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON, W - 220, y + 4, 92, 32, d, (HMENU)IDOK, NULL, NULL);
    HWND ca = CreateWindowW(L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP, W - 120, y + 4, 92, 32, d, (HMENU)IDCANCEL, NULL, NULL);
    SendMessageW(ok, WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(ca, WM_SETFONT, (WPARAM)f_body, TRUE);
    ShowWindow(d, SW_SHOW); EnableWindow(g_win, FALSE); if (n) SetFocus(g_dlg_edits[0]);
    g_dlg_done = 0; MSG msg;
    while (!g_dlg_done && GetMessageW(&msg, NULL, 0, 0) > 0) { if (!IsDialogMessageW(d, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); } }
    EnableWindow(g_win, TRUE); SetForegroundWindow(g_win);
    return g_dlg_done == 1;
}

static void show_text(const wchar_t *title, const wchar_t *text) {   /* long results (chat log) */
    const wchar_t *lab[] = {L""}; const wchar_t *init[] = {text};
    ask(title, NULL, 1, lab, init, 2);
}

/* ---------------------------------------------------------------- actions */
enum { B_NONE, B_CLOSE, B_MIN, B_START, B_STOP, B_RESTART, B_SAVEDIR, B_LOGFILE, B_IMPORT, B_MAILALL,
       A_FIRST, A_RESETPW = A_FIRST, A_CLEARPW, A_RENAME, A_GM, A_MAIL, A_CHAT, A_KICK, A_BAN, A_MUTE, A_RECLAIM, A_LAST,
       F_FIRST = 50 };
static const wchar_t *ACT_LABEL[] = {L"Reset password", L"Clear password", L"Rename", L"GM commands", L"Send mail", L"Chat log",
                                     L"Kick", L"Ban", L"Mute", L"Reclaim old ID"};
static const wchar_t *FILTERS[] = {L"All", L"Logins", L"Errors", L"Chat", L"Admin", L"HTTP"};
#define NFILT 6
static RECT r_close = {WW - 52, 10, WW - 12, 46}, r_min = {WW - 96, 10, WW - 56, 46};
static RECT r_start = {WW - 470, WH - 70, WW - 340, WH - 26}, r_stop = {WW - 330, WH - 70, WW - 200, WH - 26}, r_restart = {WW - 190, WH - 70, WW - 36, WH - 26};
static RECT r_savedir = {14, WH - 128, 58, WH - 84}, r_logfile = {14, WH - 74, 58, WH - 30};
static RECT r_import = {96, WH - 70, 262, WH - 26}, r_mailall = {272, WH - 70, 430, WH - 26};
static RECT r_act[10], r_filt[NFILT];

static struct pl *sel(void) { return (g_sel >= 0 && g_sel < g_npl) ? &g_pl[g_sel] : NULL; }

static void result(const wchar_t *what, wchar_t *r, int ok) {
    if (wcslen(r) > 160 || wcschr(r, L'\n')) show_text(what, r);
    else MessageBoxW(g_win, r, what, MB_OK | (ok ? MB_ICONINFORMATION : MB_ICONWARNING));
    free(r);
}

static void do_action(int a) {
    struct pl *p = sel(); char b[8192]; int ok; wchar_t *r;
    if (a >= A_FIRST && a < A_LAST && !p) { MessageBoxW(g_win, L"Choose a player in the list first.", L"Rozefield Server", MB_OK); return; }
    wchar_t who[120]; if (p) swprintf(who, 120, L"%ls (UID %d)", p->name, p->label);
    switch (a) {
    case A_RESETPW: {
        const wchar_t *lab[] = {L"New password (4+ characters)"};
        if (!ask(L"Reset password", who, 1, lab, NULL, 0)) return;
        snprintf(b, sizeof b, "resetpw\npid=%d", p->pid); put_kv(b, sizeof b, "password", g_dlg_out[0]);
        r = act(b, &ok); result(L"Reset password", r, ok); break; }
    case A_CLEARPW:
        if (MessageBoxW(g_win, L"Remove this player's password? The next password they log in with becomes their new one.", who, MB_YESNO | MB_ICONQUESTION) != IDYES) return;
        snprintf(b, sizeof b, "clearpw\npid=%d", p->pid); r = act(b, &ok); result(L"Clear password", r, ok); break;
    case A_RENAME: {
        const wchar_t *lab[] = {L"New name (1-24 characters)"}; const wchar_t *init[] = {p->name};
        if (!ask(L"Rename", who, 1, lab, init, 0)) return;
        snprintf(b, sizeof b, "rename\npid=%d", p->pid); put_kv(b, sizeof b, "name", g_dlg_out[0]);
        r = act(b, &ok); result(L"Rename", r, ok); break; }
    case A_GM: {
        const wchar_t *lab[] = {L"Command  (examples: /all outfits   /all furniture 99   /all everything   /currency 100000   /level 50   /give 102 1000   /char 101001)"};
        const wchar_t *init[] = {L"/all outfits"};
        if (!p->online) { MessageBoxW(g_win, L"The player must be online for GM commands.", who, MB_OK); return; }
        if (!ask(L"GM commands", who, 1, lab, init, 0)) return;
        snprintf(b, sizeof b, "gm\npid=%d", p->pid); put_kv(b, sizeof b, "cmd", g_dlg_out[0]);
        r = act(b, &ok); result(L"GM commands", r, ok); break; }
    case A_MAIL: case B_MAILALL: {
        const wchar_t *lab[] = {L"Title", L"Items (optional: itemId:count, itemId:count)", L"Message"};
        const wchar_t *init[] = {L"", L"", L""};
        if (!ask(a == B_MAILALL ? L"Mail everyone" : L"Send mail", a == B_MAILALL ? L"Every account on this server gets this mail." : who, 3, lab, init, 2)) return;
        if (a == B_MAILALL) snprintf(b, sizeof b, "mail\nto=all"); else snprintf(b, sizeof b, "mail\npid=%d", p->pid);
        put_kv(b, sizeof b, "title", g_dlg_out[0]); put_kv(b, sizeof b, "items", g_dlg_out[1]); put_kv(b, sizeof b, "content", g_dlg_out[2]);
        r = act(b, &ok); result(L"Mail", r, ok); break; }
    case A_CHAT:
        snprintf(b, sizeof b, "chatlog\npid=%d", p->pid); r = act(b, &ok); show_text(L"Chat log", r); free(r); break;
    case A_KICK:
        if (MessageBoxW(g_win, L"Disconnect this player now?", who, MB_YESNO | MB_ICONQUESTION) != IDYES) return;
        snprintf(b, sizeof b, "kick\npid=%d", p->pid); r = act(b, &ok); result(L"Kick", r, ok); break;
    case A_BAN:
        if (!p->banned && MessageBoxW(g_win, L"Ban this player? They are disconnected and can't log in until unbanned.", who, MB_YESNO | MB_ICONWARNING) != IDYES) return;
        snprintf(b, sizeof b, "%s\npid=%d", p->banned ? "unban" : "ban", p->pid); r = act(b, &ok); result(p->banned ? L"Unban" : L"Ban", r, ok); break;
    case A_MUTE:
        snprintf(b, sizeof b, "%s\npid=%d", p->muted ? "unmute" : "mute", p->pid); r = act(b, &ok); result(p->muted ? L"Unmute" : L"Mute", r, ok); break;
    case A_RECLAIM: {
        const wchar_t *lab[] = {L"Their official player id (from a friend's backup or an old screenshot)"};
        if (p->official) { MessageBoxW(g_win, L"This account came from an official backup already.", who, MB_OK); return; }
        if (!ask(L"Reclaim old ID", L"For a player who never backed up: their new account takes their old official id, so friends who imported see them again. Progress stays as it is now.", 1, lab, NULL, 0)) return;
        char idu[64]; WideCharToMultiByte(CP_UTF8, 0, g_dlg_out[0], -1, idu, sizeof idu, NULL, NULL);
        snprintf(b, sizeof b, "reclaim\npid=%d\nofficial=%s", p->pid, idu); r = act(b, &ok); result(L"Reclaim old ID", r, ok); break; }
    case B_IMPORT: {
        wchar_t fn[MAX_PATH] = L""; OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win;
        of.lpstrFilter = L"OverField backup (*.rzsave)\0*.rzsave\0All files\0*.*\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH; of.Flags = OFN_FILEMUSTEXIST;
        if (!GetOpenFileNameW(&of)) return;
        const wchar_t *lab[] = {L"Log-in name for this account"};
        if (!ask(L"Import backup", L"The player logs in with this name (and sets a password at first log-in).", 1, lab, NULL, 0)) return;
        /* the importer runs in the server: hand it the file */
        HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE) { MessageBoxW(g_win, L"Couldn't open that file.", L"Import", MB_OK); return; }
        DWORD sz = GetFileSize(f, NULL), got = 0; char *data = (char *)malloc(sz + 1); ReadFile(f, data, sz, &got, NULL); CloseHandle(f);
        char nm[200]; WideCharToMultiByte(CP_UTF8, 0, g_dlg_out[0], -1, nm, sizeof nm, NULL, NULL);
        char path[300]; snprintf(path, sizeof path, "/rozefield/import?name=");
        for (char *c = nm; *c; c++) { char t[4]; if (isalnum((unsigned char)*c)) { t[0] = *c; t[1] = 0; } else snprintf(t, 4, "%%%02X", (unsigned char)*c); strcat(path, t); }
        char *out; int okh = http("POST", path, data, (int)got, &out); free(data);
        wchar_t w[600]; if (okh) MultiByteToWideChar(CP_UTF8, 0, out, -1, w, 600); else wcscpy(w, L"The server didn't answer.");
        MessageBoxW(g_win, w, L"Import backup", MB_OK); free(out); break; }
    }
    InvalidateRect(g_win, NULL, FALSE);
}

/* ---------------------------------------------------------------- log view */
static int line_matches(const wchar_t *l) {
    wchar_t q[128]; GetWindowTextW(g_search, q, 128);
    if (q[0] && !wcsstr(l, q)) {   /* case-insensitive contains */
        wchar_t a[1200], b[128]; wcsncpy(a, l, 1199); a[1199] = 0; wcsncpy(b, q, 127); b[127] = 0; _wcslwr(a); _wcslwr(b);
        if (!wcsstr(a, b)) return 0;
    }
    switch (g_filter) {
    case 1: return wcsstr(l, L"login") || wcsstr(l, L"gate connection") || wcsstr(l, L"logged in") || wcsstr(l, L"imported");
    case 2: return wcsstr(l, L"WARNING") || wcsstr(l, L"ERROR") || wcsstr(l, L"Traceback") || wcsstr(l, L"failed") || wcsstr(l, L"refused") || wcsstr(l, L"rror");
    case 3: return wcsstr(l, L"[chat]") != NULL;
    case 4: return wcsstr(l, L"[admin]") || wcsstr(l, L"[panel]");
    case 5: return wcsstr(l, L"HTTP ") != NULL;
    }
    return 1;
}
static void rebuild_log(void) {
    EnterCriticalSection(&g_cs);
    size_t cap = 1 << 16, len = 0; wchar_t *t = (wchar_t *)malloc(cap * sizeof(wchar_t)); t[0] = 0;
    int from = g_nlines > 1500 ? g_nlines - 1500 : 0;
    for (int i = from; i < g_nlines; i++) {
        if (!line_matches(g_lines[i])) continue;
        size_t n = wcslen(g_lines[i]);
        if (len + n + 3 >= cap) { cap = (len + n + 3) * 2; t = (wchar_t *)realloc(t, cap * sizeof(wchar_t)); }
        memcpy(t + len, g_lines[i], n * sizeof(wchar_t)); len += n; t[len++] = L'\r'; t[len++] = L'\n'; t[len] = 0;
    }
    g_lines_dirty = 0;
    LeaveCriticalSection(&g_cs);
    SendMessageW(g_logv, WM_SETREDRAW, FALSE, 0);
    SetWindowTextW(g_logv, t);
    SendMessageW(g_logv, EM_SETSEL, (WPARAM)len, (LPARAM)len); SendMessageW(g_logv, EM_SCROLLCARET, 0, 0);
    SendMessageW(g_logv, WM_SETREDRAW, TRUE, 0); InvalidateRect(g_logv, NULL, TRUE);
    free(t);
}

/* ---------------------------------------------------------------- painting */
static void fill(HDC dc, RECT r, COLORREF c, int rad) {
    HBRUSH b = CreateSolidBrush(c); HRGN g = rad ? CreateRoundRectRgn(r.left, r.top, r.right + 1, r.bottom + 1, rad, rad) : CreateRectRgn(r.left, r.top, r.right, r.bottom);
    FillRgn(dc, g, b); DeleteObject(g); DeleteObject(b);
}
static void outline(HDC dc, RECT r, COLORREF c, int rad) {
    HPEN p = CreatePen(PS_SOLID, 1, c); HGDIOBJ o = SelectObject(dc, p), ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    RoundRect(dc, r.left, r.top, r.right, r.bottom, rad, rad); SelectObject(dc, o); SelectObject(dc, ob); DeleteObject(p);
}
static void txt(HDC dc, HFONT f, COLORREF c, RECT r, const wchar_t *s, UINT fmt) {
    SelectObject(dc, f); SetTextColor(dc, c); SetBkMode(dc, TRANSPARENT); DrawTextW(dc, s, -1, &r, fmt | DT_NOPREFIX);
}
static void dot(HDC dc, int cx, int cy, int r, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c); HPEN p = CreatePen(PS_SOLID, 1, c); HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p);
    Ellipse(dc, cx - r, cy - r, cx + r + 1, cy + r + 1); SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(b); DeleteObject(p);
}
static void pill(HDC dc, RECT r, int kind, int hover, int enabled, const wchar_t *label) {   /* kind 1 = primary, 2 = danger */
    int rad = 14;
    if (kind == 1) fill(dc, r, !enabled ? RGB(110, 86, 98) : hover ? RGB(248, 150, 182) : C_ACC, rad);
    else { fill(dc, r, hover && enabled ? RGB(44, 47, 62) : RGB(30, 32, 44), rad); outline(dc, r, kind == 2 && enabled ? RGB(150, 70, 70) : RGB(70, 74, 92), rad); }
    txt(dc, kind == 1 ? f_btn : f_small, kind == 1 ? RGB(42, 10, 22) : !enabled ? RGB(110, 114, 130) : kind == 2 ? RGB(255, 160, 160) : C_TXT, r, label, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static void paint(HWND h) {
    PAINTSTRUCT ps; HDC wdc = BeginPaint(h, &ps);
    HDC dc = CreateCompatibleDC(wdc); HBITMAP bb = CreateCompatibleBitmap(wdc, WW, WH); HGDIOBJ ob = SelectObject(dc, bb);
    RECT all = {0, 0, WW, WH}; fill(dc, all, C_INK, 0);
    RECT rail = {0, 0, 72, WH}; fill(dc, rail, RGB(8, 9, 14), 0);
    dot(dc, 36, 40, 18, C_ACC); RECT rl = {18, 22, 54, 58}; txt(dc, f_h, RGB(42, 10, 22), rl, L"R", DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    if (g_hover == B_SAVEDIR) fill(dc, r_savedir, RGB(40, 42, 56), 10);
    if (g_hover == B_LOGFILE) fill(dc, r_logfile, RGB(40, 42, 56), 10);
    { HPEN p = CreatePen(PS_SOLID, 2, C_MUTE); HGDIOBJ o = SelectObject(dc, p), b0 = SelectObject(dc, GetStockObject(NULL_BRUSH));
      int x = r_savedir.left + 12, y = r_savedir.top + 13; RoundRect(dc, x, y + 3, x + 21, y + 18, 4, 4); MoveToEx(dc, x, y + 3, NULL); LineTo(dc, x, y); LineTo(dc, x + 8, y); LineTo(dc, x + 10, y + 3);
      int lx = r_logfile.left + 13, ly = r_logfile.top + 12; Rectangle(dc, lx, ly, lx + 18, ly + 21);
      for (int i = 0; i < 3; i++) { MoveToEx(dc, lx + 4, ly + 6 + i * 5, NULL); LineTo(dc, lx + 14, ly + 6 + i * 5); }
      SelectObject(dc, o); SelectObject(dc, b0); DeleteObject(p); }
    if (g_hover == B_CLOSE) fill(dc, r_close, RGB(200, 64, 76), 8);
    if (g_hover == B_MIN) fill(dc, r_min, RGB(44, 47, 62), 8);
    { HPEN p = CreatePen(PS_SOLID, 2, C_TXT); HGDIOBJ o = SelectObject(dc, p);
      int cx = (r_close.left + r_close.right) / 2, cy = (r_close.top + r_close.bottom) / 2;
      MoveToEx(dc, cx - 6, cy - 6, NULL); LineTo(dc, cx + 7, cy + 7); MoveToEx(dc, cx + 6, cy - 6, NULL); LineTo(dc, cx - 7, cy + 7);
      cx = (r_min.left + r_min.right) / 2; MoveToEx(dc, cx - 7, cy, NULL); LineTo(dc, cx + 8, cy); SelectObject(dc, o); DeleteObject(p); }

    RECT rt = {96, 22, 600, 64}; txt(dc, f_title, C_TXT, rt, L"Rozefield Server", DT_LEFT | DT_SINGLELINE);
    int online = 0; for (int i = 0; i < g_npl; i++) online += g_pl[i].online;
    wchar_t st[160];
    if (g_up) swprintf(st, 160, L"Running  \x00B7  %d online  \x00B7  %d accounts%ls", online, g_npl, g_proc ? L"" : L"  \x00B7  started outside this window");
    else wcscpy(st, g_starting ? L"Starting\x2026" : L"Stopped");
    dot(dc, 104, 79, 5, g_up ? C_OK : g_starting ? C_WARN : C_BAD);
    RECT rs = {116, 68, 900, 92}; txt(dc, f_small, g_up ? RGB(159, 227, 180) : C_MUTE, rs, st, DT_LEFT | DT_VCENTER | DT_SINGLELINE);

    /* players panel */
    RECT pp = {96, 106, 446, WH - 92}; fill(dc, pp, C_PANEL, 18);
    RECT ph = {116, 116, 430, 140}; txt(dc, f_h, C_TXT, ph, L"Players", DT_LEFT | DT_SINGLELINE);
    struct pl *p = sel();
    RECT sh = {116, 378, 430, 398};
    wchar_t sw[160]; if (p) swprintf(sw, 160, L"%ls  \x00B7  UID %d%ls", p->name, p->label, p->official ? L"  \x00B7  imported" : L""); else wcscpy(sw, L"Choose a player");
    txt(dc, f_small, p ? C_TXT : C_MUTE, sh, sw, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    for (int i = 0; i < 10; i++) {
        const wchar_t *lb = ACT_LABEL[i]; int kind = 0, en = p != NULL;
        if (i == A_BAN - A_FIRST) { lb = p && p->banned ? L"Unban" : L"Ban"; kind = 2; }
        if (i == A_MUTE - A_FIRST) lb = p && p->muted ? L"Unmute" : L"Mute";
        if (i == A_KICK - A_FIRST) { kind = 2; en = p && p->online; }
        if (i == A_GM - A_FIRST) en = p && p->online;
        if (i == A_RECLAIM - A_FIRST) en = p && !p->official;
        pill(dc, r_act[i], kind, g_hover == A_FIRST + i, en && g_up, lb);
    }
    /* log panel */
    RECT lp = {462, 106, WW - 24, WH - 92}; fill(dc, lp, C_PANEL, 18);
    RECT lh = {482, 116, 700, 140}; txt(dc, f_h, C_TXT, lh, L"Live log", DT_LEFT | DT_SINGLELINE);
    for (int i = 0; i < NFILT; i++) {
        RECT r = r_filt[i];
        if (i == g_filter) fill(dc, r, C_ACC, 12); else { fill(dc, r, g_hover == F_FIRST + i ? RGB(44, 47, 62) : RGB(30, 32, 44), 12); }
        txt(dc, f_small, i == g_filter ? RGB(42, 10, 22) : C_TXT, r, FILTERS[i], DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    /* bottom bar */
    RECT bar = {72, WH - 84, WW, WH}; fill(dc, bar, RGB(8, 9, 14), 0);
    pill(dc, r_import, 0, g_hover == B_IMPORT, g_up, L"Import backup");
    pill(dc, r_mailall, 0, g_hover == B_MAILALL, g_up, L"Mail everyone");
    pill(dc, r_start, 1, g_hover == B_START, !g_up && !g_starting, L"Start");
    pill(dc, r_stop, 2, g_hover == B_STOP, g_up, L"Stop");
    pill(dc, r_restart, 0, g_hover == B_RESTART, g_up, L"Restart");

    BitBlt(wdc, 0, 0, WW, WH, dc, 0, 0, SRCCOPY);
    SelectObject(dc, ob); DeleteObject(bb); DeleteDC(dc); EndPaint(h, &ps);
}

static int hit(int x, int y) {
    POINT pt = {x, y};
    if (PtInRect(&r_close, pt)) return B_CLOSE;
    if (PtInRect(&r_min, pt)) return B_MIN;
    if (PtInRect(&r_start, pt)) return B_START;
    if (PtInRect(&r_stop, pt)) return B_STOP;
    if (PtInRect(&r_restart, pt)) return B_RESTART;
    if (PtInRect(&r_savedir, pt)) return B_SAVEDIR;
    if (PtInRect(&r_logfile, pt)) return B_LOGFILE;
    if (PtInRect(&r_import, pt)) return B_IMPORT;
    if (PtInRect(&r_mailall, pt)) return B_MAILALL;
    for (int i = 0; i < 10; i++) if (PtInRect(&r_act[i], pt)) return A_FIRST + i;
    for (int i = 0; i < NFILT; i++) if (PtInRect(&r_filt[i], pt)) return F_FIRST + i;
    return B_NONE;
}

static void click(int b) {
    char p[MAX_PATH + 16];
    switch (b) {
    case B_CLOSE: PostMessageW(g_win, WM_CLOSE, 0, 0); return;
    case B_MIN: ShowWindow(g_win, SW_MINIMIZE); return;
    case B_START: if (!g_up) start_server(); break;
    case B_STOP: if (g_up && MessageBoxW(g_win, L"Stop the server? Everyone online is disconnected.", L"Rozefield Server", MB_YESNO | MB_ICONQUESTION) == IDYES) stop_server(); break;
    case B_RESTART: if (g_up) CloseHandle(CreateThread(NULL, 0, restart_thread, NULL, 0, NULL)); break;
    case B_SAVEDIR: snprintf(p, sizeof p, "%ssave\\accounts", g_dir); ShellExecuteA(NULL, "open", p, NULL, NULL, SW_SHOWNORMAL); break;
    case B_LOGFILE: snprintf(p, sizeof p, "%sserver.log", g_dir); ShellExecuteA(NULL, "open", p, NULL, NULL, SW_SHOWNORMAL); break;
    default:
        if (b >= F_FIRST && b < F_FIRST + NFILT) { g_filter = b - F_FIRST; rebuild_log(); }
        else if ((b >= A_FIRST && b < A_LAST) || b == B_IMPORT || b == B_MAILALL) { if (g_up) do_action(b); }
    }
    InvalidateRect(g_win, NULL, FALSE);
}

static void fill_list(void) {
    static wchar_t lastq[64]; wchar_t q0[64]; GetWindowTextW(g_find, q0, 64);
    if (g_npl_new == g_npl && !memcmp(g_pl, g_pl_new, sizeof(struct pl) * g_npl) && !wcscmp(q0, lastq) && SendMessageW(g_list, LB_GETCOUNT, 0, 0) > 0) return;
    wcscpy(lastq, q0);
    int keep = g_sel >= 0 && g_sel < g_npl ? g_pl[g_sel].pid : -1;
    EnterCriticalSection(&g_cs);
    memcpy(g_pl, g_pl_new, sizeof(struct pl) * g_npl_new); g_npl = g_npl_new;
    LeaveCriticalSection(&g_cs);
    wchar_t q[64]; GetWindowTextW(g_find, q, 64); _wcslwr(q);
    SendMessageW(g_list, WM_SETREDRAW, FALSE, 0);
    int top = (int)SendMessageW(g_list, LB_GETTOPINDEX, 0, 0);
    SendMessageW(g_list, LB_RESETCONTENT, 0, 0);
    g_sel = -1;
    for (int i = 0; i < g_npl; i++) {
        wchar_t n[80]; wcsncpy(n, g_pl[i].name, 79); n[79] = 0; _wcslwr(n);
        wchar_t lab[24]; swprintf(lab, 24, L"%d", g_pl[i].label);
        if (q[0] && !wcsstr(n, q) && !wcsstr(lab, q)) continue;
        int idx = (int)SendMessageW(g_list, LB_ADDSTRING, 0, (LPARAM)L"");
        SendMessageW(g_list, LB_SETITEMDATA, idx, i);
        if (g_pl[i].pid == keep) { SendMessageW(g_list, LB_SETCURSEL, idx, 0); g_sel = i; }
    }
    SendMessageW(g_list, LB_SETTOPINDEX, top, 0);
    SendMessageW(g_list, WM_SETREDRAW, TRUE, 0); InvalidateRect(g_list, NULL, TRUE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: paint(h); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLOREDIT: case WM_CTLCOLORSTATIC:
        SetTextColor((HDC)w, (HWND)l == g_logv ? RGB(206, 209, 222) : C_TXT); SetBkColor((HDC)w, (HWND)l == g_logv ? C_PANEL : C_FIELD);
        return (LRESULT)((HWND)l == g_logv ? br_panel : br_field);
    case WM_CTLCOLORLISTBOX: SetBkColor((HDC)w, C_PANEL); return (LRESULT)br_panel;
    case WM_MEASUREITEM: ((MEASUREITEMSTRUCT *)l)->itemHeight = 40; return TRUE;
    case WM_DRAWITEM: {
        DRAWITEMSTRUCT *d = (DRAWITEMSTRUCT *)l;
        if (d->itemID == (UINT)-1) return TRUE;
        int i = (int)SendMessageW(g_list, LB_GETITEMDATA, d->itemID, 0); if (i < 0 || i >= g_npl) return TRUE;
        struct pl *p = &g_pl[i]; RECT r = d->rcItem;
        fill(d->hDC, r, C_PANEL, 0);
        if (d->itemState & ODS_SELECTED) { RECT s = {r.left + 2, r.top + 2, r.right - 2, r.bottom - 2}; fill(d->hDC, s, RGB(52, 40, 54), 12); }
        dot(d->hDC, r.left + 18, (r.top + r.bottom) / 2, 5, p->banned ? C_BAD : p->online ? C_OK : RGB(80, 84, 100));
        RECT rn = {r.left + 34, r.top + 3, r.right - 110, r.top + 22}; txt(d->hDC, f_body, p->banned ? RGB(200, 150, 150) : C_TXT, rn, p->name, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
        wchar_t sub[120]; swprintf(sub, 120, L"Lv %d  \x00B7  UID %d%ls", p->level, p->label, p->official ? L"  \x00B7  imported" : L"");
        RECT rsub = {r.left + 34, r.top + 21, r.right - 110, r.bottom - 2}; txt(d->hDC, f_small, C_MUTE, rsub, sub, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
        wchar_t tags[60] = L"";
        if (p->banned) wcscat(tags, L"banned  "); if (p->muted) wcscat(tags, L"muted  "); if (!p->pw) wcscat(tags, L"no password");
        RECT rtg = {r.right - 120, r.top, r.right - 10, r.bottom}; txt(d->hDC, f_small, p->banned ? C_BAD : C_WARN, rtg, tags, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
        return TRUE; }
    case WM_COMMAND:
        if ((HWND)l == g_list && HIWORD(w) == LBN_SELCHANGE) {
            int idx = (int)SendMessageW(g_list, LB_GETCURSEL, 0, 0);
            g_sel = idx >= 0 ? (int)SendMessageW(g_list, LB_GETITEMDATA, idx, 0) : -1; InvalidateRect(h, NULL, FALSE);
        } else if ((HWND)l == g_find && HIWORD(w) == EN_CHANGE) fill_list();
        else if ((HWND)l == g_search && HIWORD(w) == EN_CHANGE) rebuild_log();
        return 0;
    case WM_DATA:
        if (w) fill_list();
        if (g_lines_dirty) rebuild_log();
        InvalidateRect(h, NULL, FALSE); return 0;
    case WM_NCHITTEST: {
        LRESULT r = DefWindowProcW(h, m, w, l);
        if (r == HTCLIENT) { POINT pt = {(short)LOWORD(l), (short)HIWORD(l)}; ScreenToClient(h, &pt); if (pt.y < 100 && pt.x > 72 && hit(pt.x, pt.y) == B_NONE) return HTCAPTION; }
        return r; }
    case WM_MOUSEMOVE: {
        int b = hit((short)LOWORD(l), (short)HIWORD(l));
        if (b != g_hover) { g_hover = b; TRACKMOUSEEVENT te = {sizeof te, TME_LEAVE, h, 0}; TrackMouseEvent(&te); InvalidateRect(h, NULL, FALSE); }
        return 0; }
    case WM_MOUSELEAVE: g_hover = 0; InvalidateRect(h, NULL, FALSE); return 0;
    case WM_SETCURSOR: if (LOWORD(l) == HTCLIENT && g_hover) { SetCursor(LoadCursor(NULL, IDC_HAND)); return TRUE; } break;
    case WM_LBUTTONUP: click(hit((short)LOWORD(l), (short)HIWORD(l))); return 0;
    case WM_CLOSE:
        if (g_proc && g_up) {
            int r = MessageBoxW(h, L"Stop the server too?\n\nYes: stop it.  No: keep it running in the background (open this window again to control it).", L"Rozefield Server", MB_YESNOCANCEL | MB_ICONQUESTION);
            if (r == IDCANCEL) return 0;
            if (r == IDYES) stop_server();
        }
        DestroyWindow(h); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    GetModuleFileNameA(NULL, g_dir, MAX_PATH); char *sl = strrchr(g_dir, '\\'); if (sl) sl[1] = 0;
    InitializeCriticalSection(&g_cs);
    WSADATA wd; WSAStartup(MAKEWORD(2, 2), &wd);
    f_title = CreateFontW(-36, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_h = CreateFontW(-18, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_body = CreateFontW(-15, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_small = CreateFontW(-13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_btn = CreateFontW(-18, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_mono = CreateFontW(-13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, FIXED_PITCH, L"Cascadia Mono");
    br_panel = CreateSolidBrush(C_PANEL); br_field = CreateSolidBrush(C_FIELD);
    for (int i = 0; i < 10; i++) { int c = i % 2, r = i / 2; r_act[i] = (RECT){116 + c * 160, 408 + r * 44, 266 + c * 160, 444 + r * 44}; }
    for (int i = 0; i < NFILT; i++) r_filt[i] = (RECT){482 + i * 74, 148, 550 + i * 74, 174};

    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = hi; wc.lpszClassName = L"RozefieldServerPanel";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW); wc.hIcon = LoadIcon(NULL, IDI_APPLICATION); RegisterClassW(&wc);
    WNDCLASSW dc = {0}; dc.lpfnWndProc = DlgProc; dc.hInstance = hi; dc.lpszClassName = L"RzDlg"; dc.hCursor = LoadCursor(NULL, IDC_ARROW); RegisterClassW(&dc);
    g_win = CreateWindowExW(WS_EX_APPWINDOW, L"RozefieldServerPanel", L"Rozefield Server", WS_POPUP | WS_MINIMIZEBOX | WS_SYSMENU | WS_CLIPCHILDREN,
                            (GetSystemMetrics(SM_CXSCREEN) - WW) / 2, (GetSystemMetrics(SM_CYSCREEN) - WH) / 2, WW, WH, NULL, NULL, hi, NULL);
    SetWindowRgn(g_win, CreateRoundRectRgn(0, 0, WW + 1, WH + 1, 16, 16), TRUE);
    g_find = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 230, 116, 196, 26, g_win, NULL, hi, NULL);
    SendMessageW(g_find, EM_SETCUEBANNER, TRUE, (LPARAM)L"Find name or UID");
    g_list = CreateWindowExW(0, L"LISTBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_OWNERDRAWFIXED | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
                             108, 150, 326, 222, g_win, NULL, hi, NULL);
    g_search = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, WW - 260, 147, 216, 28, g_win, NULL, hi, NULL);
    SendMessageW(g_search, EM_SETCUEBANNER, TRUE, (LPARAM)L"Search the log");
    g_logv = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
                             482, 186, WW - 526, WH - 290, g_win, NULL, hi, NULL);
    SendMessageW(g_logv, EM_SETLIMITTEXT, 0, 0);
    SendMessageW(g_find, WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(g_search, WM_SETFONT, (WPARAM)f_body, TRUE);
    SendMessageW(g_logv, WM_SETFONT, (WPARAM)f_mono, TRUE);
    SendMessageW(g_find, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6)); SendMessageW(g_search, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6));
    ShowWindow(g_win, show); UpdateWindow(g_win);
    note(L"Rozefield Server panel opened.");
    read_token();
    CloseHandle(CreateThread(NULL, 0, poller, NULL, 0, NULL));
    Sleep(900);
    if (!g_up && !strstr(cmd, "--no-start")) start_server();   /* opening the panel starts the server */
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return 0;
}
