/* Rozefield SDK stub — drop-in replacement for OverField's PCSDKUI.exe (QuickSDK PC login window).
 * The game starts PCSDKUI.exe with "gameName||qgpc&action||callLogin&url||..." and listens on
 * \\.\pipe\quickpc<gameName>. The real SDK opens a web login and then writes one JSON message per pipe
 * connection. This stub skips the web page and immediately reports a successful login with the
 * name the player types in a small window; the name travels in the token, uid = "rz_<lower-case name>".
 * The window also picks the server (list, invite code / name / address, home-network search). Choosing a server
 * other than the one the game started with logs in there, points the game at it and restarts it, logged in.
 * Build: zig cc -target x86_64-windows-gnu -O2 pcsdkui_stub.c -o PCSDKUI.exe -lws2_32 -lcomdlg32 -luser32 -lgdi32 -Wl,--subsystem,windows */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <tlhelp32.h>
#include <commdlg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <ctype.h>

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
#define CH 640
#define OY 84   /* the server row sits above the tabs */
static RECT r_close = {CW - 44, 14, CW - 14, 44}, r_tab0 = {28, 70 + OY, 120, 100 + OY}, r_tab1 = {136, 70 + OY, 280, 100 + OY};
static RECT r_srv = {28, 84, CW - 104, 114}, r_add = {CW - 98, 84, CW - 64, 114}, r_find = {CW - 58, 84, CW - 28, 114};
static RECT r_rem = {28, 0, 220, 0}, r_import = {28, CH - 46, 176, CH - 22}, r_export = {184, CH - 46, 300, CH - 22}, r_forgot = {CW - 110, CH - 46, CW - 16, CH - 22};
static RECT r_chip[8];

/* ---- servers: the default from rozefield_servers.json, ones added here, ones found on the home network ----
 * The game reached a server before this window opened (Config.txt RemoteServerIP). Picking another one and
 * pressing Enter game logs in there, points the game at it and restarts the game, already logged in. */
