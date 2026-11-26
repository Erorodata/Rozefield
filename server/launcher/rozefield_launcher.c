/* Rozefield.exe - the game's own launcher (sits next to launcher.exe in the Overfield folder).
 * Choose a server (the default one from rozefield_servers.json, ones added by invite code / name / address, and ones
 * found on the home network), log in or create an account (fresh, or bring an official backup / a Rozefield account),
 * then Play: the game opens already signed in on that server. No admin rights and no setup script:
 *   - the game's address lookup (HTTPDNS) is pointed at this PC once (global-metadata.dat, original kept as .orig),
 *     and while the game runs this launcher answers those lookups with the chosen server's address;
 *   - Config.txt and rozefield_sdk.ini get the server's address; the login is handed to PCSDKUI.exe ([handoff]).
 * Saved servers and remembered logins: %APPDATA%\Rozefield\launcher.ini (passwords protected with Windows DPAPI).
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 rozefield_launcher.c launcher.rc -o Rozefield.exe
 *        -lws2_32 -lcomdlg32 -lshell32 -luser32 -lgdi32 -lcrypt32 -lwinhttp -Wl,--subsystem,windows
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <commdlg.h>
#include <wincrypt.h>
#include <winhttp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <time.h>
#include <ctype.h>

#define CW 560
#define CH 660
#define C_INK RGB(244, 246, 248)
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
#define WM_INFO (WM_APP + 1)
#define WM_DONE (WM_APP + 2)
#define HTTP_PORT 18881
#ifndef EM_SETCUEBANNER
#define EM_SETCUEBANNER 0x1501
#endif

static HWND g_win, g_combo, g_ename, g_epw;
static HFONT f_title, f_h, f_body, f_small, f_btn;
static HBRUSH br_panel, br_field;
static char g_dir[MAX_PATH], g_ini[MAX_PATH];
static int g_hover, g_remember = 1, g_busy;
static wchar_t g_status[300] = L"", g_msg[400] = L"";
static COLORREF g_statc = C_MUTE, g_msgc = C_MUTE;

/* ---------------------------------------------------------------- servers */
struct srv { char name[96]; char addr[256]; int lan; };
static struct srv g_srv[64]; static int g_nsrv, g_cur;
static volatile LONG g_info_gen;

static void u2w(const char *u, wchar_t *w, int n) { MultiByteToWideChar(CP_UTF8, 0, u, -1, w, n); }
static void w2u(const wchar_t *w, char *u, int n) { WideCharToMultiByte(CP_UTF8, 0, w, -1, u, n, NULL, NULL); }
static void trim(char *s) { char *b = s; while (*b == ' ' || *b == '\t') b++; memmove(s, b, strlen(b) + 1); char *e = s + strlen(s); while (e > s && (e[-1] == ' ' || e[-1] == '\r' || e[-1] == '\n' || e[-1] == '/')) *--e = 0; }

/* invite code: RZ-XXXX-XXX = an IPv4 address in base32 (Crockford alphabet, no I L O U) */
static const char B32[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
static void make_code(unsigned ip /* host order */, char *out) {
    char c[8]; unsigned long long v = ip;
    for (int i = 6; i >= 0; i--) { c[i] = B32[v & 31]; v >>= 5; }
    sprintf(out, "RZ-%c%c%c%c-%c%c%c", c[0], c[1], c[2], c[3], c[4], c[5], c[6]);
}
static int read_code(const char *s, char *ip_out) {
    if (toupper((unsigned char)s[0]) != 'R' || toupper((unsigned char)s[1]) != 'Z') return 0;
    unsigned long long v = 0; int n = 0;
    for (const char *p = s + 2; *p; p++) {
        if (*p == '-' || *p == ' ') continue;
        char ch = (char)toupper((unsigned char)*p); if (ch == 'O') ch = '0'; if (ch == 'I' || ch == 'L') ch = '1';
        const char *q = strchr(B32, ch); if (!q || !*q) return 0;
        v = (v << 5) | (unsigned)(q - B32); n++;
    }
    if (n != 7 || v > 0xFFFFFFFFull) return 0;
    sprintf(ip_out, "%u.%u.%u.%u", (unsigned)(v >> 24) & 255, (unsigned)(v >> 16) & 255, (unsigned)(v >> 8) & 255, (unsigned)v & 255);
    return 1;
}

static void add_srv(const char *name, const char *addr, int lan) {
    for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, addr)) { if (name[0] && !lan) snprintf(g_srv[i].name, 96, "%s", name); return; }
    if (g_nsrv >= 64) return;
    snprintf(g_srv[g_nsrv].name, 96, "%s", name[0] ? name : addr); snprintf(g_srv[g_nsrv].addr, 256, "%s", addr); g_srv[g_nsrv].lan = lan; g_nsrv++;
}

