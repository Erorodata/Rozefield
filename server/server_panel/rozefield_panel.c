/* Rozefield Server.exe - the server's control panel. Starts rozefield_server.py in the background (no console window)
 * and talks to it through its owner API (/admin/..., this PC only, token in save\admin_token.txt):
 * players online/offline, reset / clear password, rename, GM commands, mail, chat log, kick, ban, mute,
 * reclaim an old official id, import a backup, and the live log with filters.
 * If the server is already running (start_server.bat) the panel attaches to it.
 * Connect: control a Rozefield Server on another device (Linux box, VPS, another PC) with its admin password; every
 * request is signed (HMAC-SHA256, key from PBKDF2 of the password), the password itself is never sent.
 * Hosting: display name, fixed server name, router ports, download link, home-network discovery, start with Windows.
 * Imports (review / undo), Move server (export / import everything), Game package (Rozefield.zip for players).
 * --background (used by "start with Windows"): start the server and stay in the tray.
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 rozefield_panel.c panel.rc -o "Rozefield Server.exe"
 *        -lws2_32 -lcomdlg32 -lshell32 -luser32 -lgdi32 -lmsimg32 -lbcrypt -ladvapi32 -Wl,--subsystem,windows
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
#include <bcrypt.h>
#include <time.h>
#include <richedit.h>

#define WW 1180
#define WH 760
#define SB 200          /* sidebar width */
#define X0 (SB + 24)    /* main area */
#define C_INK RGB(244, 246, 248)   /* OverField UI theme */
#define C_PANEL RGB(255, 255, 255)
#define C_LINE RGB(214, 218, 226)
#define C_TILE RGB(236, 237, 241)
#define C_ACC RGB(19, 181, 197)
#define C_OK RGB(60, 194, 122)
#define C_BAD RGB(220, 60, 70)
#define C_TXT RGB(42, 44, 54)
#define C_MUTE RGB(122, 126, 142)
#define C_WARN RGB(232, 140, 20)
#define C_FIELD RGB(236, 237, 241)
#define WM_DATA (WM_APP + 1)
#define WM_TRAY (WM_APP + 2)
#ifndef EM_SETCUEBANNER
#define EM_SETCUEBANNER 0x1501
#endif

static HWND g_win, g_list, g_logv, g_find, g_search;
static HFONT f_title, f_h, f_body, f_small, f_btn, f_mono, f_icon;
static HBRUSH br_panel, br_field;
static char g_dir[MAX_PATH], g_token[64];
static int g_port = 18881;
static HANDLE g_proc;                 /* the server we started (NULL if attached to one started elsewhere) */
static volatile int g_up, g_starting;
static int g_hover, g_filter, g_sel = -1;
static long g_lognext;
static int g_follow = 1;   /* next log rebuild jumps to the newest line (filter change, start) */
/* where the server is: this PC (g_remote 0, token) or another device (g_host, signing key from the admin password) */
static char g_host[256]; static int g_remote; static unsigned char g_key[32]; static int g_haskey;
static NOTIFYICONDATAW g_tray; static int g_bg;

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

/* ---------------------------------------------------------------- signing (another device) */
static int hmac256(const unsigned char *key, int kl, const unsigned char *msg, int ml, unsigned char out[32]) {
    BCRYPT_ALG_HANDLE alg; BCRYPT_HASH_HANDLE hh; int ok = 0;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, key ? BCRYPT_ALG_HANDLE_HMAC_FLAG : 0)) return 0;
    if (!BCryptCreateHash(alg, &hh, NULL, 0, (PUCHAR)key, key ? kl : 0, 0)) {
        ok = !BCryptHashData(hh, (PUCHAR)msg, ml, 0) && !BCryptFinishHash(hh, out, 32, 0);
        BCryptDestroyHash(hh);
    }
    BCryptCloseAlgorithmProvider(alg, 0); return ok;
}
static void hexs(const unsigned char *b, int n, char *o) { for (int i = 0; i < n; i++) sprintf(o + 2 * i, "%02x", b[i]); o[2 * n] = 0; }
static int unhex(const char *h, unsigned char *o, int n) {
    for (int i = 0; i < n; i++) { unsigned v; if (sscanf(h + 2 * i, "%2x", &v) != 1) return 0; o[i] = (unsigned char)v; } return 1;
}
static int derive_key(const char *pw, const char *salthex, int rounds, unsigned char out[32]) {
    unsigned char salt[64]; int sl = (int)strlen(salthex) / 2; if (sl > 64 || !unhex(salthex, salt, sl)) return 0;
    BCRYPT_ALG_HANDLE alg; if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG)) return 0;
    int ok = !BCryptDeriveKeyPBKDF2(alg, (PUCHAR)pw, (ULONG)strlen(pw), salt, sl, rounds, out, 32, 0);
    BCryptCloseAlgorithmProvider(alg, 0); return ok;
}
static void conn_ini(char *p) { snprintf(p, MAX_PATH, "%sRozefield Server.ini", g_dir); }
static void load_conn(void) {
    char p[MAX_PATH], k[80]; conn_ini(p);
    GetPrivateProfileStringA("connect", "host", "", g_host, sizeof g_host, p);
    GetPrivateProfileStringA("connect", "key", "", k, sizeof k, p);
    g_remote = g_host[0] != 0; g_haskey = strlen(k) == 64 && unhex(k, g_key, 32);
}
static void save_conn(void) {
    char p[MAX_PATH], k[80] = ""; conn_ini(p); if (g_haskey) hexs(g_key, 32, k);
    WritePrivateProfileStringA("connect", "host", g_host, p); WritePrivateProfileStringA("connect", "key", g_remote ? k : "", p);
}