struct srv { char name[96]; char addr[256]; };
static struct srv g_srv[48]; static int g_nsrv, g_cur;
static char g_game_ip[64];                 /* the server the running game is using */
static wchar_t g_stat[200]; static COLORREF g_statc = RGB(150, 155, 170);
static volatile LONG g_gen;
static void sanitize(char *k) { for (; *k; k++) if (*k == '=' || *k == '[' || *k == ']' || *k == ';') *k = '_'; }
static void str_after(const char *from, const char *key, char *out, int n) {
    out[0] = 0; char k[64]; snprintf(k, sizeof k, "\"%s\"", key); const char *p = strstr(from, k); if (!p) return;
    p = strchr(p + strlen(k), ':'); if (!p) return; p++; while (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t') p++;
    if (*p != '"') return; p++; int i = 0; while (*p && *p != '"' && i < n - 1) { if (*p == '\\' && p[1]) p++; out[i++] = *p++; } out[i] = 0;
}
static void add_srv(const char *name, const char *addr) {
    for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, addr)) return;
    if (g_nsrv >= 48 || !addr[0]) return;
    snprintf(g_srv[g_nsrv].name, 96, "%s", name[0] ? name : addr); snprintf(g_srv[g_nsrv].addr, 256, "%s", addr); g_nsrv++;
}
static const char B32[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
static int read_code(const char *s, char *ip) {   /* RZ-XXXX-XXX = IPv4 in base32 */
    if (toupper((unsigned char)s[0]) != 'R' || toupper((unsigned char)s[1]) != 'Z') return 0;
    unsigned long long v = 0; int n = 0;
    for (const char *p = s + 2; *p; p++) {
        if (*p == '-' || *p == ' ') continue;
        char ch = (char)toupper((unsigned char)*p); if (ch == 'O') ch = '0'; if (ch == 'I' || ch == 'L') ch = '1';
        const char *q = strchr(B32, ch); if (!q || !*q) return 0; v = (v << 5) | (unsigned)(q - B32); n++;
    }
    if (n != 7 || v > 0xFFFFFFFFull) return 0;
    sprintf(ip, "%u.%u.%u.%u", (unsigned)(v >> 24) & 255, (unsigned)(v >> 16) & 255, (unsigned)(v >> 8) & 255, (unsigned)v & 255); return 1;
}
static int resolve(const char *addr, char *ip) {
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    char a[256], c[64]; snprintf(a, sizeof a, "%s", addr); char *col = strchr(a, ':'); if (col) *col = 0;
    if (read_code(a, c)) { strcpy(ip, c); return 1; }
    struct addrinfo h = {0}, *r = NULL; h.ai_family = AF_INET; h.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(a, NULL, &h, &r) != 0 || !r) return 0;
    inet_ntop(AF_INET, &((struct sockaddr_in *)r->ai_addr)->sin_addr, ip, 64); freeaddrinfo(r); return 1;
}
static char *read_all(const char *path, DWORD *len) {
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL); if (f == INVALID_HANDLE_VALUE) return NULL;
    DWORD sz = GetFileSize(f, NULL), got = 0; char *b = (char *)malloc(sz + 1); ReadFile(f, b, sz, &got, NULL); CloseHandle(f); b[got] = 0; if (len) *len = got; return b;
}
static void load_servers(void) {
    char p[MAX_PATH], def[256] = ""; snprintf(p, sizeof p, "%srozefield_servers.json", g_dir);
    char *js = read_all(p, NULL);
    if (js) {
        str_after(js, "default", def, sizeof def);
        for (const char *q = js; (q = strstr(q, "\"address\"")) != NULL; q += 9) {
            const char *ob = q; while (ob > js && *ob != '{') ob--;
            char nm[96], ad[256]; str_after(ob, "name", nm, sizeof nm); str_after(ob, "address", ad, sizeof ad); add_srv(nm, ad);
        }
        free(js);
    }
    int n = GetPrivateProfileIntA("servers", "count", 0, g_ini);
    for (int i = 0; i < n; i++) { char k[16], v[400]; snprintf(k, sizeof k, "s%d", i); GetPrivateProfileStringA("servers", k, "", v, sizeof v, g_ini);
                                  char *bar = strchr(v, '|'); if (bar) { *bar = 0; add_srv(v, bar + 1); } }
    /* the running game's server (Config.txt) */
    char cfg[MAX_PATH]; snprintf(cfg, sizeof cfg, "%slauncher_Data\\StreamingAssets\\Config.txt", g_dir);
    char *t = read_all(cfg, NULL); g_game_ip[0] = 0;
    if (t) { char *q = strstr(t, "RemoteServerIP"); if (q && (q = strchr(q, '='))) { q++; while (*q == ' ') q++; int i = 0; while (*q && *q != '\r' && *q != '\n' && *q != ' ' && i < 63) g_game_ip[i++] = *q++; g_game_ip[i] = 0; }
             if (!strstr(t, "UseCustomConfig = TRUE") && !strstr(t, "UseCustomConfig=TRUE")) g_game_ip[0] = 0; free(t); }
    if (!g_nsrv) add_srv("This PC", g_game_ip[0] ? g_game_ip : g_host);
    char last[256]; GetPrivateProfileStringA("server", "address", def[0] ? def : g_srv[0].addr, last, sizeof last, g_ini);
    g_cur = 0; for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, last)) g_cur = i;
}
static void save_servers(void) {
    char k[16], v[400]; int n = 0; WritePrivateProfileStringA("servers", NULL, NULL, g_ini);
    for (int i = 0; i < g_nsrv; i++) { snprintf(k, sizeof k, "s%d", n++); snprintf(v, sizeof v, "%s|%s", g_srv[i].name, g_srv[i].addr); WritePrivateProfileStringA("servers", k, v, g_ini); }
    snprintf(v, sizeof v, "%d", n); WritePrivateProfileStringA("servers", "count", v, g_ini);
    WritePrivateProfileStringA("server", "address", g_srv[g_cur].addr, g_ini);
}

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

static void saved_key(char *k, int n) { snprintf(k, n, "saved_%s", g_srv[g_cur].addr); sanitize(k + 6); }
static void load_saved(void) {
    char buf[1024], k[300]; saved_key(k, sizeof k); GetPrivateProfileStringA("account", k, "", buf, sizeof buf, g_ini);
    if (!buf[0] && g_cur == 0) GetPrivateProfileStringA("account", "saved", "", buf, sizeof buf, g_ini);   /* names saved before servers existed */
    g_nsaved = 0;
    for (char *t = strtok(buf, "|"); t && g_nsaved < 8; t = strtok(NULL, "|")) snprintf(g_saved[g_nsaved++], 128, "%s", t);
}
static void remember_name(const char *nm) {
    char buf[1100] = ""; int has = 0;
    for (int i = 0; i < g_nsaved; i++) if (_stricmp(g_saved[i], nm) == 0) has = 1;
    snprintf(buf, sizeof buf, "%s", nm);
    for (int i = 0; i < g_nsaved && i < 7; i++) if (_stricmp(g_saved[i], nm) != 0) { strcat(buf, "|"); strcat(buf, g_saved[i]); }
    (void)has;
    char k[300]; saved_key(k, sizeof k); WritePrivateProfileStringA("account", k, buf, g_ini);
}