/* tiny reader for rozefield_servers.json: "default", "list_url" and every {"name":..,"address":..} */
static void str_after(const char *from, const char *key, char *out, int n) {
    out[0] = 0; char k[64]; snprintf(k, sizeof k, "\"%s\"", key); const char *p = strstr(from, k); if (!p) return;
    p = strchr(p + strlen(k), ':'); if (!p) return; p++; while (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t') p++;
    if (*p != '"') return; p++; int i = 0;
    while (*p && *p != '"' && i < n - 1) { if (*p == '\\' && p[1]) p++; out[i++] = *p++; }
    out[i] = 0;
}
static void read_list_json(const char *js, char *def, char *list_url) {
    if (def) str_after(js, "default", def, 256);
    if (list_url) str_after(js, "list_url", list_url, 512);
    const char *p = js;
    while ((p = strstr(p, "\"address\"")) != NULL) {
        const char *ob = p; while (ob > js && *ob != '{') ob--;
        char nm[96], ad[256]; str_after(ob, "name", nm, sizeof nm); str_after(ob, "address", ad, sizeof ad);
        if (ad[0]) add_srv(nm, ad, 0);
        p += 9;
    }
}
static char *read_file(const char *path, DWORD *len) {
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return NULL;
    DWORD sz = GetFileSize(f, NULL), got = 0; char *b = (char *)malloc(sz + 1); ReadFile(f, b, sz, &got, NULL); CloseHandle(f);
    b[got] = 0; if (len) *len = got; return b;
}
static char *https_get(const char *url) {   /* for a server list kept on GitHub (or any https page) */
    wchar_t w[1024]; u2w(url, w, 1024); URL_COMPONENTS uc = {sizeof uc}; wchar_t host[256], path[768];
    uc.lpszHostName = host; uc.dwHostNameLength = 256; uc.lpszUrlPath = path; uc.dwUrlPathLength = 768;
    if (!WinHttpCrackUrl(w, 0, 0, &uc)) return NULL;
    HINTERNET s = WinHttpOpen(L"Rozefield", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, NULL, NULL, 0); if (!s) return NULL;
    WinHttpSetTimeouts(s, 4000, 4000, 4000, 4000);
    HINTERNET c = WinHttpConnect(s, host, uc.nPort, 0);
    HINTERNET r = c ? WinHttpOpenRequest(c, L"GET", path, NULL, NULL, NULL, uc.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0) : NULL;
    char *out = NULL;
    if (r && WinHttpSendRequest(r, NULL, 0, NULL, 0, 0, 0) && WinHttpReceiveResponse(r, NULL)) {
        size_t cap = 65536, len = 0; out = (char *)malloc(cap + 1); DWORD n;
        while (WinHttpReadData(r, out + len, (DWORD)(cap - len), &n) && n) { len += n; if (len == cap) { cap *= 2; out = (char *)realloc(out, cap + 1); } }
        out[len] = 0;
    }
    if (r) WinHttpCloseHandle(r); if (c) WinHttpCloseHandle(c); WinHttpCloseHandle(s);
    return out;
}

static void load_servers(void) {
    char p[MAX_PATH], def[256] = "", url[512] = "";
    snprintf(p, sizeof p, "%srozefield_servers.json", g_dir);
    char *js = read_file(p, NULL);
    if (js) { read_list_json(js, def, url); free(js); }
    if (url[0]) { char *l = https_get(url); if (l) { read_list_json(l, NULL, NULL); free(l); } }
    int n = GetPrivateProfileIntA("servers", "count", 0, g_ini);
    for (int i = 0; i < n; i++) {
        char k[16], v[400]; snprintf(k, sizeof k, "s%d", i); GetPrivateProfileStringA("servers", k, "", v, sizeof v, g_ini);
        char *bar = strchr(v, '|'); if (!bar) continue; *bar = 0; add_srv(v, bar + 1, 0);
    }
    if (!g_nsrv) add_srv("This PC", "127.0.0.1", 0);
    char last[256]; GetPrivateProfileStringA("last", "server", def, last, sizeof last, g_ini);
    g_cur = 0; for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, last)) g_cur = i;
}
static void save_servers(void) {
    char v[400], k[16]; int n = 0;
    WritePrivateProfileStringA("servers", NULL, NULL, g_ini);
    for (int i = 0; i < g_nsrv; i++) { if (g_srv[i].lan) continue; snprintf(k, sizeof k, "s%d", n++); snprintf(v, sizeof v, "%s|%s", g_srv[i].name, g_srv[i].addr); WritePrivateProfileStringA("servers", k, v, g_ini); }
    snprintf(v, sizeof v, "%d", n); WritePrivateProfileStringA("servers", "count", v, g_ini);
    WritePrivateProfileStringA("last", "server", g_srv[g_cur].addr, g_ini);
}
static void fill_combo(void) {
    SendMessageW(g_combo, CB_RESETCONTENT, 0, 0);
    for (int i = 0; i < g_nsrv; i++) {
        char t[400]; wchar_t w[400];
        if (!strcmp(g_srv[i].name, g_srv[i].addr)) snprintf(t, sizeof t, "%s%s", g_srv[i].name, g_srv[i].lan ? "  (home network)" : "");
        else snprintf(t, sizeof t, "%s  \xC2\xB7  %s%s", g_srv[i].name, g_srv[i].addr, g_srv[i].lan ? "  (home network)" : "");
        u2w(t, w, 400); SendMessageW(g_combo, CB_ADDSTRING, 0, (LPARAM)w);
    }
    SendMessageW(g_combo, CB_SETCURSEL, g_cur, 0);
}