/* ---------------------------------------------------------------- HTTP to the server */
static int http_raw(const char *method, const char *path, const char *body, int blen, char **out, int *outlen) {
    *out = NULL; if (outlen) *outlen = 0;
    struct addrinfo hints = {0}, *ai = NULL; hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM;
    char port[16]; snprintf(port, sizeof port, "%d", g_port);
    if (getaddrinfo(g_remote ? g_host : "127.0.0.1", port, &hints, &ai) != 0 || !ai) return 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    DWORD to = 20000; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    int c = connect(s, ai->ai_addr, (int)ai->ai_addrlen); freeaddrinfo(ai);
    if (c != 0) { closesocket(s); return 0; }
    char hdr[700], auth[300] = "";
    if (g_remote) {
        unsigned char bh[32], sig[32]; char bhx[65], sigx[65]; hmac256(NULL, 0, (const unsigned char *)body, blen, bh); hexs(bh, 32, bhx);
        long long t = (long long)time(NULL); size_t ml = strlen(path) + 200; char *msg = (char *)malloc(ml);
        int n = snprintf(msg, ml, "%lld\n%s\n%s\n%s", t, method, path, bhx);
        hmac256(g_key, 32, (const unsigned char *)msg, n, sig); hexs(sig, 32, sigx); free(msg);
        snprintf(auth, sizeof auth, "X-Admin-Time: %lld\r\nX-Admin-Sig: %s\r\n", t, sigx);
    } else snprintf(auth, sizeof auth, "X-Admin-Token: %s\r\n", g_token);
    int hl = snprintf(hdr, sizeof hdr, "%s %s HTTP/1.0\r\nHost: rozefield\r\n%sContent-Length: %d\r\n\r\n", method, path, auth, blen);
    send(s, hdr, hl, 0);
    for (int off = 0; off < blen;) { int n = send(s, body + off, blen - off, 0); if (n <= 0) break; off += n; }
    int cap = 65536, len = 0, r; char *b = (char *)malloc(cap + 1);
    while ((r = recv(s, b + len, cap - len, 0)) > 0) { len += r; if (len == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
    b[len] = 0; closesocket(s);
    int code = 0; sscanf(b, "HTTP/%*s %d", &code);
    char *p = strstr(b, "\r\n\r\n");
    if (!p || code != 200) { free(b); return code == 403 ? -1 : 0; }
    int bl = len - (int)(p + 4 - b);
    memmove(b, p + 4, bl + 1);
    *out = b; if (outlen) *outlen = bl; return 1;
}
static int http(const char *method, const char *path, const char *body, int blen, char **out) {
    return http_raw(method, path, body, blen, out, NULL) == 1;
}
static wchar_t *wide(const char *u) {
    int n = MultiByteToWideChar(CP_UTF8, 0, u, -1, NULL, 0); wchar_t *w = (wchar_t *)malloc(n * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, u, -1, w, n); return w;
}
/* POST/GET a hosting call; returns malloc'd text after OK| / ERR| (or the whole answer), *ok set */
static wchar_t *host_call(const char *method, const char *path, const char *body, int blen, int *ok) {
    char *out; *ok = 0;
    if (!http(method, path, body, blen, &out)) return _wcsdup(L"The server didn't answer (or refused the admin password).");
    *ok = strncmp(out, "ERR|", 4) != 0;
    const char *t = (!strncmp(out, "OK|", 3) || !strncmp(out, "ERR|", 4)) ? strchr(out, '|') + 1 : out;
    wchar_t *w = wide(t); free(out); return w;
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
/* traffic (GET /admin/host/traffic): rates, 60 x 10 s history, per player */
static long long t_down, t_up, t_msgs, t_today, t_dl;
static int t_hist[60][3], t_nhist;
struct tp { wchar_t name[64]; long long down, up, msgs; };
static struct tp t_pl[12]; static int t_npl;
static void parse_traffic(char *out) {
    char *save = NULL; int np = 0;
    for (char *line = strtok_s(out, "\n", &save); line; line = strtok_s(NULL, "\n", &save)) {
        if (!strncmp(line, "rate|", 5)) sscanf(line + 5, "%lld|%lld|%lld|%lld|%lld", &t_down, &t_up, &t_msgs, &t_today, &t_dl);
        else if (!strncmp(line, "hist|", 5)) {
            int n = 0; char *q = line + 5;
            while (*q && n < 60) { sscanf(q, "%d,%d,%d", &t_hist[n][0], &t_hist[n][1], &t_hist[n][2]); n++; q = strchr(q, ';'); if (!q) break; q++; }
            t_nhist = n;
        } else if (!strncmp(line, "p|", 2) && np < 12) {
            char *f[5] = {0}; int k = 0; char *q = line;
            while (k < 5) { f[k++] = q; char *bar = strchr(q, '|'); if (!bar) break; *bar = 0; q = bar + 1; }
            if (k == 5) { MultiByteToWideChar(CP_UTF8, 0, f[1], -1, t_pl[np].name, 64); t_pl[np].down = atoll(f[2]); t_pl[np].up = atoll(f[3]); t_pl[np].msgs = atoll(f[4]); np++; }
        }
    }
    t_npl = np;
}

static DWORD WINAPI poller(LPVOID a) {
    for (int tick = 0;; tick++) {
        char *out;
        if (!g_remote && (g_token[0] == 0 || tick % 10 == 0)) read_token();
        int up = (g_remote ? g_haskey : g_token[0] != 0) && http("GET", "/admin/players", "", 0, &out);
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
            if (tick % 2 == 0 && http("GET", "/admin/host/traffic", "", 0, &out)) { parse_traffic(out); free(out); }
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
    static wchar_t own[MAX_PATH + 4]; static const wchar_t *pys[] = {own, L"py -3.13", L"py -3.12", L"py -3", L"python"};
    { wchar_t wd0[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_dir, -1, wd0, MAX_PATH); swprintf(own, MAX_PATH + 4, L"\"%lspython\\python.exe\"", wd0); }
    const wchar_t *py = NULL;
    for (int i = 0; i < 5 && !py; i++) { wchar_t c[64]; swprintf(c, 64, L"%ls -c \"1\"", pys[i]); if (run_ok(c)) py = pys[i]; }
    if (!py) { note(L"Python 3 was not found. Run setup_python.bat once (or install Python from python.org)."); g_starting = 0; return 0; }
    wchar_t c[256]; swprintf(c, 256, L"%ls -c \"import google.protobuf, cramjam\"", py);
    if (!run_ok(c)) { note(L"Installing what the server needs (first start)..."); swprintf(c, 256, L"%ls -m pip install -r requirements.txt", py); run_ok(c); }
    char game[MAX_PATH], gp[MAX_PATH]; snprintf(game, sizeof game, "%s..\\Overfield", g_dir); snprintf(gp, sizeof gp, "%sgame_path.txt", g_dir);
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
static void start_server(void) {
    if (g_remote) { note(L"Connected to %hs: start it on that device (or it starts by itself as a service).", g_host); return; }
    if (!g_starting) { g_starting = 1; CloseHandle(CreateThread(NULL, 0, start_thread, NULL, 0, NULL)); }
}
static void stop_server(void) {
    int ok; wchar_t *r = act("stop", &ok); free(r);
    if (g_proc) { if (WaitForSingleObject(g_proc, 4000) != WAIT_OBJECT_0) TerminateProcess(g_proc, 0); }
    note(L"Server stopped.");
}
static DWORD WINAPI restart_thread(LPVOID a) {
    if (g_remote) { int ok; wchar_t *r = host_call("POST", "/admin/host/restart", "", 0, &ok); note(L"Restart: %ls", r); free(r); return 0; }
    stop_server(); for (int i = 0; i < 20 && g_up; i++) Sleep(300); Sleep(800); start_server(); return 0;
}

/* ---------------------------------------------------------------- dialogs */
static wchar_t g_dlg_out[10][1024]; static int g_dlg_done, g_dlg_n;
static HWND g_dlg_edits[10], g_dlg_combo;

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
    int W = (flags & 4) ? 620 : 460, rowh = n > 5 ? 52 : 58, H = 120 + n * rowh + ((flags & 2) ? 90 : 0) + (intro ? 44 : 0);
    RECT pr; GetWindowRect(g_win, &pr);
    HWND d = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, L"RzDlg", title, WS_POPUP | WS_CAPTION | WS_SYSMENU,
                             (pr.left + pr.right - W) / 2, max(0, (int)(pr.top + pr.bottom - H) / 2), W, H, g_win, NULL, GetModuleHandleW(NULL), NULL);
    int y = 16;
    if (intro) { HWND s = CreateWindowW(L"STATIC", intro, WS_CHILD | WS_VISIBLE, 18, y, W - 40, 40, d, NULL, NULL, NULL); SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE); y += 44; }
    g_dlg_n = n;
    for (int i = 0; i < n; i++) {
        HWND s = CreateWindowW(L"STATIC", labels[i], WS_CHILD | WS_VISIBLE, 18, y, W - 40, 18, d, NULL, NULL, NULL);
        SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE);
        int multi = (flags & 2) && i == n - 1;
        int pw = (flags & 1) || ((flags >> 8) & (1 << i));   /* bit 8+i: only field i hides what is typed */
        DWORD st = WS_CHILD | WS_VISIBLE | WS_TABSTOP | (multi ? (ES_MULTILINE | ES_WANTRETURN | WS_VSCROLL) : ES_AUTOHSCROLL) | (pw ? ES_PASSWORD : 0);
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
       B_CONNECT, B_HOSTING, B_IMPORTS, B_MOVE, B_PACKAGE,
       A_FIRST, A_RESETPW = A_FIRST, A_CLEARPW, A_RENAME, A_GM, A_MAIL, A_CHAT, A_KICK, A_BAN, A_MUTE, A_RECLAIM, A_LAST,
       F_FIRST = 50 };
static const wchar_t *ACT_LABEL[] = {L"Reset password", L"Clear password", L"Rename", L"GM commands", L"Send mail", L"Chat log",
                                     L"Kick", L"Ban", L"Mute", L"Reclaim old ID"};
static const wchar_t *FILTERS[] = {L"All", L"Logins", L"Errors", L"Chat", L"Admin", L"HTTP", L"Player"};
#define NFILT 7
static RECT r_close = {WW - 52, 10, WW - 12, 46}, r_min = {WW - 96, 10, WW - 56, 46};
static RECT r_start = {WW - 420, WH - 70, WW - 300, WH - 26}, r_stop = {WW - 290, WH - 70, WW - 170, WH - 26}, r_restart = {WW - 160, WH - 70, WW - 36, WH - 26};
static RECT r_savedir = {12, WH - 120, SB - 12, WH - 88}, r_logfile = {12, WH - 82, SB - 12, WH - 50};
static RECT r_import = {X0, WH - 70, X0 + 150, WH - 26}, r_mailall = {X0 + 160, WH - 70, X0 + 300, WH - 26}, r_connect = {X0 + 310, WH - 70, X0 + 470, WH - 26};
static RECT r_hosting = {600, 26, 700, 58}, r_imports = {708, 26, 798, 58}, r_move = {806, 26, 922, 58}, r_package = {930, 26, 1060, 58};
static RECT r_act[10], r_filt[NFILT];

static struct pl *sel(void) { return (g_sel >= 0 && g_sel < g_npl) ? &g_pl[g_sel] : NULL; }

static void result(const wchar_t *what, wchar_t *r, int ok) {
    if (wcslen(r) > 160 || wcschr(r, L'\n')) show_text(what, r);
    else MessageBoxW(g_win, r, what, MB_OK | (ok ? MB_ICONINFORMATION : MB_ICONWARNING));
    free(r);
}

/* ---------------------------------------------------------------- hosting */
/* value of "key" in a flat JSON text (after `from`): strings (with \" and \\), true/false/numbers */
static int json_get(const char *js, const char *from, const char *key, char *out, int n) {
    out[0] = 0; const char *b = from ? strstr(js, from) : js; if (!b) return 0;
    char k[80]; snprintf(k, sizeof k, "\"%s\":", key); const char *p = strstr(b, k); if (!p) return 0;
    p += strlen(k); while (*p == ' ') p++;
    int i = 0;
    if (*p == '"') { for (p++; *p && *p != '"' && i < n - 1; p++) { if (*p == '\\' && p[1]) { p++; out[i++] = *p == 'n' ? '\n' : *p; } else out[i++] = *p; } }
    else while (*p && *p != ',' && *p != '}' && i < n - 1) out[i++] = *p++;
    out[i] = 0; return 1;
}
static void json_put(char *b, size_t bs, const char *k, const wchar_t *v, int boolean) {
    char u[2048]; WideCharToMultiByte(CP_UTF8, 0, v, -1, u, sizeof u, NULL, NULL);
    size_t l = strlen(b); l += snprintf(b + l, bs - l, "%s\"%s\":", l > 1 ? "," : "", k);
    if (boolean) { snprintf(b + l, bs - l, "%s", (u[0] == 'y' || u[0] == 'Y' || u[0] == '1' || u[0] == 'o' || u[0] == 'O') ? "true" : "false"); return; }
    b[l++] = '"';
    for (char *c = u; *c && l < bs - 4; c++) { if (*c == '"' || *c == '\\') b[l++] = '\\'; if ((unsigned char)*c >= 32) b[l++] = *c; }
    b[l++] = '"'; b[l] = 0;
}
#define RUNKEY L"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
static int autostart_on(void) {
    wchar_t v[MAX_PATH * 2]; DWORD sz = sizeof v;
    return RegGetValueW(HKEY_CURRENT_USER, RUNKEY, L"Rozefield Server", RRF_RT_REG_SZ, NULL, v, &sz) == ERROR_SUCCESS;
}
static void autostart_set(int on) {
    HKEY k; if (RegCreateKeyExW(HKEY_CURRENT_USER, RUNKEY, 0, NULL, 0, KEY_WRITE, NULL, &k, NULL)) return;
    if (on) { wchar_t exe[MAX_PATH], v[MAX_PATH + 32]; GetModuleFileNameW(NULL, exe, MAX_PATH); swprintf(v, MAX_PATH + 32, L"\"%ls\" --background", exe);
              RegSetValueExW(k, L"Rozefield Server", 0, REG_SZ, (BYTE *)v, (DWORD)((wcslen(v) + 1) * sizeof(wchar_t))); }
    else RegDeleteValueW(k, L"Rozefield Server");
    RegCloseKey(k);
}

static void do_connect(void) {
    wchar_t host[256]; MultiByteToWideChar(CP_UTF8, 0, g_host, -1, host, 256);
    const wchar_t *lab[] = {L"Server address: its name, internet or home-network address (leave empty for this PC)"}; const wchar_t *init[] = {host};
    if (!ask(L"Connect", L"Control the Rozefield Server on another device (mini PC, Linux box, VPS) with its admin password.", 1, lab, init, 4)) return;
    char nh[256]; WideCharToMultiByte(CP_UTF8, 0, g_dlg_out[0], -1, nh, sizeof nh, NULL, NULL);
    { char *e = nh + strlen(nh); while (e > nh && (e[-1] == ' ' || e[-1] == '/')) *--e = 0; char *b = nh; while (*b == ' ') b++;
      if (!strncmp(b, "http://", 7)) b += 7; memmove(nh, b, strlen(b) + 1); char *c = strchr(nh, ':'); if (c) *c = 0; }
    if (!nh[0] || !strcmp(nh, "localhost") || !strcmp(nh, "127.0.0.1")) {
        g_host[0] = 0; g_remote = 0; g_haskey = 0; save_conn(); read_token(); note(L"Connected to this PC."); return;
    }
    const wchar_t *lab2[] = {L"Admin password (set on that device)"};
    if (!ask(L"Connect", NULL, 1, lab2, NULL, 1)) return;
    char pw[512]; WideCharToMultiByte(CP_UTF8, 0, g_dlg_out[0], -1, pw, sizeof pw, NULL, NULL);
    char old[256]; int oldr = g_remote, oldk = g_haskey; unsigned char oldkey[32]; strcpy(old, g_host); memcpy(oldkey, g_key, 32);
    strcpy(g_host, nh); g_remote = 1; g_haskey = 0;
    char *out; int ok = 0;
    if (http("GET", "/admin/salt", "", 0, &out)) {
        char *bar = strchr(out, '|');
        if (!out[0]) MessageBoxW(g_win, L"That server has no admin password yet.\n\nOn that device run:  start_server --set-admin-password <password>\n(or set it in Hosting on that device's own panel).", L"Connect", MB_OK | MB_ICONWARNING);
        else if (bar) { *bar = 0; ok = derive_key(pw, out, atoi(bar + 1), g_key); }
        free(out);
    } else MessageBoxW(g_win, L"No Rozefield Server answered at that address (TCP 18881).", L"Connect", MB_OK | MB_ICONWARNING);
    SecureZeroMemory(pw, sizeof pw);
    if (ok) { g_haskey = 1; char *o2; int r = http_raw("GET", "/admin/host/status", "", 0, &o2, NULL); if (r == 1) free(o2); ok = r == 1;
              if (r == -1) MessageBoxW(g_win, L"Wrong admin password.", L"Connect", MB_OK | MB_ICONWARNING); }
    if (!ok) { strcpy(g_host, old); g_remote = oldr; g_haskey = oldk; memcpy(g_key, oldkey, 32); return; }
    save_conn(); g_lognext = 0; note(L"Connected to %hs.", g_host);
}

static void do_hosting(void) {
    char *js; if (!http("GET", "/admin/host/status", "", 0, &js)) { MessageBoxW(g_win, L"The server didn't answer.", L"Hosting", MB_OK); return; }
    static const char *keys[] = {"display_name", "server_name", "name_provider", "duckdns_token", "update_url", "download_link", "upnp", "lan_discovery"};
    wchar_t cur[8][600]; char v[1200];
    for (int i = 0; i < 8; i++) { json_get(js, "\"settings\"", keys[i], v, sizeof v); if (i >= 6) strcpy(v, strcmp(v, "false") ? "yes" : "no"); MultiByteToWideChar(CP_UTF8, 0, v, -1, cur[i], 600); }
    char ns[300], rt[300], pub[64], lan[64]; json_get(js, NULL, "name_status", ns, sizeof ns); json_get(js, NULL, "router", rt, sizeof rt);
    json_get(js, NULL, "public_ip", pub, sizeof pub); json_get(js, NULL, "lan_ip", lan, sizeof lan);
    char code[32], lcode[32]; json_get(js, NULL, "invite_code", code, sizeof code); json_get(js, NULL, "lan_code", lcode, sizeof lcode); free(js);
    wchar_t intro[900]; swprintf(intro, 900, L"Invite code %hs (internet)  \x00B7  %hs (home network)  \x00B7  name: %hs\nRouter: %hs",
                                 code[0] ? code : "unknown", lcode, ns, rt); (void)pub; (void)lan;
    const wchar_t *lab[] = {L"Display name (shown in the launcher and on the download page)", L"Fixed server name players use (e.g. myserver.duckdns.org)",
                            L"Name service: none, duckdns, or url (own domain)", L"DuckDNS token (from duckdns.org)", L"Own domain: dynamic-DNS update URL ({ip} = this server's address)",
                            L"Download link for Rozefield.zip (e.g. Google Drive), tried before this server", L"Open router ports automatically (yes / no)",
                            L"Answer launchers on the home network (yes / no)", L"Start with Windows, in the tray (yes / no)", L"New admin password for connecting from another device (empty = keep)"};
    const wchar_t *init[10]; for (int i = 0; i < 8; i++) init[i] = cur[i];
    init[8] = g_remote ? L"(only on that device)" : autostart_on() ? L"yes" : L"no"; init[9] = L"";
    int n = g_remote ? 8 : 10;
    if (!ask(L"Hosting", intro, n, lab, init, 4 | (1 << (8 + 9)))) return;
    char b[8192] = "{";
    for (int i = 0; i < 8; i++) json_put(b, sizeof b, keys[i], g_dlg_out[i], i >= 6);
    strcat(b, "}");
    int ok; wchar_t *r = host_call("POST", "/admin/host/settings", b, (int)strlen(b), &ok);
    wchar_t msg[2000]; swprintf(msg, 2000, L"Settings: %ls", r); free(r);
    if (!g_remote) {
        int on = g_dlg_out[8][0] == L'y' || g_dlg_out[8][0] == L'Y'; autostart_set(on);
        wcscat(msg, on ? L"\nStarts with Windows: on (in the tray)." : L"\nStarts with Windows: off.");
        if (g_dlg_out[9][0]) {
            char pw[512]; WideCharToMultiByte(CP_UTF8, 0, g_dlg_out[9], -1, pw, sizeof pw, NULL, NULL);
            int ok2; wchar_t *r2 = host_call("POST", "/admin/host/password", pw, (int)strlen(pw), &ok2); SecureZeroMemory(pw, sizeof pw);
            wcscat(msg, L"\nAdmin password: "); wcscat(msg, r2); free(r2);
        }
    }
    wchar_t *r3 = host_call("POST", "/admin/host/name", "", 0, &ok); wcscat(msg, L"\nServer name: "); wcsncat(msg, r3, 400); free(r3);
    MessageBoxW(g_win, msg, L"Hosting", MB_OK | MB_ICONINFORMATION);
}

static void do_imports(void) {
    char *out; if (!http("GET", "/admin/host/imports", "", 0, &out)) { MessageBoxW(g_win, L"The server didn't answer.", L"Imports", MB_OK); return; }
    size_t cap = strlen(out) * 2 + 64; char *t = (char *)malloc(cap); t[0] = 0; size_t l = 0; char *save = NULL;
    for (char *line = strtok_s(out, "\n", &save); line; line = strtok_s(NULL, "\n", &save)) {
        char *f[7] = {0}; int k = 0; char *q = line;
        while (k < 7) { f[k++] = q; char *bar = strchr(q, '|'); if (!bar) break; *bar = 0; q = bar + 1; }
        if (k < 7) continue;
        time_t tt = (time_t)atoll(f[1]); struct tm *lt = localtime(&tt); char when[32] = "";
        if (lt) strftime(when, sizeof when, "%d %b %H:%M", lt);
        l += snprintf(t + l, cap - l, "#%s  %s  %s  %s (%s)%s%s\r\n", f[0], when, f[2][0] ? f[2] : "?", !strcmp(f[5], "ok") ? "imported" : "REFUSED",
                      f[4], f[6][0] ? ": " : "", f[6]);
    }
    if (!l) strcpy(t, "No imports yet.");
    wchar_t *w = wide(t); free(t); free(out);
    const wchar_t *lab[] = {L"Import number to undo (e.g. 3) - leave empty to close", L"Imports, newest first"}; const wchar_t *init[] = {L"", w};
    int r = ask(L"Imported accounts", L"Undo puts the account back as it was before (or removes it if it was new). The player must be offline.", 2, lab, init, 2 | 4);
    free(w);
    if (!r || !g_dlg_out[0][0]) return;
    int id = _wtoi(g_dlg_out[0][0] == L'#' ? g_dlg_out[0] + 1 : g_dlg_out[0]); if (id <= 0) return;
    wchar_t q[100]; swprintf(q, 100, L"Undo import #%d?", id);
    if (MessageBoxW(g_win, q, L"Imported accounts", MB_YESNO | MB_ICONQUESTION) != IDYES) return;
    char b[32]; snprintf(b, sizeof b, "%d", id); int ok; wchar_t *res = host_call("POST", "/admin/host/undo_import", b, (int)strlen(b), &ok);
    MessageBoxW(g_win, res, L"Imported accounts", MB_OK | (ok ? MB_ICONINFORMATION : MB_ICONWARNING)); free(res);
}

static void do_move(void) {
    int r = MessageBoxW(g_win, L"Move this server to another device.\n\nYes: export everything (accounts, chat, photos, settings, game update) to one file.\nNo: import a file exported from another server (replaces this server's data after a restart; the current data is kept).",
                        L"Move server", MB_YESNOCANCEL | MB_ICONQUESTION);
    if (r == IDYES) {
        wchar_t fn[MAX_PATH] = L"Rozefield server export.zip"; OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win;
        of.lpstrFilter = L"Server export (*.zip)\0*.zip\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH; of.lpstrDefExt = L"zip"; of.Flags = OFN_OVERWRITEPROMPT;
        if (!GetSaveFileNameW(&of)) return;
        note(L"Exporting the server..."); char *out; int len;
        if (http_raw("GET", "/admin/host/export", "", 0, &out, &len) != 1) { MessageBoxW(g_win, L"The server didn't answer.", L"Move server", MB_OK); return; }
        HANDLE f = CreateFileW(fn, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w = 0;
        if (f != INVALID_HANDLE_VALUE) { WriteFile(f, out, len, &w, NULL); CloseHandle(f); }
        free(out);
        wchar_t m[MAX_PATH + 300]; swprintf(m, MAX_PATH + 300, w == (DWORD)len ? L"Saved (%d MB):\n%ls\n\nOn the new device: start Rozefield Server, then Move server > No (import) and pick this file." : L"Couldn't write %d MB to\n%ls", len >> 20, fn);
        MessageBoxW(g_win, m, L"Move server", MB_OK);
    } else if (r == IDNO) {
        wchar_t fn[MAX_PATH] = L""; OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win;
        of.lpstrFilter = L"Server export (*.zip)\0*.zip\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH; of.Flags = OFN_FILEMUSTEXIST;
        if (!GetOpenFileNameW(&of)) return;
        HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE) { MessageBoxW(g_win, L"Couldn't open that file.", L"Move server", MB_OK); return; }
        DWORD sz = GetFileSize(f, NULL), got = 0; char *data = (char *)malloc(sz + 1); ReadFile(f, data, sz, &got, NULL); CloseHandle(f);
        int ok; wchar_t *res = host_call("POST", "/admin/host/import", data, (int)got, &ok); free(data);
        if (ok && MessageBoxW(g_win, res, L"Move server - restart now?", MB_YESNO | MB_ICONQUESTION) == IDYES) CloseHandle(CreateThread(NULL, 0, restart_thread, NULL, 0, NULL));
        else if (!ok) MessageBoxW(g_win, res, L"Move server", MB_OK | MB_ICONWARNING);
        free(res);
    }
}

static void do_package(void) {
    char *out; if (!http("GET", "/admin/host/package", "", 0, &out)) { MessageBoxW(g_win, L"The server didn't answer.", L"Game package", MB_OK); return; }
    char st[32] = "", file[MAX_PATH] = "", err[300] = ""; long long done = 0, total = 0;
    { char *f[5] = {0}; int k = 0; char *q = out; while (k < 5) { f[k++] = q; char *bar = strchr(q, '|'); if (!bar) break; *bar = 0; q = bar + 1; }
      if (k == 5) { snprintf(st, sizeof st, "%s", f[0]); done = atoll(f[1]); total = atoll(f[2]); snprintf(file, sizeof file, "%s", f[3]); snprintf(err, sizeof err, "%s", f[4]); } }
    free(out);
    wchar_t m[1200];
    if (!strcmp(st, "building")) { swprintf(m, 1200, L"Building Rozefield.zip: %d%% (%lld of %lld MB).", total ? (int)(done * 100 / total) : 0, done >> 20, total >> 20); MessageBoxW(g_win, m, L"Game package", MB_OK); return; }
    if (!strcmp(st, "done")) swprintf(m, 1200, L"Ready: %hs\n\nPlayers download it from this server's page (http://<server name>/) or from your Drive link.\n\nBuild it again now (after a game update)?", file);
    else if (!strcmp(st, "failed")) swprintf(m, 1200, L"The last build failed: %hs\n\nTry again?", err);
    else wcscpy(m, L"Build Rozefield.zip for players: the Overfield game folder next to the Server folder, with this server set as the default.\n\nIt can take a few minutes (several GB). Build now?");
    if (MessageBoxW(g_win, m, L"Game package", MB_YESNO | MB_ICONQUESTION) != IDYES) return;
    int ok; wchar_t *r = host_call("POST", "/admin/host/package", "", 0, &ok);
    MessageBoxW(g_win, ok ? L"Building in the background. Press Game package again to see how far it is." : r, L"Game package", MB_OK | (ok ? MB_ICONINFORMATION : MB_ICONWARNING)); free(r);
}

static void do_action(int a) {
    struct pl *p = sel(); char b[8192]; int ok; wchar_t *r;
    if (a >= A_FIRST && a < A_LAST && !p) { MessageBoxW(g_win, L"Choose a player in the list first.", L"Rozefield Server", MB_OK); return; }
    wchar_t who[120]; if (p) swprintf(who, 120, L"%ls (UID %d)", p->name, p->label);
    switch (a) {
    case B_CONNECT: do_connect(); break;
    case B_HOSTING: do_hosting(); break;
    case B_IMPORTS: do_imports(); break;
    case B_MOVE: do_move(); break;
    case B_PACKAGE: do_package(); break;
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
    case 6: {   /* the selected player's own lines: the server tags them [Name] */
        struct pl *p = (g_sel >= 0 && g_sel < g_npl) ? &g_pl[g_sel] : NULL;
        if (!p) return 0;
        wchar_t tag[80]; swprintf(tag, 80, L"[%ls]", p->name);
        wchar_t num[24]; swprintf(num, 24, L"%d", p->pid);
        return wcsstr(l, tag) || wcsstr(l, num) || (wcsstr(l, L"[chat]") && wcsstr(l, p->name)); }
    }
    return 1;
}
/* colour by kind: errors red, admin green, logins yellow, a player's own lines blue */
enum { K_OTHER, K_ERR, K_ADMIN, K_LOGIN, K_PLAYER };
static int line_kind(const wchar_t *l) {
    if (wcsstr(l, L"WARNING") || wcsstr(l, L"ERROR") || wcsstr(l, L"Traceback") || wcsstr(l, L"failed") || wcsstr(l, L"refused") || wcsstr(l, L"rror")) return K_ERR;
    if (wcsstr(l, L"[admin]") || wcsstr(l, L"[panel]")) return K_ADMIN;
    if (wcsstr(l, L"login") || wcsstr(l, L"gate connection") || wcsstr(l, L"logged in") || wcsstr(l, L"imported") || wcsstr(l, L"/rozefield/register")) return K_LOGIN;
    const wchar_t *b = wcschr(l, L' ');   /* "HH:MM:SS [Name] <- ..." */
    if (b && b[1] == L'[' || wcsstr(l, L"[chat]")) return K_PLAYER;
    return K_OTHER;
}
static void rtf_put(char **t, size_t *len, size_t *cap, const char *s) {
    size_t n = strlen(s); if (*len + n + 1 >= *cap) { *cap = (*len + n + 1) * 2; *t = (char *)realloc(*t, *cap); }
    memcpy(*t + *len, s, n + 1); *len += n;
}
static void rebuild_log(void) {
    EnterCriticalSection(&g_cs);
    size_t rcap = 1 << 17, rlen = 0; char *rtf = (char *)malloc(rcap); rtf[0] = 0;
    rtf_put(&rtf, &rlen, &rcap, "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Cascadia Mono;}}"
            "{\\colortbl;\\red60\\green64\\blue78;\\red200\\green40\\blue50;\\red28\\green136\\blue64;\\red176\\green124\\blue0;\\red30\\green96\\blue200;}"
            "\\f0\\fs18\\sa60 ");
    size_t cap = 1 << 16, len = 0; wchar_t *t = (wchar_t *)malloc(cap * sizeof(wchar_t)); t[0] = 0;
    int from = g_nlines > 1500 ? g_nlines - 1500 : 0;
    for (int i = from; i < g_nlines; i++) {
        if (!line_matches(g_lines[i])) continue;
        { char c[16]; snprintf(c, sizeof c, "\\cf%d ", 1 + line_kind(g_lines[i])); rtf_put(&rtf, &rlen, &rcap, c);
          for (const wchar_t *q = g_lines[i]; *q; q++) {
              char e[16];
              if (*q == L'\\' || *q == L'{' || *q == L'}') snprintf(e, sizeof e, "\\%c", (char)*q);
              else if (*q < 128) { e[0] = (char)*q; e[1] = 0; }
              else snprintf(e, sizeof e, "\\u%d?", (int)(short)*q);
              rtf_put(&rtf, &rlen, &rcap, e);
          }
          rtf_put(&rtf, &rlen, &rcap, "\\par "); }
        size_t n = wcslen(g_lines[i]);
        if (len + n + 3 >= cap) { cap = (len + n + 3) * 2; t = (wchar_t *)realloc(t, cap * sizeof(wchar_t)); }
        memcpy(t + len, g_lines[i], n * sizeof(wchar_t)); len += n; t[len++] = L'\r'; t[len++] = L'\n'; t[len] = 0;
    }
    g_lines_dirty = 0;
    LeaveCriticalSection(&g_cs);
    SCROLLINFO si = {sizeof si, SIF_ALL}; GetScrollInfo(g_logv, SB_VERT, &si);
    int at_end = g_follow || si.nMax <= 0 || si.nPos + (int)si.nPage >= si.nMax - 2;
    int first = (int)SendMessageW(g_logv, EM_GETFIRSTVISIBLELINE, 0, 0);
    SendMessageW(g_logv, WM_SETREDRAW, FALSE, 0);
    rtf_put(&rtf, &rlen, &rcap, "}");
    SETTEXTEX stx = {ST_DEFAULT, CP_ACP}; SendMessageW(g_logv, EM_SETTEXTEX, (WPARAM)&stx, (LPARAM)rtf); free(rtf);
    len = (size_t)GetWindowTextLengthW(g_logv);
    if (at_end) { SendMessageW(g_logv, EM_SETSEL, (WPARAM)len, (LPARAM)len); SendMessageW(g_logv, EM_SCROLLCARET, 0, 0); }
    else SendMessageW(g_logv, EM_LINESCROLL, 0, first);   /* the reader scrolled up: stay where they are */
    SendMessageW(g_logv, WM_SETREDRAW, TRUE, 0);
    if (at_end) SendMessageW(g_logv, WM_VSCROLL, SB_BOTTOM, 0);
    g_follow = 0;
    InvalidateRect(g_logv, NULL, TRUE);
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
    if (kind == 1) fill(dc, r, !enabled ? RGB(166, 216, 222) : hover ? RGB(14, 160, 176) : C_ACC, rad);
    else { fill(dc, r, hover && enabled ? RGB(232, 246, 248) : C_PANEL, rad); outline(dc, r, kind == 2 && enabled ? RGB(230, 150, 156) : C_LINE, rad); }
    txt(dc, kind == 1 ? f_btn : f_small, kind == 1 ? RGB(255, 255, 255) : !enabled ? RGB(170, 174, 186) : kind == 2 ? C_BAD : C_TXT, r, label, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static void fmt_bytes(long long v, wchar_t *o, int per_sec) {
    const wchar_t *u = per_sec ? L"/s" : L"";
    if (v < 1024) swprintf(o, 40, L"%lld B%ls", v, u);
    else if (v < 1024 * 1024) swprintf(o, 40, L"%.1f KB%ls", v / 1024.0, u);
    else if (v < 1024LL * 1024 * 1024) swprintf(o, 40, L"%.1f MB%ls", v / 1048576.0, u);
    else swprintf(o, 40, L"%.2f GB%ls", v / 1073741824.0, u);
}
static void paint(HWND h) {
    PAINTSTRUCT ps; HDC wdc = BeginPaint(h, &ps);
    HDC dc = CreateCompatibleDC(wdc); HBITMAP bb = CreateCompatibleBitmap(wdc, WW, WH); HGDIOBJ ob = SelectObject(dc, bb);
    RECT all = {0, 0, WW, WH}; fill(dc, all, C_INK, 0);
    /* sidebar: the chosen player's actions, then folders */
    RECT rail = {0, 0, SB, WH}; fill(dc, rail, C_PANEL, 0); { RECT ln = {SB - 1, 0, SB, WH}; fill(dc, ln, C_LINE, 0); }
    dot(dc, 34, 40, 16, C_ACC); RECT rl = {18, 24, 50, 56}; txt(dc, f_h, RGB(255, 255, 255), rl, L"R", DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    RECT rn0 = {58, 26, SB - 8, 54}; txt(dc, f_h, C_TXT, rn0, L"Rozefield", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    struct pl *p = sel();
    { wchar_t cap[120]; if (p) swprintf(cap, 120, L"Player: %ls", p->name); else wcscpy(cap, L"Choose a player");
      RECT rc = {20, 82, SB - 10, 102}; txt(dc, f_small, p ? C_TXT : C_MUTE, rc, cap, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS); }
    static const wchar_t *ICONS[] = {L"\xE192", L"\xE785", L"\xE70F", L"\xE756", L"\xE715", L"\xE8BD", L"\xE7E8", L"\xE733", L"\xE74F", L"\xE77B"};
    for (int i = 0; i < 10; i++) {
        const wchar_t *lb = ACT_LABEL[i]; int danger = 0, en = p != NULL;
        if (i == A_BAN - A_FIRST) { lb = p && p->banned ? L"Unban" : L"Ban"; danger = 1; }
        if (i == A_MUTE - A_FIRST) lb = p && p->muted ? L"Unmute" : L"Mute";
        if (i == A_KICK - A_FIRST) { danger = 1; en = p && p->online; }
        if (i == A_GM - A_FIRST) en = p && p->online;
        if (i == A_RECLAIM - A_FIRST) en = p && !p->official;
        en = en && g_up;
        RECT r = r_act[i]; if (en && g_hover == A_FIRST + i) fill(dc, r, RGB(232, 246, 248), 10);
        COLORREF c = !en ? RGB(186, 189, 200) : danger ? C_BAD : C_TXT;
        RECT ri = {r.left + 10, r.top, r.left + 34, r.bottom}; txt(dc, f_icon, c, ri, ICONS[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT rt2 = {r.left + 38, r.top, r.right - 6, r.bottom}; txt(dc, f_body, c, rt2, lb, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    }
    { RECT rs2[] = {r_savedir, r_logfile}; const wchar_t *lab[] = {L"Save folder", L"Log file"}, *ic[] = {L"\xE8B7", L"\xE8A5"}; int hv[] = {B_SAVEDIR, B_LOGFILE};
      for (int i = 0; i < 2; i++) { RECT r = rs2[i]; if (g_hover == hv[i]) fill(dc, r, C_TILE, 10);
          RECT ri = {r.left + 10, r.top, r.left + 34, r.bottom}; txt(dc, f_icon, C_MUTE, ri, ic[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE);
          RECT rt2 = {r.left + 38, r.top, r.right, r.bottom}; txt(dc, f_body, C_MUTE, rt2, lab[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE); } }
    if (g_hover == B_CLOSE) fill(dc, r_close, RGB(200, 64, 76), 8);
    if (g_hover == B_MIN) fill(dc, r_min, C_TILE, 8);
    { HPEN p = CreatePen(PS_SOLID, 2, C_TXT); HGDIOBJ o = SelectObject(dc, p);
      int cx = (r_close.left + r_close.right) / 2, cy = (r_close.top + r_close.bottom) / 2;
      MoveToEx(dc, cx - 6, cy - 6, NULL); LineTo(dc, cx + 7, cy + 7); MoveToEx(dc, cx + 6, cy - 6, NULL); LineTo(dc, cx - 7, cy + 7);
      cx = (r_min.left + r_min.right) / 2; MoveToEx(dc, cx - 7, cy, NULL); LineTo(dc, cx + 8, cy); SelectObject(dc, o); DeleteObject(p); }

    RECT rt = {X0, 22, 600, 64}; txt(dc, f_title, C_TXT, rt, L"Rozefield Server", DT_LEFT | DT_SINGLELINE);
    int online = 0; for (int i = 0; i < g_npl; i++) online += g_pl[i].online;
    wchar_t st[480];
    if (g_up) swprintf(st, 160, L"Running  \x00B7  %d online  \x00B7  %d accounts%ls", online, g_npl, g_proc ? L"" : L"  \x00B7  started outside this window");
    else wcscpy(st, g_starting ? L"Starting\x2026" : g_remote ? L"Not reachable" : L"Stopped");
    if (g_remote) { wchar_t c[300]; swprintf(c, 300, L"  \x00B7  connected to %hs", g_host); wcscat(st, c); }
    dot(dc, X0 + 8, 79, 5, g_up ? C_OK : g_starting ? C_WARN : C_BAD);
    RECT rs = {X0 + 20, 68, WW - 40, 92}; txt(dc, f_small, g_up ? C_OK : C_MUTE, rs, st, DT_LEFT | DT_VCENTER | DT_SINGLELINE);

    /* players panel */
    RECT pp = {X0, 106, X0 + 380, 400}; fill(dc, pp, C_PANEL, 18); outline(dc, pp, C_LINE, 18);
    RECT ph = {X0 + 16, 116, X0 + 120, 140}; txt(dc, f_h, C_TXT, ph, L"Players", DT_LEFT | DT_SINGLELINE);
    /* traffic */
    { RECT tc = {X0, 414, X0 + 380, WH - 92}; fill(dc, tc, C_PANEL, 18); outline(dc, tc, C_LINE, 18);
      RECT th = {X0 + 16, 422, X0 + 200, 446}; txt(dc, f_h, C_TXT, th, L"Traffic", DT_LEFT | DT_SINGLELINE);
      RECT tl = {X0 + 200, 424, X0 + 364, 446}; txt(dc, f_small, C_MUTE, tl, L"last 10 minutes", DT_RIGHT | DT_SINGLELINE);
      RECT gr = {X0 + 16, 452, X0 + 364, 522}; fill(dc, gr, RGB(248, 249, 251), 8);
      int mx = 1024; for (int i = 0; i < t_nhist; i++) { if (t_hist[i][0] > mx) mx = t_hist[i][0]; if (t_hist[i][1] > mx) mx = t_hist[i][1]; }
      for (int k = 0; k < 2 && t_nhist > 1; k++) {
          HPEN pen = CreatePen(k ? PS_DOT : PS_SOLID, k ? 1 : 2, k ? RGB(230, 0, 110) : C_ACC); HGDIOBJ o = SelectObject(dc, pen);
          for (int i = 0; i < t_nhist; i++) {
              int x = gr.left + 4 + (gr.right - gr.left - 8) * i / (t_nhist - 1), y = gr.bottom - 4 - (int)((long long)(gr.bottom - gr.top - 8) * t_hist[i][k] / mx);
              if (i) LineTo(dc, x, y); else MoveToEx(dc, x, y, NULL);
          }
          SelectObject(dc, o); DeleteObject(pen);
      }
      wchar_t a[40], b[40], c2[40], d[40], m[160];
      fmt_bytes(t_down, a, 1); fmt_bytes(t_up, b, 1); fmt_bytes(t_today, c2, 0); fmt_bytes(mx, d, 1);
      swprintf(m, 160, L"\x2014 to players   \x00B7\x00B7 from players   (top: %ls)", d);
      RECT lg = {X0 + 16, 524, X0 + 364, 542}; txt(dc, f_small, C_MUTE, lg, m, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
      const wchar_t *tn[] = {L"Down", L"Up", L"Msgs/s", L"Today"}; wchar_t tv[4][40]; wcscpy(tv[0], a); wcscpy(tv[1], b); swprintf(tv[2], 40, L"%lld", t_msgs); wcscpy(tv[3], c2);
      for (int i = 0; i < 4; i++) { RECT r = {X0 + 16 + i * 88, 546, X0 + 98 + i * 88, 588}; fill(dc, r, C_TILE, 8);
          RECT r1 = {r.left + 8, r.top + 3, r.right - 4, r.top + 20}; txt(dc, f_small, C_MUTE, r1, tn[i], DT_LEFT | DT_SINGLELINE);
          RECT r2 = {r.left + 8, r.top + 20, r.right - 4, r.bottom - 2}; txt(dc, f_body, C_TXT, r2, tv[i], DT_LEFT | DT_SINGLELINE); }
      int y = 594;
      for (int i = 0; i < t_npl && y < WH - 120; i++, y += 20) {
          wchar_t r1[40], r2[40], line[160]; fmt_bytes(t_pl[i].down, r1, 1); fmt_bytes(t_pl[i].up, r2, 1);
          swprintf(line, 160, L"%ls \x2193  %ls \x2191  \x00B7  %lld msgs/s", r1, r2, t_pl[i].msgs);
          RECT ra = {X0 + 16, y, X0 + 150, y + 20}; txt(dc, f_small, C_TXT, ra, t_pl[i].name, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
          RECT rb = {X0 + 150, y, X0 + 364, y + 20}; txt(dc, f_small, C_MUTE, rb, line, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
      }
      { wchar_t r1[40], line[120]; fmt_bytes(t_dl, r1, 1); swprintf(line, 120, L"%ls", r1);
        RECT ra = {X0 + 16, y, X0 + 220, y + 20}; txt(dc, f_small, C_TXT, ra, L"Downloads (updates, game zip)", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT rb = {X0 + 220, y, X0 + 364, y + 20}; txt(dc, f_small, C_MUTE, rb, line, DT_RIGHT | DT_VCENTER | DT_SINGLELINE); } }
    /* log panel: tall, beside players and traffic */
    RECT lp = {X0 + 396, 106, WW - 24, WH - 92}; fill(dc, lp, C_PANEL, 18); outline(dc, lp, C_LINE, 18);
    RECT lh = {X0 + 412, 116, X0 + 560, 140}; txt(dc, f_h, C_TXT, lh, L"Live log", DT_LEFT | DT_SINGLELINE);
    { const wchar_t *kl[] = {L"Login", L"Error", L"Admin", L"Player"}; COLORREF kc[] = {RGB(176, 124, 0), RGB(200, 40, 50), RGB(28, 136, 64), RGB(30, 96, 200)};
      int x = X0 + 412; for (int i = 0; i < 4; i++) { dot(dc, x + 4, 188 - 4 + 4, 4, kc[i]); RECT r = {x + 12, 180, x + 70, 196}; txt(dc, f_small, kc[i], r, kl[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE); x += 66; } }
    for (int i = 0; i < NFILT; i++) {
        RECT r = r_filt[i];
        if (i == g_filter) fill(dc, r, C_ACC, 12); else { fill(dc, r, g_hover == F_FIRST + i ? RGB(220, 240, 243) : C_TILE, 12); }
        txt(dc, f_small, i == g_filter ? RGB(255, 255, 255) : C_TXT, r, FILTERS[i], DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    /* bottom bar */
    RECT bar = {SB, WH - 84, WW, WH}; fill(dc, bar, C_PANEL, 0); { RECT ln = {SB, WH - 84, WW, WH - 83}; fill(dc, ln, C_LINE, 0); }
    pill(dc, r_import, 0, g_hover == B_IMPORT, g_up, L"Import backup");
    pill(dc, r_mailall, 0, g_hover == B_MAILALL, g_up, L"Mail everyone");
    pill(dc, r_connect, 0, g_hover == B_CONNECT, 1, g_remote ? L"Connect (other device)" : L"Connect\x2026");
    pill(dc, r_hosting, 0, g_hover == B_HOSTING, g_up, L"Hosting");
    pill(dc, r_imports, 0, g_hover == B_IMPORTS, g_up, L"Imports");
    pill(dc, r_move, 0, g_hover == B_MOVE, g_up, L"Move server");
    pill(dc, r_package, 0, g_hover == B_PACKAGE, g_up, L"Game package");
    pill(dc, r_start, 1, g_hover == B_START, !g_up && !g_starting && !g_remote, L"Start");
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
    if (PtInRect(&r_connect, pt)) return B_CONNECT;
    if (PtInRect(&r_hosting, pt)) return B_HOSTING;
    if (PtInRect(&r_imports, pt)) return B_IMPORTS;
    if (PtInRect(&r_move, pt)) return B_MOVE;
    if (PtInRect(&r_package, pt)) return B_PACKAGE;
    for (int i = 0; i < 10; i++) if (PtInRect(&r_act[i], pt)) return A_FIRST + i;
    for (int i = 0; i < NFILT; i++) if (PtInRect(&r_filt[i], pt)) return F_FIRST + i;
    return B_NONE;
}

static void click(int b) {
    char p[MAX_PATH + 16];
    switch (b) {
    case B_CLOSE: PostMessageW(g_win, WM_CLOSE, 0, 0); return;
    case B_MIN: ShowWindow(g_win, SW_HIDE); return;   /* to the tray: the server keeps running */
    case B_CONNECT: do_action(B_CONNECT); break;
    case B_START: if (!g_up) start_server(); break;
    case B_STOP: if (g_up && MessageBoxW(g_win, L"Stop the server? Everyone online is disconnected.", L"Rozefield Server", MB_YESNO | MB_ICONQUESTION) == IDYES) stop_server(); break;
    case B_RESTART: if (g_up) CloseHandle(CreateThread(NULL, 0, restart_thread, NULL, 0, NULL)); break;
    case B_SAVEDIR: snprintf(p, sizeof p, "%ssave\\accounts", g_dir); ShellExecuteA(NULL, "open", p, NULL, NULL, SW_SHOWNORMAL); break;
    case B_LOGFILE: snprintf(p, sizeof p, "%sserver.log", g_dir); ShellExecuteA(NULL, "open", p, NULL, NULL, SW_SHOWNORMAL); break;
    default:
        if (b >= F_FIRST && b < F_FIRST + NFILT) { g_filter = b - F_FIRST; g_follow = 1; rebuild_log(); }
        else if ((b >= A_FIRST && b < A_LAST) || b == B_IMPORT || b == B_MAILALL || (b >= B_HOSTING && b <= B_PACKAGE)) { if (g_up) do_action(b); }
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
        SetTextColor((HDC)w, (HWND)l == g_logv ? RGB(60, 64, 78) : C_TXT); SetBkColor((HDC)w, (HWND)l == g_logv ? C_PANEL : C_FIELD);
        return (LRESULT)((HWND)l == g_logv ? br_panel : br_field);
    case WM_CTLCOLORLISTBOX: SetBkColor((HDC)w, C_PANEL); return (LRESULT)br_panel;
    case WM_MEASUREITEM: ((MEASUREITEMSTRUCT *)l)->itemHeight = 40; return TRUE;
    case WM_DRAWITEM: {
        DRAWITEMSTRUCT *d = (DRAWITEMSTRUCT *)l;
        if (d->itemID == (UINT)-1) return TRUE;
        int i = (int)SendMessageW(g_list, LB_GETITEMDATA, d->itemID, 0); if (i < 0 || i >= g_npl) return TRUE;
        struct pl *p = &g_pl[i]; RECT r = d->rcItem;
        fill(d->hDC, r, C_PANEL, 0);
        if (d->itemState & ODS_SELECTED) { RECT s = {r.left + 2, r.top + 2, r.right - 2, r.bottom - 2}; fill(d->hDC, s, RGB(214, 242, 246), 12); }
        dot(d->hDC, r.left + 18, (r.top + r.bottom) / 2, 5, p->banned ? C_BAD : p->online ? C_OK : RGB(190, 194, 206));
        RECT rn = {r.left + 34, r.top + 3, r.right - 110, r.top + 22}; txt(d->hDC, f_body, p->banned ? C_BAD : C_TXT, rn, p->name, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
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
            if (g_filter == 6) { g_follow = 1; rebuild_log(); }
        } else if ((HWND)l == g_find && HIWORD(w) == EN_CHANGE) fill_list();
        else if ((HWND)l == g_search && HIWORD(w) == EN_CHANGE) rebuild_log();
        return 0;
    case WM_DATA:
        if (w) fill_list();
        if (g_lines_dirty) rebuild_log();
        InvalidateRect(h, NULL, FALSE); return 0;
    case WM_NCHITTEST: {
        LRESULT r = DefWindowProcW(h, m, w, l);
        if (r == HTCLIENT) { POINT pt = {(short)LOWORD(l), (short)HIWORD(l)}; ScreenToClient(h, &pt); if (pt.y < 100 && pt.x > SB && hit(pt.x, pt.y) == B_NONE) return HTCAPTION; }
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
    case WM_TRAY:
        if (l == WM_LBUTTONUP || l == WM_LBUTTONDBLCLK) { ShowWindow(h, SW_SHOW); ShowWindow(h, SW_RESTORE); SetForegroundWindow(h); }
        return 0;
    case WM_DESTROY: Shell_NotifyIconW(NIM_DELETE, &g_tray); PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

/* The Rozefield copy keeps its Unity window settings under its own name (app.info = Rozefield), so it started with
 * defaults: wrong monitor / fullscreen mode / refresh, which flickers on a second screen. Copy the window and quality
 * settings from the official copy (HKCU\\Software\\Inutan\\OverField) every start, so both behave the same. */
static int sync_screen_prefs(void) {
    HKEY src, dst; int n = 0;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Inutan\\OverField", 0, KEY_READ, &src) != ERROR_SUCCESS) return 0;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\Rozefield\\Rozefield", 0, NULL, 0, KEY_WRITE, NULL, &dst, NULL) != ERROR_SUCCESS) { RegCloseKey(src); return 0; }
    for (DWORD i = 0;; i++) {
        wchar_t name[512]; DWORD nl = 512, type, dl = 0;
        if (RegEnumValueW(src, i, name, &nl, NULL, &type, NULL, &dl) != ERROR_SUCCESS) break;
        if (wcsncmp(name, L"Screenmanager", 13) && wcsncmp(name, L"UnitySelectMonitor", 18) && wcsncmp(name, L"UnityGraphicsQuality", 20)) continue;
        BYTE *data = (BYTE *)malloc(dl + 2); DWORD dl2 = dl; nl = 512;
        if (RegEnumValueW(src, i, name, &nl, NULL, &type, data, &dl2) == ERROR_SUCCESS && RegSetValueExW(dst, name, 0, type, data, dl2) == ERROR_SUCCESS) n++;
        free(data);
    }
    RegCloseKey(src); RegCloseKey(dst);
    return n;
}
int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    /* one panel only: a second start brings the open one to the front (also when it is in the tray) */
    CreateMutexW(NULL, TRUE, L"Local\\RozefieldServerPanel");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        HWND w = FindWindowW(L"RozefieldServerPanel", NULL);
        if (w) { ShowWindow(w, SW_RESTORE); SetForegroundWindow(w); }
        return 0;
    }
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
    for (int i = 0; i < 10; i++) r_act[i] = (RECT){10, 108 + i * 36, SB - 10, 140 + i * 36};
    for (int i = 0; i < NFILT; i++) r_filt[i] = (RECT){X0 + 412 + i * 68, 148, X0 + 474 + i * 68, 174};
    f_icon = CreateFontW(-16, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe MDL2 Assets");
    LoadLibraryW(L"Msftedit.dll");

    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = hi; wc.lpszClassName = L"RozefieldServerPanel";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW); wc.hIcon = LoadIcon(NULL, IDI_APPLICATION); RegisterClassW(&wc);
    WNDCLASSW dc = {0}; dc.lpfnWndProc = DlgProc; dc.hInstance = hi; dc.lpszClassName = L"RzDlg"; dc.hCursor = LoadCursor(NULL, IDC_ARROW); RegisterClassW(&dc);
    g_win = CreateWindowExW(WS_EX_APPWINDOW, L"RozefieldServerPanel", L"Rozefield Server", WS_POPUP | WS_MINIMIZEBOX | WS_SYSMENU | WS_CLIPCHILDREN,
                            (GetSystemMetrics(SM_CXSCREEN) - WW) / 2, (GetSystemMetrics(SM_CYSCREEN) - WH) / 2, WW, WH, NULL, NULL, hi, NULL);
    SetWindowRgn(g_win, CreateRoundRectRgn(0, 0, WW + 1, WH + 1, 16, 16), TRUE);
    g_find = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, X0 + 130, 114, 234, 26, g_win, NULL, hi, NULL);
    SendMessageW(g_find, EM_SETCUEBANNER, TRUE, (LPARAM)L"Find name or UID");
    g_list = CreateWindowExW(0, L"LISTBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_OWNERDRAWFIXED | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
                             X0 + 12, 150, 356, 240, g_win, NULL, hi, NULL);
    g_search = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, WW - 214, 113, 172, 28, g_win, NULL, hi, NULL);
    SendMessageW(g_search, EM_SETCUEBANNER, TRUE, (LPARAM)L"Search the log");
    g_logv = CreateWindowExW(0, MSFTEDIT_CLASS, L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
                             X0 + 408, 204, WW - 24 - 12 - (X0 + 408), WH - 92 - 12 - 204, g_win, NULL, hi, NULL);
    SendMessageW(g_logv, EM_EXLIMITTEXT, 0, 0x7FFFFFFF); SendMessageW(g_logv, EM_SETBKGNDCOLOR, 0, C_PANEL);
    SendMessageW(g_find, WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(g_search, WM_SETFONT, (WPARAM)f_body, TRUE);
    SendMessageW(g_logv, WM_SETFONT, (WPARAM)f_mono, TRUE);
    SendMessageW(g_find, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6)); SendMessageW(g_search, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6));
    g_bg = strstr(cmd, "--background") != NULL;
    g_tray.cbSize = sizeof g_tray; g_tray.hWnd = g_win; g_tray.uID = 1; g_tray.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    g_tray.uCallbackMessage = WM_TRAY; g_tray.hIcon = LoadIconW(hi, MAKEINTRESOURCEW(1)); if (!g_tray.hIcon) g_tray.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wcscpy(g_tray.szTip, L"Rozefield Server - click to open"); Shell_NotifyIconW(NIM_ADD, &g_tray);
    if (!g_bg) { ShowWindow(g_win, show); UpdateWindow(g_win); }
    load_conn();
    note(L"Rozefield Server panel opened.");
    { int n = sync_screen_prefs(); wchar_t m[160];
      swprintf(m, 160, n ? L"Window settings copied from your official game (%d) - same screen, mode and refresh." : L"No official window settings found to copy.", n); note(m); }
    if (!g_remote) read_token(); else note(L"Connected to %hs (Connect to change).", g_host);
    CloseHandle(CreateThread(NULL, 0, poller, NULL, 0, NULL));
    Sleep(900);
    if (!g_up && !strstr(cmd, "--no-start")) start_server();   /* opening the panel starts the server */
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return 0;
}