static void layout(void) {
    int y = 122 + OY;
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
    /* server row */
    text(dc, g_fsmall, C_MUTED, 28, 64, L"Server");
    { HBRUSH fb = CreateSolidBrush(C_FIELD); RECT rr[] = {r_srv, r_add, r_find};
      for (int i = 0; i < 3; i++) { HRGN rg = CreateRoundRectRgn(rr[i].left, rr[i].top, rr[i].right + 1, rr[i].bottom + 1, 8, 8); FillRgn(dc, rg, fb); DeleteObject(rg); }
      DeleteObject(fb);
      wchar_t w[200]; char t[400];
      if (!strcmp(g_srv[g_cur].name, g_srv[g_cur].addr)) snprintf(t, sizeof t, "%s", g_srv[g_cur].name); else snprintf(t, sizeof t, "%s  \xC2\xB7  %s", g_srv[g_cur].name, g_srv[g_cur].addr);
      MultiByteToWideChar(CP_UTF8, 0, t, -1, w, 200);
      RECT tr = {r_srv.left + 10, r_srv.top, r_srv.right - 26, r_srv.bottom};
      SelectObject(dc, g_fsmall); SetTextColor(dc, C_TEXT); SetBkMode(dc, TRANSPARENT); DrawTextW(dc, w, -1, &tr, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
      text(dc, g_fsmall, C_MUTED, r_srv.right - 20, r_srv.top + 6, L"\x25BE");
      text(dc, g_fbody, C_TEXT, r_add.left + 11, r_add.top + 3, L"+");
      text(dc, g_fsmall, C_TEXT, r_find.left + 6, r_find.top + 6, L"\x2315"); }
    { HBRUSH db = CreateSolidBrush(g_statc); RECT dot = {28, 125, 36, 133}; HRGN rg = CreateEllipticRgn(dot.left, dot.top, dot.right, dot.bottom); FillRgn(dc, rg, db); DeleteObject(rg); DeleteObject(db);
      text(dc, g_fsmall, g_statc, 42, 120, g_stat); }
    text(dc, g_fbody, g_tab ? C_MUTED : C_TEXT, 28, 74 + OY, L"Log in");
    text(dc, g_fbody, g_tab ? C_TEXT : C_MUTED, 136, 74 + OY, L"Create account");
    HBRUSH acc = CreateSolidBrush(C_ACCENT);
    RECT ul = g_tab ? (RECT){136, 98 + OY, 254, 100 + OY} : (RECT){28, 98 + OY, 76, 100 + OY}; FillRect(dc, &ul, acc);
    HBRUSH line = CreateSolidBrush(RGB(48, 52, 64)); RECT ln = {28, 100 + OY, CW - 28, 101 + OY}; FillRect(dc, &ln, line); DeleteObject(line);
    int y = 122 + OY;
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
    text(dc, g_fsmall, C_ACCENT, r_import.left, r_import.top, L"Bring my account");
    text(dc, g_fsmall, C_ACCENT, r_export.left, r_export.top, L"Export account");
    text(dc, g_fsmall, C_MUTED, r_forgot.left, r_forgot.top, L"Forgot password");
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
    { char ip[64]; if (!resolve(g_srv[g_cur].addr, ip)) { SetCursor(LoadCursor(NULL, IDC_ARROW)); wcscpy(g_err, L"Can't find that server name."); InvalidateRect(g_win, NULL, TRUE); return; }
      snprintf(g_host, sizeof g_host, "%s", ip); }
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
    of.lpstrFilter = L"Official backup or Rozefield account (*.rzsave, *.rzaccount)\0*.rzsave;*.rzaccount\0All files\0*.*\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH;
    of.Flags = OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR; of.lpstrTitle = L"Choose your official backup (.rzsave) or Rozefield account (.rzaccount)";
    int acct = wcslen(fn) > 10 && !_wcsicmp(fn + wcslen(fn) - 10, L".rzaccount");
    if (!GetOpenFileNameW(&of)) return;
    acct = wcslen(fn) > 10 && !_wcsicmp(fn + wcslen(fn) - 10, L".rzaccount");
    char path[300] = "/rozefield/import";
    if (acct) {   /* an account from another Rozefield server needs the log-in name it will have here */
        wchar_t wn[64]; GetWindowTextW(g_ename, wn, 64);
        if (!wn[0]) { wcscpy(g_err, L"Type the account name you want on this server first."); InvalidateRect(g_win, NULL, TRUE); return; }
        char n8[192]; WideCharToMultiByte(CP_UTF8, 0, wn, -1, n8, sizeof n8, NULL, NULL);
        strcat(path, "?name="); for (unsigned char *c = (unsigned char *)n8; *c && strlen(path) < sizeof path - 4; c++) { if (isalnum(*c)) { size_t l2 = strlen(path); path[l2] = (char)*c; path[l2 + 1] = 0; } else sprintf(path + strlen(path), "%%%02X", *c); }
    }
    HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) { wcscpy(g_err, L"Couldn't open that file."); InvalidateRect(g_win, NULL, TRUE); return; }
    DWORD size = GetFileSize(f, NULL), got = 0;
    char *data = (char *)malloc(size ? size : 1);
    ReadFile(f, data, size, &got, NULL); CloseHandle(f);
    char out[600];
    SetCursor(LoadCursor(NULL, IDC_WAIT));
    int ok = http_post(path, data, (int)got, out, sizeof out, 120000);
    SetCursor(LoadCursor(NULL, IDC_ARROW));
    free(data);
    if (!ok) { wcscpy(g_err, L"The Rozefield server didn't answer. Is it running?"); InvalidateRect(g_win, NULL, TRUE); return; }
    if (strncmp(out, "OK|", 3) == 0) {
        char *uid = out + 3, *nm = strchr(uid, '|'); if (nm) *nm++ = 0; else nm = uid;
        wchar_t w[128]; MultiByteToWideChar(CP_UTF8, 0, nm, -1, w, 128);
        g_tab = 0; layout();
        if (!acct) SetWindowTextW(g_ename, w);
        SetWindowTextW(g_epw, L""); SetFocus(g_epw);
        swprintf(g_err, 256, L"\"%ls\" is here. Choose a password and press Enter game.", w);
    } else {
        wchar_t w[256]; MultiByteToWideChar(CP_UTF8, 0, strncmp(out, "ERR|", 4) == 0 ? out + 4 : out, -1, w, 256);
        swprintf(g_err, 256, L"Import failed: %ls", w);
    }
    InvalidateRect(g_win, NULL, TRUE);
}