/* ---------------------------------------------------------------- remembered logins (DPAPI) */
static void key_for(char *k, int n, const char *addr, const char *what) { snprintf(k, n, "%s_%s", what, addr); for (char *c = k; *c; c++) if (*c == '=' || *c == '[' || *c == ']') *c = '_'; }
static void remember(const char *addr, const char *name, const char *pw) {
    char k[320]; key_for(k, sizeof k, addr, "name"); WritePrivateProfileStringA("logins", k, name, g_ini);
    key_for(k, sizeof k, addr, "pw");
    if (!pw) { WritePrivateProfileStringA("logins", k, NULL, g_ini); return; }
    DATA_BLOB in = {(DWORD)strlen(pw), (BYTE *)pw}, out;
    if (CryptProtectData(&in, L"Rozefield", NULL, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) {
        char *hex = (char *)malloc(out.cbData * 2 + 1); for (DWORD i = 0; i < out.cbData; i++) sprintf(hex + 2 * i, "%02x", out.pbData[i]);
        WritePrivateProfileStringA("logins", k, hex, g_ini); free(hex); LocalFree(out.pbData);
    }
}
static void recall(const char *addr, char *name, int nn, char *pw, int pn) {
    char k[320]; key_for(k, sizeof k, addr, "name"); GetPrivateProfileStringA("logins", k, "", name, nn, g_ini);
    pw[0] = 0; key_for(k, sizeof k, addr, "pw"); char hex[2048]; GetPrivateProfileStringA("logins", k, "", hex, sizeof hex, g_ini);
    int hl = (int)strlen(hex) / 2; if (!hl) return;
    BYTE *b = (BYTE *)malloc(hl); for (int i = 0; i < hl; i++) { unsigned v; sscanf(hex + 2 * i, "%2x", &v); b[i] = (BYTE)v; }
    DATA_BLOB in = {(DWORD)hl, b}, out;
    if (CryptUnprotectData(&in, NULL, NULL, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) {
        int n = (int)out.cbData < pn - 1 ? (int)out.cbData : pn - 1; memcpy(pw, out.pbData, n); pw[n] = 0; SecureZeroMemory(out.pbData, out.cbData); LocalFree(out.pbData);
    }
    free(b);
}

/* ---------------------------------------------------------------- talking to a server */
static int resolve(const char *addr, char *ip) {
    char a[256], c[64]; snprintf(a, sizeof a, "%s", addr); trim(a);
    if (!strncmp(a, "http://", 7)) memmove(a, a + 7, strlen(a + 7) + 1);
    char *col = strchr(a, ':'); if (col) *col = 0;
    if (read_code(a, c)) { strcpy(ip, c); return 1; }
    struct addrinfo h = {0}, *r = NULL; h.ai_family = AF_INET; h.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(a, NULL, &h, &r) != 0 || !r) return 0;
    inet_ntop(AF_INET, &((struct sockaddr_in *)r->ai_addr)->sin_addr, ip, 64); freeaddrinfo(r); return 1;
}
/* plain HTTP to ip:port; returns body (malloc) or NULL; *len = body length */
static char *http(const char *ip, int port, const char *method, const char *path, const char *body, int blen, int *len, int timeout) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port);
    inet_pton(AF_INET, ip, &a.sin_addr);
    DWORD to = timeout; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to); setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (char *)&to, sizeof to);
    u_long nb = 1; ioctlsocket(s, FIONBIO, &nb); connect(s, (struct sockaddr *)&a, sizeof a);
    fd_set w; FD_ZERO(&w); FD_SET(s, &w); struct timeval tv = {timeout / 1000, (timeout % 1000) * 1000};
    if (select(0, NULL, &w, NULL, &tv) != 1) { closesocket(s); return NULL; }
    nb = 0; ioctlsocket(s, FIONBIO, &nb);
    char hdr[600]; int hl = snprintf(hdr, sizeof hdr, "%s %s HTTP/1.0\r\nHost: rozefield\r\nContent-Length: %d\r\n\r\n", method, path, blen);
    send(s, hdr, hl, 0); for (int off = 0; off < blen;) { int n = send(s, body + off, blen - off, 0); if (n <= 0) break; off += n; }
    size_t cap = 65536, l = 0; int r; char *b = (char *)malloc(cap + 1);
    while ((r = recv(s, b + l, (int)(cap - l), 0)) > 0) { l += r; if (l == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
    b[l] = 0; closesocket(s);
    char *p = strstr(b, "\r\n\r\n"); int code = 0; sscanf(b, "HTTP/%*s %d", &code);
    if (!p || code != 200) { free(b); return NULL; }
    int bl = (int)(l - (p + 4 - b)); memmove(b, p + 4, bl + 1); if (len) *len = bl; return b;
}

static DWORD WINAPI info_thread(LPVOID a) {
    LONG gen = (LONG)(INT_PTR)a; char ip[64] = "", *out = NULL;
    struct srv sv = g_srv[g_cur];
    wchar_t *st = (wchar_t *)malloc(300 * sizeof(wchar_t)); COLORREF c = C_BAD;
    if (!resolve(sv.addr, ip)) swprintf(st, 300, L"Can't find that server name.");
    else if (!(out = http(ip, HTTP_PORT, "GET", "/rozefield/info", "", 0, NULL, 2500))) swprintf(st, 300, L"Not reachable right now (%hs). Is the server on?", ip);
    else {
        char nm[96], ver[64], on[16] = "0"; str_after(out, "name", nm, sizeof nm); str_after(out, "version", ver, sizeof ver);
        const char *o = strstr(out, "\"online\":"); if (o) snprintf(on, sizeof on, "%d", atoi(o + 9));
        char *dash = strstr(ver, "-rz"); (void)dash;
        swprintf(st, 300, L"Online  \x00B7  %hs player%hs on now  \x00B7  update %.10hs", on, strcmp(on, "1") ? "s" : "", ver);
        c = C_OK; free(out);
    }
    if (gen == g_info_gen) { wcscpy(g_status, st); g_statc = c; PostMessageW(g_win, WM_INFO, 0, 0); }
    free(st); return 0;
}
static void refresh_info(void) {
    wcscpy(g_status, L"Checking the server\x2026"); g_statc = C_MUTE; InvalidateRect(g_win, NULL, FALSE);
    LONG gen = InterlockedIncrement(&g_info_gen); CloseHandle(CreateThread(NULL, 0, info_thread, (LPVOID)(INT_PTR)gen, 0, NULL));
}
static void server_changed(void) {
    char nm[128], pw[256]; recall(g_srv[g_cur].addr, nm, sizeof nm, pw, sizeof pw);
    wchar_t w[256]; u2w(nm, w, 128); SetWindowTextW(g_ename, w); u2w(pw, w, 256); SetWindowTextW(g_epw, w); SecureZeroMemory(pw, sizeof pw);
    g_msg[0] = 0; save_servers(); refresh_info();
}

/* ---------------------------------------------------------------- home network */
static void find_nearby(void) {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0); BOOL on = TRUE; setsockopt(s, SOL_SOCKET, SO_BROADCAST, (char *)&on, sizeof on);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(18882); a.sin_addr.s_addr = INADDR_BROADCAST;
    sendto(s, "ROZEFIELD?", 10, 0, (struct sockaddr *)&a, sizeof a);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK); sendto(s, "ROZEFIELD?", 10, 0, (struct sockaddr *)&a, sizeof a);
    int found = 0; DWORD end = GetTickCount() + 1500;
    while (GetTickCount() < end) {
        fd_set r; FD_ZERO(&r); FD_SET(s, &r); struct timeval tv = {0, 200000};
        if (select(0, &r, NULL, NULL, &tv) != 1) continue;
        char b[2048]; struct sockaddr_in from; int fl = sizeof from; int n = recvfrom(s, b, sizeof b - 1, 0, (struct sockaddr *)&from, &fl);
        if (n <= 0) continue; b[n] = 0;
        char nm[96], ip[64]; str_after(b, "name", nm, sizeof nm); inet_ntop(AF_INET, &from.sin_addr, ip, sizeof ip);
        if (!strcmp(ip, "127.0.0.1")) snprintf(nm + strlen(nm), sizeof nm - strlen(nm), " (this PC)");
        int before = g_nsrv; add_srv(nm, ip, 1); if (g_nsrv > before) found++; else found += 0;
    }
    closesocket(s);
    fill_combo();
    if (found) swprintf(g_msg, 400, L"Found %d server%ls on your network. Pick it in the list.", found, found == 1 ? L"" : L"s");
    else wcscpy(g_msg, L"No new servers found on your network.");
    g_msgc = C_MUTE;
}

/* ---------------------------------------------------------------- pointing the game at the server */
static int patch_metadata(wchar_t *err) {   /* the game's address lookup goes to this PC (127.0.0.1), done once */
    char f[MAX_PATH], o[MAX_PATH]; snprintf(f, sizeof f, "%slauncher_Data\\il2cpp_data\\Metadata\\global-metadata.dat", g_dir); snprintf(o, sizeof o, "%s.orig", f);
    DWORD len; char *d = read_file(GetFileAttributesA(o) != INVALID_FILE_ATTRIBUTES ? o : f, &len);
    if (!d) { wcscpy(err, L"Game files not found: put Rozefield.exe in the Overfield folder (next to launcher.exe)."); return 0; }
    unsigned lo = *(unsigned *)(d + 8), ls = *(unsigned *)(d + 12), ldo = *(unsigned *)(d + 16);
    const char *OLD = "8.134.240.36"; char *hitp = NULL;
    for (char *p = d + ldo; p + 12 <= d + len; p++) if (!memcmp(p, OLD, 12)) { hitp = p; break; }
    if (!hitp) { free(d); return 1; }   /* already pointed here (or a build without the lookup) */
    int pos = (int)(hitp - (d + ldo)), hit = -1;
    for (unsigned i = 0; i < ls / 8; i++) { unsigned *e = (unsigned *)(d + lo + i * 8); if (e[0] == 12 && (int)e[1] == pos) { hit = (int)(lo + i * 8); break; } }
    if (hit < 0) { free(d); wcscpy(err, L"This game build isn't supported (lookup not found)."); return 0; }
    /* is the current file already patched? */
    DWORD cl; char *cur = read_file(f, &cl);
    int done = cur && cl == len && *(unsigned *)(cur + hit) == 9 && !memcmp(cur + ldo + pos, "127.0.0.1", 9);
    free(cur);
    if (done) { free(d); return 1; }
    if (GetFileAttributesA(o) == INVALID_FILE_ATTRIBUTES) CopyFileA(f, o, TRUE);
    memcpy(d + ldo + pos, "127.0.0.1", 9); *(unsigned *)(d + hit) = 9;
    HANDLE h = CreateFileA(f, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w = 0;
    if (h != INVALID_HANDLE_VALUE) { WriteFile(h, d, len, &w, NULL); CloseHandle(h); }
    free(d);
    if (w != len) { wcscpy(err, L"Couldn't update the game files (is the game still open?)."); return 0; }
    return 1;
}
static void set_config(const char *ip) {   /* StreamingAssets\Config.txt: UseCustomConfig = TRUE, RemoteServerIP = <ip> */
    char f[MAX_PATH], o[MAX_PATH]; snprintf(f, sizeof f, "%slauncher_Data\\StreamingAssets\\Config.txt", g_dir); snprintf(o, sizeof o, "%s.orig", f);
    DWORD len; char *t = read_file(f, &len); if (!t) return;
    if (GetFileAttributesA(o) == INVALID_FILE_ATTRIBUTES) CopyFileA(f, o, TRUE);
    size_t cap = len + 256; char *n = (char *)malloc(cap); n[0] = 0; char *save = NULL; int sawc = 0, sawi = 0;
    for (char *line = strtok_s(t, "\n", &save); line; line = strtok_s(NULL, "\n", &save)) {
        char *cr = strchr(line, '\r'); if (cr) *cr = 0;
        char k[64] = ""; sscanf(line, " %63[^= ]", k);
        if (!strcmp(k, "UseCustomConfig")) { strcat(n, "UseCustomConfig = TRUE\r\n"); sawc = 1; }
        else if (!strcmp(k, "RemoteServerIP")) { snprintf(n + strlen(n), cap - strlen(n), "RemoteServerIP = %s\r\n", ip); sawi = 1; }
        else { strcat(n, line); strcat(n, "\r\n"); }
    }
    if (!sawc) strcat(n, "UseCustomConfig = TRUE\r\n");
    if (!sawi) snprintf(n + strlen(n), cap - strlen(n), "RemoteServerIP = %s\r\n", ip);
    HANDLE h = CreateFileA(f, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w;
    if (h != INVALID_HANDLE_VALUE) { WriteFile(h, n, (DWORD)strlen(n), &w, NULL); CloseHandle(h); }
    free(t); free(n);
}

/* answers the game's HTTPDNS lookups (GET /resolve?domain=..) with the server's address while the game runs */
static char g_lookup_ip[64]; static SOCKET g_lookup = INVALID_SOCKET;
static DWORD WINAPI lookup_conn(LPVOID a) {
    SOCKET c = (SOCKET)(INT_PTR)a; char b[4096]; int l = 0, r;
    DWORD to = 4000; setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    while (l < (int)sizeof b - 1 && (r = recv(c, b + l, sizeof b - 1 - l, 0)) > 0) { l += r; b[l] = 0; if (strstr(b, "\r\n\r\n")) break; }
    b[l] = 0;
    char dom[256] = ""; char *q = strstr(b, "domain="); if (q) { int i = 0; q += 7; while (*q && *q != '&' && *q != ' ' && i < 255) dom[i++] = *q++; dom[i] = 0; }
    char body[600]; int bl = snprintf(body, sizeof body, "{\"host\": \"%s\", \"ttl\": 600, \"ips\": [\"%s\"], \"cip\": \"127.0.0.1\", \"cl\": [3]}", dom, g_lookup_ip);
    char out[900]; int ol = snprintf(out, sizeof out, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s", bl, body);
    send(c, out, ol, 0); closesocket(c); return 0;
}
static DWORD WINAPI lookup_loop(LPVOID a) {
    for (;;) { SOCKET c = accept(g_lookup, NULL, NULL); if (c == INVALID_SOCKET) break; CloseHandle(CreateThread(NULL, 0, lookup_conn, (LPVOID)(INT_PTR)c, 0, NULL)); }
    return 0;
}
static int is_local_ip(const char *ip) {
    if (!strncmp(ip, "127.", 4)) return 1;
    char hn[256]; struct addrinfo h = {0}, *r = NULL, *p; h.ai_family = AF_INET;
    if (gethostname(hn, sizeof hn) || getaddrinfo(hn, NULL, &h, &r)) return 0;
    int yes = 0; for (p = r; p; p = p->ai_next) { char a[64]; inet_ntop(AF_INET, &((struct sockaddr_in *)p->ai_addr)->sin_addr, a, sizeof a); if (!strcmp(a, ip)) yes = 1; }
    freeaddrinfo(r); return yes;
}
static int start_lookup(const char *ip, wchar_t *err) {
    snprintf(g_lookup_ip, sizeof g_lookup_ip, "%s", ip);
    if (g_lookup != INVALID_SOCKET) return 1;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons(80); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s, (struct sockaddr *)&a, sizeof a) || listen(s, 16)) {
        closesocket(s);
        if (is_local_ip(ip)) return 1;   /* the Rozefield Server on this PC answers the lookups itself */
        wcscpy(err, L"Another program on this PC uses port 80 (a web server, or Rozefield Server for a different server). Close it and press Play again.");
        return 0;
    }
    g_lookup = s; CloseHandle(CreateThread(NULL, 0, lookup_loop, NULL, 0, NULL)); return 1;
}

/* ---------------------------------------------------------------- play */
static char g_pname[128], g_ppw[256];
static DWORD WINAPI play_thread(LPVOID a) {
    wchar_t *err = (wchar_t *)calloc(500, sizeof(wchar_t)); char ip[64];
    struct srv sv = g_srv[g_cur];
    if (!resolve(sv.addr, ip)) { wcscpy(err, L"Can't find that server name."); goto out; }
    char body[400]; int bl = snprintf(body, sizeof body, "%s\n%s", g_pname, g_ppw);
    char *r = http(ip, HTTP_PORT, "POST", "/rozefield/login", body, bl, NULL, 6000);
    SecureZeroMemory(body, sizeof body);
    if (!r) { swprintf(err, 500, L"The server didn't answer (%hs).", ip); goto out; }
    if (strncmp(r, "OK|", 3)) { wchar_t w[400]; u2w(strchr(r, '|') ? strchr(r, '|') + 1 : r, w, 400); wcscpy(err, w); free(r); goto out; }
    char *f[4] = {0}; int k = 0; char *q = r + 3; while (k < 3) { f[k++] = q; char *bar = strchr(q, '|'); if (!bar) break; *bar = 0; q = bar + 1; }
    if (k < 3) { wcscpy(err, L"Unexpected answer from the server."); free(r); goto out; }
    remember(sv.addr, g_pname, g_remember ? g_ppw : NULL);
    if (!patch_metadata(err)) { free(r); goto out; }
    set_config(ip);
    char sdk[MAX_PATH], exp[32]; snprintf(sdk, sizeof sdk, "%srozefield_sdk.ini", g_dir); snprintf(exp, sizeof exp, "%lld", (long long)time(NULL) + 600);
    WritePrivateProfileStringA("server", "ip", ip, sdk);
    WritePrivateProfileStringA("handoff", "uid", f[0], sdk); WritePrivateProfileStringA("handoff", "name", f[1], sdk);
    WritePrivateProfileStringA("handoff", "key", f[2], sdk); WritePrivateProfileStringA("handoff", "expires", exp, sdk);
    free(r);
    if (!start_lookup(ip, err)) goto out;
    char game[MAX_PATH]; snprintf(game, sizeof game, "%slauncher.exe", g_dir);
    STARTUPINFOA si = {sizeof si}; PROCESS_INFORMATION pi;
    if (!CreateProcessA(game, NULL, NULL, NULL, FALSE, 0, NULL, g_dir, &si, &pi)) { wcscpy(err, L"Couldn't start the game (launcher.exe)."); goto out; }
    CloseHandle(pi.hThread);
    PostMessageW(g_win, WM_DONE, 1, 0);          /* hide while the game runs */
    WaitForSingleObject(pi.hProcess, INFINITE); CloseHandle(pi.hProcess);
    PostMessageW(g_win, WM_DONE, 2, 0);          /* the game closed */
    free(err); SecureZeroMemory(g_ppw, sizeof g_ppw); return 0;
out:
    SecureZeroMemory(g_ppw, sizeof g_ppw);
    PostMessageW(g_win, WM_DONE, 0, (LPARAM)err); return 0;
}

/* ---------------------------------------------------------------- dialogs */
static wchar_t g_dlg_out[4][600]; static int g_dlg_done, g_dlg_n, g_dlg_choice;
static HWND g_dlg_edits[4], g_dlg_radio[3];
static LRESULT CALLBACK DlgProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CTLCOLOREDIT: SetTextColor((HDC)w, C_TXT); SetBkColor((HDC)w, C_FIELD); return (LRESULT)br_field;
    case WM_CTLCOLORSTATIC: case WM_CTLCOLORBTN: SetTextColor((HDC)w, C_TXT); SetBkColor((HDC)w, C_PANEL); return (LRESULT)br_panel;
    case WM_ERASEBKGND: { RECT r; GetClientRect(h, &r); FillRect((HDC)w, &r, br_panel); return 1; }
    case WM_COMMAND:
        if (LOWORD(w) == IDOK) {
            for (int i = 0; i < g_dlg_n; i++) GetWindowTextW(g_dlg_edits[i], g_dlg_out[i], 600);
            for (int i = 0; i < 3; i++) if (g_dlg_radio[i] && SendMessageW(g_dlg_radio[i], BM_GETCHECK, 0, 0) == BST_CHECKED) g_dlg_choice = i;
            g_dlg_done = 1; DestroyWindow(h); return 0;
        }
        if (LOWORD(w) == IDCANCEL) { g_dlg_done = -1; DestroyWindow(h); return 0; }
        break;
    case WM_CLOSE: g_dlg_done = -1; DestroyWindow(h); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}