#define WM_STAT (WM_APP + 5)
static DWORD WINAPI stat_thread(LPVOID a) {
    LONG gen = (LONG)(INT_PTR)a; char ip[64] = "", out[2048]; wchar_t st[200]; COLORREF c = C_ERR;
    struct srv sv = g_srv[g_cur];
    if (!resolve(sv.addr, ip)) wcscpy(st, L"Can't find that server name.");
    else {
        char keep[64]; snprintf(keep, sizeof keep, "%s", g_host); snprintf(g_host, sizeof g_host, "%s", ip);
        int ok = 0; SOCKET s = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a2 = {0}; a2.sin_family = AF_INET; a2.sin_port = htons(18881); a2.sin_addr.s_addr = inet_addr(ip);
        DWORD to = 2500; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
        if (connect(s, (struct sockaddr *)&a2, sizeof a2) == 0) {
            const char *rq = "GET /rozefield/info HTTP/1.0\r\nHost: rozefield\r\n\r\n"; send(s, rq, (int)strlen(rq), 0);
            int l = 0, r; while (l < (int)sizeof out - 1 && (r = recv(s, out + l, sizeof out - 1 - l, 0)) > 0) l += r; out[l] = 0; ok = strstr(out, "rozefield-info") != NULL;
        }
        closesocket(s); (void)keep;
        if (!ok) swprintf(st, 200, L"Not reachable right now (%hs).", ip);
        else { const char *o = strstr(out, "\"online\":"); int on = o ? atoi(o + 9) : 0;
               swprintf(st, 200, L"Online  \x00B7  %d player%ls on now%ls", on, on == 1 ? L"" : L"s",
                        g_game_ip[0] && strcmp(ip, g_game_ip) ? L"  \x00B7  game restarts to switch" : L""); c = RGB(95, 212, 154); }
    }
    if (gen == g_gen) { wcscpy(g_stat, st); g_statc = c; InvalidateRect(g_win, NULL, TRUE); }
    return 0;
}
static void server_changed(void) {
    wcscpy(g_stat, L"Checking the server\x2026"); g_statc = C_MUTED; save_servers(); load_saved(); g_err[0] = 0;
    LONG gen = InterlockedIncrement(&g_gen); CloseHandle(CreateThread(NULL, 0, stat_thread, (LPVOID)(INT_PTR)gen, 0, NULL));
    InvalidateRect(g_win, NULL, TRUE);
}
/* one-line input box in the card's colours */
static wchar_t g_in[300]; static int g_in_done;
static LRESULT CALLBACK InProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CTLCOLOREDIT: SetTextColor((HDC)w, C_TEXT); SetBkColor((HDC)w, C_FIELD); return (LRESULT)g_brfield;
    case WM_CTLCOLORSTATIC: SetTextColor((HDC)w, C_MUTED); SetBkColor((HDC)w, C_CARD); return (LRESULT)g_brcard;
    case WM_ERASEBKGND: { RECT r; GetClientRect(h, &r); FillRect((HDC)w, &r, g_brcard); return 1; }
    case WM_COMMAND: if (LOWORD(w) == IDOK || LOWORD(w) == IDCANCEL) { if (LOWORD(w) == IDOK) GetWindowTextW(GetDlgItem(h, 100), g_in, 300); g_in_done = LOWORD(w) == IDOK ? 1 : -1; DestroyWindow(h); } return 0;
    case WM_CLOSE: g_in_done = -1; DestroyWindow(h); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}