/* n text fields (pwmask: bit i = hide typing), optional 3 radio choices */
static int ask(const wchar_t *title, const wchar_t *intro, int n, const wchar_t **labels, const wchar_t **init, int pwmask, const wchar_t **choices) {
    int W = 440, H = 116 + n * 58 + (choices ? 96 : 0) + (intro ? 48 : 0);
    RECT pr; GetWindowRect(g_win, &pr);
    HWND d = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, L"RzLDlg", title, WS_POPUP | WS_CAPTION | WS_SYSMENU,
                             (pr.left + pr.right - W) / 2, (pr.top + pr.bottom - H) / 2, W, H, g_win, NULL, GetModuleHandleW(NULL), NULL);
    int y = 14;
    if (intro) { HWND s = CreateWindowW(L"STATIC", intro, WS_CHILD | WS_VISIBLE, 18, y, W - 40, 44, d, NULL, NULL, NULL); SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE); y += 48; }
    g_dlg_n = n; memset(g_dlg_radio, 0, sizeof g_dlg_radio); g_dlg_choice = 0;
    for (int i = 0; i < n; i++) {
        HWND s = CreateWindowW(L"STATIC", labels[i], WS_CHILD | WS_VISIBLE, 18, y, W - 40, 18, d, NULL, NULL, NULL); SendMessageW(s, WM_SETFONT, (WPARAM)f_small, TRUE);
        g_dlg_edits[i] = CreateWindowExW(0, L"EDIT", init && init[i] ? init[i] : L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL | ((pwmask >> i) & 1 ? ES_PASSWORD : 0),
                                         18, y + 20, W - 40, 28, d, NULL, NULL, NULL);
        SendMessageW(g_dlg_edits[i], WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(g_dlg_edits[i], EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(6, 6));
        y += 58;
    }
    if (choices) for (int i = 0; i < 3; i++) {
        g_dlg_radio[i] = CreateWindowW(L"BUTTON", choices[i], WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTORADIOBUTTON | (i == 0 ? WS_GROUP : 0), 18, y, W - 40, 28, d, NULL, NULL, NULL);
        SendMessageW(g_dlg_radio[i], WM_SETFONT, (WPARAM)f_body, TRUE); y += 30;
    }
    if (choices) SendMessageW(g_dlg_radio[0], BM_SETCHECK, BST_CHECKED, 0);
    HWND ok = CreateWindowW(L"BUTTON", L"OK", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON, W - 220, y + 6, 92, 32, d, (HMENU)IDOK, NULL, NULL);
    HWND ca = CreateWindowW(L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP, W - 120, y + 6, 92, 32, d, (HMENU)IDCANCEL, NULL, NULL);
    SendMessageW(ok, WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(ca, WM_SETFONT, (WPARAM)f_body, TRUE);
    ShowWindow(d, SW_SHOW); EnableWindow(g_win, FALSE); if (n) SetFocus(g_dlg_edits[0]);
    g_dlg_done = 0; MSG msg;
    while (!g_dlg_done && GetMessageW(&msg, NULL, 0, 0) > 0) { if (!IsDialogMessageW(d, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); } }
    EnableWindow(g_win, TRUE); SetForegroundWindow(g_win);
    return g_dlg_done == 1;
}

/* ---------------------------------------------------------------- buttons */
enum { B_NONE, B_CLOSE, B_MIN, B_ADD, B_FIND, B_REMEMBER, B_PLAY, B_CREATE, B_EXPORT, B_SITE };
static RECT r_close = {CW - 50, 12, CW - 14, 46}, r_min = {CW - 92, 12, CW - 56, 46};
static RECT r_add = {40, 196, 200, 226}, r_find = {208, 196, 388, 226};
static RECT r_remember = {40, 418, 300, 444}, r_play = {40, 470, CW - 40, 520};
static RECT r_create = {40, 534, 270, 570}, r_export = {290, 534, CW - 40, 570}, r_site = {40, 590, CW - 40, 612};

static void set_msg(const wchar_t *m, COLORREF c) { wcsncpy(g_msg, m, 399); g_msg[399] = 0; g_msgc = c; InvalidateRect(g_win, NULL, FALSE); }

static void do_add(void) {
    const wchar_t *lab[] = {L"Invite code, server name or address (e.g. RZ-1A2B-3CD, myserver.duckdns.org)", L"Name to show (optional)"};
    if (!ask(L"Add a server", L"Ask the server owner for the invite code or the server's name.", 2, lab, NULL, 0, NULL)) return;
    char a[256], n[96], ip[64]; w2u(g_dlg_out[0], a, sizeof a); w2u(g_dlg_out[1], n, sizeof n); trim(a); trim(n);
    if (!a[0]) return;
    if (read_code(a, ip)) { if (!n[0]) snprintf(n, sizeof n, "%s", a); snprintf(a, sizeof a, "%s", ip); }
    add_srv(n, a, 0); for (int i = 0; i < g_nsrv; i++) if (!_stricmp(g_srv[i].addr, a)) g_cur = i;
    fill_combo(); server_changed();
}

static int read_fields(char *name, int nn, char *pw, int pn) {
    wchar_t w[256]; GetWindowTextW(g_ename, w, 128); w2u(w, name, nn); trim(name);
    GetWindowTextW(g_epw, w, 256); w2u(w, pw, pn); SecureZeroMemory(w, sizeof w);
    if (!name[0] || !pw[0]) { set_msg(L"Enter your account name and password.", C_BAD); return 0; }
    return 1;
}
static void do_play(void) {
    if (g_busy) return;
    if (!read_fields(g_pname, sizeof g_pname, g_ppw, sizeof g_ppw)) return;
    g_busy = 1; set_msg(L"Logging in\x2026", C_MUTE);
    CloseHandle(CreateThread(NULL, 0, play_thread, NULL, 0, NULL));
}
static char *read_upload(const wchar_t *filter, DWORD *len) {
    wchar_t fn[MAX_PATH] = L""; OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win; of.lpstrFilter = filter; of.lpstrFile = fn; of.nMaxFile = MAX_PATH; of.Flags = OFN_FILEMUSTEXIST;
    if (!GetOpenFileNameW(&of)) return NULL;
    HANDLE f = CreateFileW(fn, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL); if (f == INVALID_HANDLE_VALUE) return NULL;
    DWORD sz = GetFileSize(f, NULL), got = 0; char *b = (char *)malloc(sz + 1); ReadFile(f, b, sz, &got, NULL); CloseHandle(f); *len = got; return b;
}
static void urlenc(const char *s, char *o, int n) { int l = 0; for (; *s && l < n - 4; s++) { if (isalnum((unsigned char)*s)) o[l++] = *s; else l += sprintf(o + l, "%%%02X", (unsigned char)*s); } o[l] = 0; }
static void do_create(void) {
    const wchar_t *lab[] = {L"Account name (letters, numbers, spaces, - and _)", L"Password (4+ characters)", L"Password again"};
    const wchar_t *ch[] = {L"Fresh start", L"Bring my official account (backup file from Rozefield Backup)", L"Bring my account from another Rozefield server (.rzaccount)"};
    if (!ask(L"Create account", NULL, 3, lab, NULL, 6, ch)) return;
    if (wcscmp(g_dlg_out[1], g_dlg_out[2])) { set_msg(L"The two passwords don't match.", C_BAD); return; }
    char name[128], pw[256], ip[64]; w2u(g_dlg_out[0], name, sizeof name); w2u(g_dlg_out[1], pw, sizeof pw); trim(name);
    SecureZeroMemory(g_dlg_out, sizeof g_dlg_out);
    int choice = g_dlg_choice;
    if (!resolve(g_srv[g_cur].addr, ip)) { set_msg(L"Can't find that server name.", C_BAD); return; }
    char body[400]; int bl = snprintf(body, sizeof body, "%s\n%s", name, pw); char *r;
    if (choice == 0) r = http(ip, HTTP_PORT, "POST", "/rozefield/register", body, bl, NULL, 6000);
    else {
        DWORD len; char *data = read_upload(choice == 1 ? L"Official backup (*.rzsave)\0*.rzsave\0All files\0*.*\0" : L"Rozefield account (*.rzaccount)\0*.rzaccount\0All files\0*.*\0", &len);
        if (!data) { SecureZeroMemory(pw, sizeof pw); return; }
        set_msg(L"Bringing your account over\x2026", C_MUTE); UpdateWindow(g_win);
        char path[400], en[300]; urlenc(name, en, sizeof en); snprintf(path, sizeof path, "/rozefield/import?name=%s", en);
        r = http(ip, HTTP_PORT, "POST", path, data, (int)len, NULL, 120000); free(data);
        if (r && !strncmp(r, "OK|", 3)) { free(r); r = http(ip, HTTP_PORT, "POST", "/rozefield/login", body, bl, NULL, 6000); }   /* first log-in sets the password */
    }
    SecureZeroMemory(body, sizeof body);
    if (!r) { set_msg(L"The server didn't answer.", C_BAD); SecureZeroMemory(pw, sizeof pw); return; }
    if (!strncmp(r, "OK|", 3)) {
        wchar_t w[256]; u2w(name, w, 128); SetWindowTextW(g_ename, w); u2w(pw, w, 256); SetWindowTextW(g_epw, w); SecureZeroMemory(w, sizeof w);
        set_msg(choice ? L"Your account is here. Press Play." : L"Account created. Press Play.", C_OK);
    } else { wchar_t w[400]; u2w(strchr(r, '|') ? strchr(r, '|') + 1 : r, w, 400); set_msg(w, C_BAD); }
    free(r); SecureZeroMemory(pw, sizeof pw);
}
static void do_export(void) {
    char name[128], pw[256], ip[64]; if (!read_fields(name, sizeof name, pw, sizeof pw)) return;
    if (!resolve(g_srv[g_cur].addr, ip)) { set_msg(L"Can't find that server name.", C_BAD); return; }
    char body[400]; int bl = snprintf(body, sizeof body, "%s\n%s", name, pw), len = 0; SecureZeroMemory(pw, sizeof pw);
    char *r = http(ip, HTTP_PORT, "POST", "/rozefield/export_account", body, bl, &len, 30000); SecureZeroMemory(body, sizeof body);
    if (!r) { set_msg(L"The server didn't answer.", C_BAD); return; }
    if (strncmp(r, "{", 1)) { wchar_t w[400]; u2w(strchr(r, '|') ? strchr(r, '|') + 1 : r, w, 400); set_msg(w, C_BAD); free(r); return; }
    wchar_t fn[MAX_PATH]; u2w(name, fn, 100); wcscat(fn, L".rzaccount");
    OPENFILENAMEW of = {0}; of.lStructSize = sizeof of; of.hwndOwner = g_win; of.lpstrFilter = L"Rozefield account (*.rzaccount)\0*.rzaccount\0"; of.lpstrFile = fn; of.nMaxFile = MAX_PATH; of.lpstrDefExt = L"rzaccount"; of.Flags = OFN_OVERWRITEPROMPT;
    if (GetSaveFileNameW(&of)) {
        HANDLE f = CreateFileW(fn, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL); DWORD w = 0;
        if (f != INVALID_HANDLE_VALUE) { WriteFile(f, r, len, &w, NULL); CloseHandle(f); }
        set_msg(w == (DWORD)len ? L"Saved. On another Rozefield server: Create account > Bring my account from another Rozefield server." : L"Couldn't save the file.", w == (DWORD)len ? C_OK : C_BAD);
    }
    free(r);
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
static void txt(HDC dc, HFONT f, COLORREF c, RECT r, const wchar_t *s, UINT fmt) { SelectObject(dc, f); SetTextColor(dc, c); SetBkMode(dc, TRANSPARENT); DrawTextW(dc, s, -1, &r, fmt | DT_NOPREFIX); }
static void pill(HDC dc, RECT r, int primary, int hover, int enabled, const wchar_t *label) {
    int rad = (r.bottom - r.top) / 2 + 4;
    if (primary) fill(dc, r, !enabled ? RGB(166, 216, 222) : hover ? RGB(14, 160, 176) : C_ACC, rad);
    else { fill(dc, r, hover ? RGB(232, 246, 248) : C_PANEL, rad); outline(dc, r, C_LINE, rad); }
    txt(dc, primary ? f_btn : f_small, primary ? RGB(255, 255, 255) : C_TXT, r, label, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}
static void label(HDC dc, int y, const wchar_t *s) { RECT r = {40, y, CW - 40, y + 20}; txt(dc, f_small, C_MUTE, r, s, DT_LEFT | DT_SINGLELINE); }

static void paint(HWND h) {
    PAINTSTRUCT ps; HDC wdc = BeginPaint(h, &ps);
    HDC dc = CreateCompatibleDC(wdc); HBITMAP bb = CreateCompatibleBitmap(wdc, CW, CH); HGDIOBJ ob = SelectObject(dc, bb);
    RECT all = {0, 0, CW, CH}; fill(dc, all, C_INK, 0);
    RECT card = {16, 16, CW - 16, CH - 16}; fill(dc, card, C_PANEL, 20); outline(dc, card, C_LINE, 20);
    RECT rt = {40, 34, CW - 100, 80}; txt(dc, f_title, C_TXT, rt, L"Rozefield", DT_LEFT | DT_SINGLELINE);
    RECT rs = {42, 80, CW - 40, 100}; txt(dc, f_small, C_MUTE, rs, L"Private OverField servers", DT_LEFT | DT_SINGLELINE);
    if (g_hover == B_CLOSE) fill(dc, r_close, RGB(200, 64, 76), 8);
    if (g_hover == B_MIN) fill(dc, r_min, C_TILE, 8);
    { HPEN p = CreatePen(PS_SOLID, 2, C_TXT); HGDIOBJ o = SelectObject(dc, p);
      int cx = (r_close.left + r_close.right) / 2, cy = (r_close.top + r_close.bottom) / 2;
      MoveToEx(dc, cx - 6, cy - 6, NULL); LineTo(dc, cx + 7, cy + 7); MoveToEx(dc, cx + 6, cy - 6, NULL); LineTo(dc, cx - 7, cy + 7);
      cx = (r_min.left + r_min.right) / 2; MoveToEx(dc, cx - 7, cy, NULL); LineTo(dc, cx + 8, cy); SelectObject(dc, o); DeleteObject(p); }
    label(dc, 118, L"Server");
    pill(dc, r_add, 0, g_hover == B_ADD, 1, L"Add server\x2026");
    pill(dc, r_find, 0, g_hover == B_FIND, 1, L"Find on my network");
    { HBRUSH b = CreateSolidBrush(g_statc); HGDIOBJ o = SelectObject(dc, b); HPEN pn = CreatePen(PS_SOLID, 1, g_statc); HGDIOBJ op = SelectObject(dc, pn);
      Ellipse(dc, 41, 245, 51, 255); SelectObject(dc, o); SelectObject(dc, op); DeleteObject(b); DeleteObject(pn);
      RECT r = {58, 238, CW - 40, 262}; txt(dc, f_small, g_statc == C_MUTE ? C_MUTE : g_statc == C_OK ? RGB(30, 140, 86) : C_BAD, r, g_status, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS); }
    label(dc, 282, L"Account name");
    label(dc, 346, L"Password");
    { RECT box = {r_remember.left, r_remember.top + 4, r_remember.left + 18, r_remember.top + 22};
      if (g_remember) fill(dc, box, C_ACC, 6); else { fill(dc, box, C_PANEL, 6); outline(dc, box, C_LINE, 6); }
      if (g_remember) { HPEN p = CreatePen(PS_SOLID, 2, RGB(255, 255, 255)); HGDIOBJ o = SelectObject(dc, p);
                        MoveToEx(dc, box.left + 4, box.top + 9, NULL); LineTo(dc, box.left + 8, box.top + 13); LineTo(dc, box.left + 14, box.top + 5); SelectObject(dc, o); DeleteObject(p); }
      RECT r = {r_remember.left + 28, r_remember.top, r_remember.right, r_remember.bottom}; txt(dc, f_small, C_TXT, r, L"Remember me on this PC", DT_LEFT | DT_VCENTER | DT_SINGLELINE); }
    { RECT r = {40, 446, CW - 40, 468}; txt(dc, f_small, g_msgc, r, g_msg, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS); }
    pill(dc, r_play, 1, g_hover == B_PLAY, !g_busy, g_busy ? L"Starting\x2026" : L"Play");
    pill(dc, r_create, 0, g_hover == B_CREATE, 1, L"Create account");
    pill(dc, r_export, 0, g_hover == B_EXPORT, 1, L"Export my account");
    RECT rf = r_site; txt(dc, f_small, g_hover == B_SITE ? C_ACC : C_MUTE, rf, L"Save your official account before 8 Feb 2027 with Rozefield Backup", DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    BitBlt(wdc, 0, 0, CW, CH, dc, 0, 0, SRCCOPY);
    SelectObject(dc, ob); DeleteObject(bb); DeleteDC(dc); EndPaint(h, &ps);
}
static int hit(int x, int y) {
    POINT pt = {x, y};
    RECT rs[] = {r_close, r_min, r_add, r_find, r_remember, r_play, r_create, r_export};
    int ids[] = {B_CLOSE, B_MIN, B_ADD, B_FIND, B_REMEMBER, B_PLAY, B_CREATE, B_EXPORT};
    for (int i = 0; i < 8; i++) if (PtInRect(&rs[i], pt)) return ids[i];
    return B_NONE;
}
static void click(int b) {
    switch (b) {
    case B_CLOSE: PostMessageW(g_win, WM_CLOSE, 0, 0); break;
    case B_MIN: ShowWindow(g_win, SW_MINIMIZE); break;
    case B_ADD: do_add(); break;
    case B_FIND: set_msg(L"Looking for servers on your network\x2026", C_MUTE); UpdateWindow(g_win); find_nearby(); break;
    case B_REMEMBER: g_remember = !g_remember; if (!g_remember) remember(g_srv[g_cur].addr, "", NULL); break;
    case B_PLAY: do_play(); break;
    case B_CREATE: do_create(); break;
    case B_EXPORT: do_export(); break;
    }
    InvalidateRect(g_win, NULL, FALSE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: paint(h); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLOREDIT: case WM_CTLCOLORLISTBOX: SetTextColor((HDC)w, C_TXT); SetBkColor((HDC)w, C_FIELD); return (LRESULT)br_field;
    case WM_COMMAND:
        if ((HWND)l == g_combo && HIWORD(w) == CBN_SELCHANGE) { int i = (int)SendMessageW(g_combo, CB_GETCURSEL, 0, 0); if (i >= 0 && i < g_nsrv) { g_cur = i; server_changed(); } }
        return 0;
    case WM_INFO: InvalidateRect(h, NULL, FALSE); return 0;
    case WM_DONE:
        if (w == 1) { ShowWindow(h, SW_HIDE); return 0; }
        g_busy = 0;
        if (w == 2) { set_msg(L"The game closed. Press Play to start again.", C_MUTE); ShowWindow(h, SW_SHOW); SetForegroundWindow(h); }
        else if (l) { set_msg((wchar_t *)l, C_BAD); free((void *)l); }
        return 0;
    case WM_KEYDOWN: if (w == VK_RETURN) do_play(); return 0;
    case WM_NCHITTEST: {
        LRESULT r = DefWindowProcW(h, m, w, l);
        if (r == HTCLIENT) { POINT pt = {(short)LOWORD(l), (short)HIWORD(l)}; ScreenToClient(h, &pt); if (pt.y < 110 && hit(pt.x, pt.y) == B_NONE) return HTCAPTION; }
        return r; }
    case WM_MOUSEMOVE: {
        int b = hit((short)LOWORD(l), (short)HIWORD(l));
        if (b != g_hover) { g_hover = b; TRACKMOUSEEVENT te = {sizeof te, TME_LEAVE, h, 0}; TrackMouseEvent(&te); InvalidateRect(h, NULL, FALSE); }
        return 0; }
    case WM_MOUSELEAVE: g_hover = 0; InvalidateRect(h, NULL, FALSE); return 0;
    case WM_SETCURSOR: if (LOWORD(l) == HTCLIENT && g_hover) { SetCursor(LoadCursor(NULL, IDC_HAND)); return TRUE; } break;
    case WM_LBUTTONUP: click(hit((short)LOWORD(l), (short)HIWORD(l))); return 0;
    case WM_CLOSE: DestroyWindow(h); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    CreateMutexW(NULL, TRUE, L"Local\\RozefieldLauncher");
    if (GetLastError() == ERROR_ALREADY_EXISTS) { HWND w = FindWindowW(L"RozefieldLauncher", NULL); if (w) { ShowWindow(w, SW_SHOW); ShowWindow(w, SW_RESTORE); SetForegroundWindow(w); } return 0; }
    GetModuleFileNameA(NULL, g_dir, MAX_PATH); char *sl = strrchr(g_dir, '\\'); if (sl) sl[1] = 0;
    { char ad[MAX_PATH]; if (SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, ad) == S_OK) { snprintf(g_ini, sizeof g_ini, "%s\\Rozefield", ad); CreateDirectoryA(g_ini, NULL); strcat(g_ini, "\\launcher.ini"); }
      else snprintf(g_ini, sizeof g_ini, "%srozefield_launcher.ini", g_dir); }
    WSADATA wd; WSAStartup(MAKEWORD(2, 2), &wd);
    g_remember = GetPrivateProfileIntA("last", "remember", 1, g_ini);
    f_title = CreateFontW(-40, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_h = CreateFontW(-18, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_body = CreateFontW(-17, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_small = CreateFontW(-14, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_btn = CreateFontW(-20, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    br_panel = CreateSolidBrush(C_PANEL); br_field = CreateSolidBrush(C_FIELD);
    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = hi; wc.lpszClassName = L"RozefieldLauncher"; wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIconW(hi, MAKEINTRESOURCEW(1)); RegisterClassW(&wc);
    WNDCLASSW dc = {0}; dc.lpfnWndProc = DlgProc; dc.hInstance = hi; dc.lpszClassName = L"RzLDlg"; dc.hCursor = LoadCursor(NULL, IDC_ARROW); RegisterClassW(&dc);
    g_win = CreateWindowExW(WS_EX_APPWINDOW, L"RozefieldLauncher", L"Rozefield", WS_POPUP | WS_MINIMIZEBOX | WS_SYSMENU | WS_CLIPCHILDREN,
                            (GetSystemMetrics(SM_CXSCREEN) - CW) / 2, (GetSystemMetrics(SM_CYSCREEN) - CH) / 2, CW, CH, NULL, NULL, hi, NULL);
    SetWindowRgn(g_win, CreateRoundRectRgn(0, 0, CW + 1, CH + 1, 22, 22), TRUE);
    g_combo = CreateWindowExW(0, L"COMBOBOX", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, 40, 140, CW - 80, 300, g_win, NULL, hi, NULL);
    g_ename = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 40, 304, CW - 80, 32, g_win, NULL, hi, NULL);
    g_epw = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL | ES_PASSWORD, 40, 368, CW - 80, 32, g_win, NULL, hi, NULL);
    HWND ctl[] = {g_combo, g_ename, g_epw};
    for (int i = 0; i < 3; i++) SendMessageW(ctl[i], WM_SETFONT, (WPARAM)f_body, TRUE);
    SendMessageW(g_ename, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(8, 8)); SendMessageW(g_epw, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(8, 8));
    SendMessageW(g_ename, EM_SETCUEBANNER, TRUE, (LPARAM)L"Your account name"); SendMessageW(g_ename, EM_LIMITTEXT, 24, 0);
    load_servers(); fill_combo();
    ShowWindow(g_win, show); UpdateWindow(g_win);
    server_changed();
    SetFocus(GetWindowTextLengthW(g_ename) ? g_epw : g_ename);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN && (msg.hwnd == g_ename || msg.hwnd == g_epw)) { do_play(); continue; }
        if (!IsDialogMessageW(g_win, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    }
    { char v[8]; snprintf(v, sizeof v, "%d", g_remember); WritePrivateProfileStringA("last", "remember", v, g_ini); }
    if (g_lookup != INVALID_SOCKET) closesocket(g_lookup);
    return 0;
}