static int input(const wchar_t *prompt) {
    static int reg; if (!reg) { WNDCLASSW wc = {0}; wc.lpfnWndProc = InProc; wc.hInstance = GetModuleHandleW(NULL); wc.lpszClassName = L"RzIn"; wc.hCursor = LoadCursor(NULL, IDC_ARROW); RegisterClassW(&wc); reg = 1; }
    RECT pr; GetWindowRect(g_win, &pr); int W = CW - 20, H = 150;
    HWND d = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, L"RzIn", L"", WS_POPUP | WS_BORDER, pr.left + 10, pr.top + 60, W, H, g_win, NULL, NULL, NULL);
    HWND st = CreateWindowW(L"STATIC", prompt, WS_CHILD | WS_VISIBLE, 16, 12, W - 32, 40, d, NULL, NULL, NULL); SendMessageW(st, WM_SETFONT, (WPARAM)g_fsmall, TRUE);
    HWND e = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 16, 56, W - 32, 28, d, (HMENU)100, NULL, NULL); SendMessageW(e, WM_SETFONT, (WPARAM)g_fbody, TRUE);
    HWND ok = CreateWindowW(L"BUTTON", L"OK", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON, W - 196, 100, 86, 30, d, (HMENU)IDOK, NULL, NULL);
    HWND ca = CreateWindowW(L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP, W - 102, 100, 86, 30, d, (HMENU)IDCANCEL, NULL, NULL);
    SendMessageW(ok, WM_SETFONT, (WPARAM)g_fsmall, TRUE); SendMessageW(ca, WM_SETFONT, (WPARAM)g_fsmall, TRUE);
    ShowWindow(d, SW_SHOW); EnableWindow(g_win, FALSE); SetFocus(e); g_in_done = 0; g_in[0] = 0; MSG msg;
    while (!g_in_done && GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN) { SendMessageW(d, WM_COMMAND, IDOK, 0); continue; }
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_ESCAPE) { SendMessageW(d, WM_COMMAND, IDCANCEL, 0); continue; }
        if (!IsDialogMessageW(d, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    }
    EnableWindow(g_win, TRUE); SetForegroundWindow(g_win); return g_in_done == 1 && g_in[0];
}
static void do_add(void) {
    if (!input(L"Invite code, server name or address (ask the server owner), e.g. RZ-1A2B-3CD or myserver.duckdns.org")) return;
    char a[256], ip[64]; WideCharToMultiByte(CP_UTF8, 0, g_in, -1, a, sizeof a, NULL, NULL);
    char *b = a; while (*b == ' ') b++; char *e = b + strlen(b); while (e > b && (e[-1] == ' ' || e[-1] == '/')) *--e = 0;
    if (!strncmp(b, "http://", 7)) b += 7;
    char nm[96]; snprintf(nm, sizeof nm, "%s", b);
    if (read_code(b, ip)) b = ip;
    add_srv(nm, b); for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, b)) g_cur = i;
    server_changed();
}
static void do_find(void) {
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0); BOOL on = TRUE; setsockopt(s, SOL_SOCKET, SO_BROADCAST, (char *)&on, sizeof on);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18882); a.sin_addr.s_addr = INADDR_BROADCAST;
    sendto(s, "ROZEFIELD?", 10, 0, (struct sockaddr *)&a, sizeof a);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK); sendto(s, "ROZEFIELD?", 10, 0, (struct sockaddr *)&a, sizeof a);
    int before = g_nsrv; DWORD end = GetTickCount() + 1500; SetCursor(LoadCursor(NULL, IDC_WAIT));
    while (GetTickCount() < end) {
        fd_set r; FD_ZERO(&r); FD_SET(s, &r); struct timeval tv = {0, 200000};
        if (select(0, &r, NULL, NULL, &tv) != 1) continue;
        char b[2048]; struct sockaddr_in from; int fl = sizeof from; int n = recvfrom(s, b, sizeof b - 1, 0, (struct sockaddr *)&from, &fl);
        if (n <= 0) continue; b[n] = 0;
        char nm[96], ip[64]; str_after(b, "name", nm, sizeof nm); inet_ntop(AF_INET, &from.sin_addr, ip, sizeof ip);
        if (!strcmp(ip, "127.0.0.1")) strcat(nm, " (this PC)");
        add_srv(nm, ip);
    }
    closesocket(s); SetCursor(LoadCursor(NULL, IDC_ARROW));
    swprintf(g_err, 256, g_nsrv > before ? L"Found %d server%ls on your network: pick it in the server list." : L"No new servers found on your network.", g_nsrv - before, g_nsrv - before == 1 ? L"" : L"s");
    if (g_nsrv > before) save_servers();
    InvalidateRect(g_win, NULL, TRUE);
}
static void server_menu(void) {
    HMENU m = CreatePopupMenu();
    for (int i = 0; i < g_nsrv; i++) {
        char t[400]; wchar_t w[400];
        if (!strcmp(g_srv[i].name, g_srv[i].addr)) snprintf(t, sizeof t, "%s", g_srv[i].name); else snprintf(t, sizeof t, "%s  (%s)", g_srv[i].name, g_srv[i].addr);
        MultiByteToWideChar(CP_UTF8, 0, t, -1, w, 400); AppendMenuW(m, MF_STRING | (i == g_cur ? MF_CHECKED : 0), 1 + i, w);
    }
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, 900, L"Add server\x2026");
    AppendMenuW(m, MF_STRING, 901, L"Find on my network");
    if (g_nsrv > 1) AppendMenuW(m, MF_STRING, 902, L"Remove this server from the list");
    POINT pt = {r_srv.left, r_srv.bottom}; ClientToScreen(g_win, &pt);
    int c = TrackPopupMenu(m, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN, pt.x, pt.y, 0, g_win, NULL); DestroyMenu(m);
    if (c >= 1 && c <= g_nsrv) { g_cur = c - 1; server_changed(); }
    else if (c == 900) do_add();
    else if (c == 901) do_find();
    else if (c == 902) { memmove(&g_srv[g_cur], &g_srv[g_cur + 1], (g_nsrv - g_cur - 1) * sizeof(struct srv)); g_nsrv--; g_cur = 0; server_changed(); }
}
static void do_export(void) {
    wchar_t wn[64], wp[128]; GetWindowTextW(g_ename, wn, 64); GetWindowTextW(g_epw, wp, 128);
    if (!wn[0] || !wp[0]) { wcscpy(g_err, L"Type your account name and password first."); InvalidateRect(g_win, NULL, TRUE); return; }
    char n8[192], p8[384], body[600]; WideCharToMultiByte(CP_UTF8, 0, wn, -1, n8, sizeof n8, NULL, NULL); WideCharToMultiByte(CP_UTF8, 0, wp, -1, p8, sizeof p8, NULL, NULL);
    int bl = snprintf(body, sizeof body, "%s\n%s", n8, p8); SecureZeroMemory(p8, sizeof p8); SecureZeroMemory(wp, sizeof wp);
    /* the account file can be larger than http_post's buffer: read it here */
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18881); a.sin_addr.s_addr = inet_addr(g_host);
    DWORD to = 30000; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    if (connect(s, (struct sockaddr *)&a, sizeof a)) { closesocket(s); wcscpy(g_err, L"The Rozefield server didn't answer."); InvalidateRect(g_win, NULL, TRUE); return; }
    char hdr[200]; int hl = snprintf(hdr, sizeof hdr, "POST /rozefield/export_account HTTP/1.0\r\nHost: rozefield\r\nContent-Length: %d\r\n\r\n", bl);
    send(s, hdr, hl, 0); send(s, body, bl, 0); SecureZeroMemory(body, sizeof body);
    size_t cap = 1 << 20, len = 0; int r; char *b = (char *)malloc(cap + 1);
    while ((r = recv(s, b + len, (int)(cap - len), 0)) > 0) { len += r; if (len == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
    b[len] = 0; closesocket(s);
    char *bd = strstr(b, "\r\n\r\n"); bd = bd ? bd + 4 : b + len;
    if (*bd != '{') { MultiByteToWideChar(CP_UTF8, 0, strncmp(bd, "ERR|", 4) == 0 ? bd + 4 : bd, -1, g_err, 256); free(b); InvalidateRect(g_win, NULL, TRUE); return; }
    wchar_t fn[MAX_PATH]; swprintf(fn, MAX_PATH, L"%ls.rzaccount", wn);
    OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win; of.lpstrFilter = L"Rozefield account (*.rzaccount)\0*.rzaccount\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH;
    of.lpstrDefExt = L"rzaccount"; of.Flags = OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR;
    if (GetSaveFileNameW(&of)) {
        HANDLE f = CreateFileW(fn, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w = 0, want = (DWORD)(b + len - bd);
        if (f != INVALID_HANDLE_VALUE) { WriteFile(f, bd, want, &w, NULL); CloseHandle(f); }
        wcscpy(g_err, w == want ? L"Saved. On another server: pick it, then Bring my account." : L"Couldn't save the file.");
    }
    free(b); InvalidateRect(g_win, NULL, TRUE);
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
            if (pt.y < 58 && !in(r_close, pt.x, pt.y)) return HTCAPTION;
        }
        return r; }
    case WM_LBUTTONDOWN: {
        int x = (short)LOWORD(l), y = (short)HIWORD(l);
        if (in(r_close, x, y)) { g_done = -1; DestroyWindow(h); return 0; }
        if (in(r_tab0, x, y) && g_tab) { g_tab = 0; g_err[0] = 0; layout(); return 0; }
        if (in(r_tab1, x, y) && !g_tab) { g_tab = 1; g_err[0] = 0; layout(); return 0; }
        if (in(r_rem, x, y)) { g_remember = !g_remember; InvalidateRect(h, NULL, TRUE); return 0; }
        if (in(r_import, x, y)) { do_import(); return 0; }
        if (in(r_export, x, y)) { do_export(); return 0; }
        if (in(r_srv, x, y)) { server_menu(); return 0; }
        if (in(r_add, x, y)) { do_add(); return 0; }
        if (in(r_find, x, y)) { do_find(); return 0; }
        if (in(r_forgot, x, y)) { wcscpy(g_err, L"Ask the server owner to reset it (tools\\reset_password.py)."); InvalidateRect(h, NULL, TRUE); return 0; }
        for (int i = 0; i < 8; i++) if (r_chip[i].right && in(r_chip[i], x, y)) {
            wchar_t wn[128]; MultiByteToWideChar(CP_UTF8, 0, g_saved[i], -1, wn, 128);
            SetWindowTextW(g_ename, wn); SetFocus(g_epw); return 0; }
        return 0; }
    case WM_SETCURSOR: {
        POINT pt; GetCursorPos(&pt); ScreenToClient(h, &pt);
        int hot = in(r_close, pt.x, pt.y) || in(r_tab0, pt.x, pt.y) || in(r_tab1, pt.x, pt.y) || in(r_rem, pt.x, pt.y) || in(r_import, pt.x, pt.y) || in(r_forgot, pt.x, pt.y) ||
                  in(r_export, pt.x, pt.y) || in(r_srv, pt.x, pt.y) || in(r_add, pt.x, pt.y) || in(r_find, pt.x, pt.y);
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
    load_servers(); server_changed();
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

static void write_file(const char *f, const char *d, DWORD n) {
    HANDLE h = CreateFileA(f, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w; if (h != INVALID_HANDLE_VALUE) { WriteFile(h, d, n, &w, NULL); CloseHandle(h); }
}
static void point_config(const char *ip) {   /* Config.txt: UseCustomConfig = TRUE, RemoteServerIP = ip */
    char f[MAX_PATH], o[MAX_PATH]; snprintf(f, sizeof f, "%slauncher_Data\\StreamingAssets\\Config.txt", g_dir); snprintf(o, sizeof o, "%s.orig", f);
    DWORD len; char *t = read_all(f, &len); if (!t) return;
    if (GetFileAttributesA(o) == INVALID_FILE_ATTRIBUTES) CopyFileA(f, o, TRUE);
    size_t cap = len + 256; char *n = (char *)calloc(cap, 1); char *save = NULL; int c = 0, i = 0;
    for (char *line = strtok_s(t, "\n", &save); line; line = strtok_s(NULL, "\n", &save)) {
        char *cr = strchr(line, '\r'); if (cr) *cr = 0; char k[64] = ""; sscanf(line, " %63[^= ]", k);
        if (!strcmp(k, "UseCustomConfig")) { strcat(n, "UseCustomConfig = TRUE\r\n"); c = 1; }
        else if (!strcmp(k, "RemoteServerIP")) { snprintf(n + strlen(n), cap - strlen(n), "RemoteServerIP = %s\r\n", ip); i = 1; }
        else { strcat(n, line); strcat(n, "\r\n"); }
    }
    if (!c) strcat(n, "UseCustomConfig = TRUE\r\n");
    if (!i) snprintf(n + strlen(n), cap - strlen(n), "RemoteServerIP = %s\r\n", ip);
    write_file(f, n, (DWORD)strlen(n)); free(t); free(n);
}
static void point_lookup(const char *ip) {   /* the game's address lookup (HTTPDNS): the server itself if it fits, else this PC */
    const char *target = strlen(ip) <= 12 ? ip : "127.0.0.1";
    char f[MAX_PATH], o[MAX_PATH]; snprintf(f, sizeof f, "%slauncher_Data\\il2cpp_data\\Metadata\\global-metadata.dat", g_dir); snprintf(o, sizeof o, "%s.orig", f);
    int have_orig = GetFileAttributesA(o) != INVALID_FILE_ATTRIBUTES;
    DWORD len; char *d = read_all(have_orig ? o : f, &len); if (!d) return;
    unsigned lo = *(unsigned *)(d + 8), ls = *(unsigned *)(d + 12), ldo = *(unsigned *)(d + 16);
    char *hitp = NULL; for (char *p = d + ldo; p + 12 <= d + len; p++) if (!memcmp(p, "8.134.240.36", 12)) { hitp = p; break; }
    if (!hitp) { free(d); logf_("lookup: original address not found, left as it is%s", ""); return; }
    int pos = (int)(hitp - (d + ldo)), hit = -1;
    for (unsigned i = 0; i < ls / 8; i++) { unsigned *e = (unsigned *)(d + lo + i * 8); if (e[0] == 12 && (int)e[1] == pos) { hit = (int)(lo + i * 8); break; } }
    if (hit < 0) { free(d); return; }
    if (!have_orig) CopyFileA(f, o, TRUE);
    memcpy(d + ldo + pos, target, strlen(target)); *(unsigned *)(d + hit) = (unsigned)strlen(target);
    write_file(f, d, len); free(d); logf_("lookup -> %s", target);
}
static DWORD parent_pid(void);
static void switch_and_restart(const char *ip) {
    char sdk[MAX_PATH], exp[32]; snprintf(sdk, sizeof sdk, "%srozefield_sdk.ini", g_dir); snprintf(exp, sizeof exp, "%lld", (long long)time(NULL) + 600);
    WritePrivateProfileStringA("server", "ip", ip, sdk);
    WritePrivateProfileStringA("handoff", "uid", g_uid, sdk); WritePrivateProfileStringA("handoff", "name", g_name, sdk);
    WritePrivateProfileStringA("handoff", "key", g_key, sdk); WritePrivateProfileStringA("handoff", "expires", exp, sdk);
    point_config(ip);
    HANDLE g = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, FALSE, parent_pid());
    if (g) { TerminateProcess(g, 0); WaitForSingleObject(g, 15000); CloseHandle(g); }
    Sleep(500);
    point_lookup(ip);
    char game[MAX_PATH]; snprintf(game, sizeof game, "%slauncher.exe", g_dir);
    STARTUPINFOA si = {sizeof si}; PROCESS_INFORMATION pi;
    if (CreateProcessA(game, NULL, NULL, NULL, FALSE, 0, NULL, g_dir, &si, &pi)) { CloseHandle(pi.hThread); CloseHandle(pi.hProcess); }
    logf_("switched server to %s and restarted the game", ip);
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
        } else {
            /* picked a server the running game isn't using: point the game there and restart it, logged in */
            const char *cur = g_game_ip[0] ? g_game_ip : "127.0.0.1";
            if (strcmp(g_host, cur)) { switch_and_restart(g_host); return 0; }
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
