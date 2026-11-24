/* RozefieldBackup.exe - save your OverField account while the official server is still online.
 *
 * Click "Open OverField (Official)": the game starts and logs in to the official server as usual, but its
 * connection passes through this window, which records what the server tells the game about your account.
 * Nothing is changed or sent on your behalf. Your login token is not saved. When you close the game (or press
 * "Save backup") you get  backups\<name>_<date>.rzsave  - import it into Rozefield from its login window.
 *
 * How: Config.txt is switched to UseCustomConfig/RemoteServerIP=127.0.0.1 just long enough for the game to read it
 * (put back as soon as the game has asked for the server list). Dispatch HTTP (:18881) is forwarded to the official
 * dispatch server; the game server address in its answer is pointed at the local relay (:11001), which forwards
 * every byte to the official game server and keeps a copy.
 *
 * File format (RZSAVE2): "RZSAVE2\n" + JSON meta line + records {u8 dir(0=client,1=server), u16 conn, f64 time,
 * u32 len, frame bytes as on the wire}.
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 rozefield_backup.c -o RozefieldBackup.exe
 *        -lws2_32 -lcomdlg32 -lshell32 -lole32 -luser32 -lgdi32 -ladvapi32 -Wl,--subsystem,windows
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <tlhelp32.h>

#define DISPATCH_HOST "dsp-global-of.inutan.com"
#define DISPATCH_PORT 18881
#define GATE_PORT 11001
#define HTTPDNS_IP "8.134.240.36"
#define WM_LOG (WM_APP + 1)
#define WM_CHECK (WM_APP + 2)
#define WM_GAMEEXIT (WM_APP + 3)

static HWND g_win, g_log, g_check, g_edit, g_open, g_save, g_status;
static char g_exedir[MAX_PATH], g_game[MAX_PATH], g_cfg[MAX_PATH], g_cfgbak[MAX_PATH];
static char g_upstream_ip[64];
static char g_gate_ip[64]; static int g_gate_port;
static CRITICAL_SECTION g_cs;
static FILE *g_tmp; static char g_tmppath[MAX_PATH];
static long g_frames; static int g_conns;
static char g_player[128];
static volatile int g_running, g_cfg_patched, g_sdk_swapped;
static HANDLE g_game_proc;

/* ------------------------------------------------------------------ UI helpers */
static char g_logpath[MAX_PATH];
static void ui_log(const char *fmt, ...) {
    char b[1024]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    if (g_logpath[0]) {   /* RozefieldBackup.log next to the exe: send it when something goes wrong */
        FILE *lf = fopen(g_logpath, "ab");
        if (lf) { SYSTEMTIME t; GetLocalTime(&t); fprintf(lf, "%02d:%02d:%02d  %s\r\n", t.wHour, t.wMinute, t.wSecond, b); fclose(lf); }
    }
    wchar_t *w = (wchar_t *)malloc(2048 * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, b, -1, w, 2048);
    PostMessageW(g_win, WM_LOG, 0, (LPARAM)w);
}

struct check { const char *label; const char *how; int msg_id; int done; };
static struct check CHECKS[] = {
    {"Account, characters, bag, quests, story", "log in", 1006, 0},
    {"Garden Plaza layout", "go to your own Garden Plaza", 1016, 0},
    {"Achievements", "Manual > Achievements: open every tab", 1762, 0},
    {"Life skills", "Life: open each life skill", 1370, 0},
    {"Life collection book", "Life: open each collection book", 1366, 0},
    {"Exploration manual", "open the Manual", 1862, 0},
    {"Poster album", "open the Poster album", 1424, 0},
    {"Character achievements", "Characters: open each character's achievement page", 1480, 0},
    {"Friends", "open the Friends list", 1740, 0},
    {"Plaza presets", "in decorate mode open Preset Decor", 2624, 0},
    {"Mail", "open the Mailbox", 1122, 0},
};
#define NCHECK (int)(sizeof CHECKS / sizeof CHECKS[0])

static void refresh_checks(void) {
    SendMessageW(g_check, LB_RESETCONTENT, 0, 0);
    for (int i = 0; i < NCHECK; i++) {
        char b[300]; wchar_t w[300];
        snprintf(b, sizeof b, "%s  %s   (%s)", CHECKS[i].done ? "[saved]" : "[  -  ]", CHECKS[i].label, CHECKS[i].how);
        MultiByteToWideChar(CP_UTF8, 0, b, -1, w, 300);
        SendMessageW(g_check, LB_ADDSTRING, 0, (LPARAM)w);
    }
}

/* ------------------------------------------------------------------ settings */
static void ini_path(char *out) { snprintf(out, MAX_PATH, "%sRozefieldBackup.ini", g_exedir); }

static int has_launcher(const char *dir) {
    char p[MAX_PATH]; snprintf(p, sizeof p, "%s\\launcher.exe", dir);
    return GetFileAttributesA(p) != INVALID_FILE_ATTRIBUTES;
}

static void find_game(void) {
    char ini[MAX_PATH]; ini_path(ini);
    GetPrivateProfileStringA("game", "folder", "", g_game, sizeof g_game, ini);
    if (g_game[0] && has_launcher(g_game)) return;
    g_game[0] = 0;
    /* Steam libraries: <SteamPath>\steamapps\libraryfolders.vdf lists every library "path" */
    char steam[MAX_PATH] = ""; DWORD sz = sizeof steam;
    if (RegGetValueA(HKEY_CURRENT_USER, "Software\\Valve\\Steam", "SteamPath", RRF_RT_REG_SZ, NULL, steam, &sz) == ERROR_SUCCESS) {
        char libs[32][MAX_PATH]; int n = 0;
        snprintf(libs[n++], MAX_PATH, "%s", steam);
        char vdf[MAX_PATH]; snprintf(vdf, sizeof vdf, "%s\\steamapps\\libraryfolders.vdf", steam);
        FILE *f = fopen(vdf, "rb");
        if (f) {
            char line[1024];
            while (fgets(line, sizeof line, f) && n < 32) {
                char *k = strstr(line, "\"path\"");
                if (!k) continue;
                char *a = strchr(k + 6, '"'); if (!a) continue;
                char *e = strchr(a + 1, '"'); if (!e) continue;
                *e = 0; char *o = libs[n]; int j = 0;
                for (char *c = a + 1; *c && j < MAX_PATH - 1; c++) { if (c[0] == '\\' && c[1] == '\\') c++; o[j++] = *c; }
                o[j] = 0; n++;
            }
            fclose(f);
        }
        for (int i = 0; i < n; i++) {
            char p[MAX_PATH]; snprintf(p, sizeof p, "%s\\steamapps\\common\\OverField", libs[i]);
            for (char *c = p; *c; c++) if (*c == '/') *c = '\\';
            if (has_launcher(p)) { snprintf(g_game, sizeof g_game, "%s", p); return; }
        }
    }
    const char *guess[] = {"C:\\Program Files (x86)\\Steam\\steamapps\\common\\OverField", "D:\\SteamLibrary\\steamapps\\common\\OverField",
                           "E:\\SteamLibrary\\steamapps\\common\\OverField", "H:\\SteamLibrary\\steamapps\\common\\OverField"};
    for (int i = 0; i < 4; i++) if (has_launcher(guess[i])) { snprintf(g_game, sizeof g_game, "%s", guess[i]); return; }
}

/* ------------------------------------------------------------------ Config.txt / login window switch */
static int patch_config(void) {
    snprintf(g_cfg, sizeof g_cfg, "%s\\launcher_Data\\StreamingAssets\\Config.txt", g_game);
    snprintf(g_cfgbak, sizeof g_cfgbak, "%s.rzbackup", g_cfg);
    if (GetFileAttributesA(g_cfgbak) == INVALID_FILE_ATTRIBUTES && !CopyFileA(g_cfg, g_cfgbak, TRUE)) return 0;
    FILE *f = fopen(g_cfgbak, "rb"); if (!f) return 0;
    static char in[65536], out[70000]; size_t n = fread(in, 1, sizeof in - 1, f); fclose(f); in[n] = 0;
    char *o = out; o[0] = 0;
    int seen_c = 0, seen_r = 0;
    for (char *line = in; *line;) {
        char *nl = strchr(line, '\n'); size_t len = nl ? (size_t)(nl - line + 1) : strlen(line);
        char *t = line; while (*t == ' ' || *t == '\t') t++;
        if (_strnicmp(t, "UseCustomConfig", 15) == 0) { o += sprintf(o, "UseCustomConfig = TRUE\r\n"); seen_c = 1; }
        else if (_strnicmp(t, "RemoteServerIP", 14) == 0) { o += sprintf(o, "RemoteServerIP = 127.0.0.1\r\n"); seen_r = 1; }
        else { memcpy(o, line, len); o += len; *o = 0; }
        line += len;
    }
    if (!seen_c) o += sprintf(o, "\r\nUseCustomConfig = TRUE\r\n");
    if (!seen_r) o += sprintf(o, "RemoteServerIP = 127.0.0.1\r\n");
    f = fopen(g_cfg, "wb"); if (!f) return 0;
    fwrite(out, 1, o - out, f); fclose(f);
    g_cfg_patched = 1;
    return 1;
}

static void restore_config(void) {
    if (GetFileAttributesA(g_cfgbak) != INVALID_FILE_ATTRIBUTES) {
        if (CopyFileA(g_cfgbak, g_cfg, FALSE)) DeleteFileA(g_cfgbak);
    }
    g_cfg_patched = 0;
}

/* A Rozefield login window (PCSDKUI.exe with PCSDKUI.exe.orig beside it) would log in to Rozefield: use the
 * official one while backing up. */
static void sdk_official(int on) {
    char cur[MAX_PATH], orig[MAX_PATH], rz[MAX_PATH];
    snprintf(cur, sizeof cur, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe", g_game);
    snprintf(orig, sizeof orig, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe.orig", g_game);
    snprintf(rz, sizeof rz, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe.rozefield", g_game);
    if (on) {
        if (GetFileAttributesA(orig) != INVALID_FILE_ATTRIBUTES && GetFileAttributesA(rz) == INVALID_FILE_ATTRIBUTES) {
            if (CopyFileA(cur, rz, FALSE) && CopyFileA(orig, cur, FALSE)) g_sdk_swapped = 1;
        }
    } else if (GetFileAttributesA(rz) != INVALID_FILE_ATTRIBUTES) {
        if (CopyFileA(rz, cur, FALSE)) { DeleteFileA(rz); g_sdk_swapped = 0; }
    }
}

static void restore_all(void) {
    char cfg[MAX_PATH]; snprintf(cfg, sizeof cfg, "%s\\launcher_Data\\StreamingAssets\\Config.txt", g_game);
    snprintf(g_cfg, sizeof g_cfg, "%s", cfg); snprintf(g_cfgbak, sizeof g_cfgbak, "%s.rzbackup", cfg);
    restore_config();
    sdk_official(0);
}

/* ------------------------------------------------------------------ recording */
static void record(int dir, int conn, const unsigned char *raw, uint32_t len) {
    EnterCriticalSection(&g_cs);
    if (g_tmp) {
        FILETIME ft; GetSystemTimeAsFileTime(&ft);
        double t = ((((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7) - 11644473600.0;
        unsigned char d = (unsigned char)dir; uint16_t c = (uint16_t)conn;
        fwrite(&d, 1, 1, g_tmp); fwrite(&c, 2, 1, g_tmp); fwrite(&t, 8, 1, g_tmp); fwrite(&len, 4, 1, g_tmp);
        fwrite(raw, 1, len, g_tmp);
        g_frames++;
    }
    LeaveCriticalSection(&g_cs);
}

static uint64_t rd_varint(const unsigned char **p, const unsigned char *e) {
    uint64_t v = 0; int s = 0;
    while (*p < e) { unsigned char b = *(*p)++; v |= (uint64_t)(b & 0x7f) << s; if (!(b & 0x80)) break; s += 7; }
    return v;
}

struct head { uint64_t packet_id, msg_id, flag, body_len, seq; };
static void parse_head(const unsigned char *p, const unsigned char *e, struct head *h) {
    memset(h, 0, sizeof *h);
    while (p < e) {
        uint64_t k = rd_varint(&p, e); int f = (int)(k >> 3), wt = (int)(k & 7);
        if (wt == 0) {
            uint64_t v = rd_varint(&p, e);
            if (f == 1) h->packet_id = v; else if (f == 2) h->msg_id = v; else if (f == 3) h->flag = v;
            else if (f == 4) h->body_len = v; else if (f == 6) h->seq = v;
        } else if (wt == 2) { uint64_t l = rd_varint(&p, e); p += l; }
        else if (wt == 1) p += 8; else if (wt == 5) p += 4; else break;
    }
}

/* raw snappy (only needed to read the player's name from PlayerMainDataRsp) */
static unsigned char *snappy_raw(const unsigned char *s, size_t n, size_t *outlen) {
    const unsigned char *e = s + n;
    uint64_t ulen = rd_varint(&s, e);
    if (ulen > (64u << 20)) return NULL;
    unsigned char *o = (unsigned char *)malloc(ulen + 1); size_t op = 0;
    while (s < e && op <= ulen) {
        unsigned char tag = *s++; size_t len, off;
        switch (tag & 3) {
        case 0:
            len = (tag >> 2) + 1;
            if (len > 60) { int nb = (int)len - 60; len = 0; for (int i = 0; i < nb && s < e; i++) len |= (size_t)(*s++) << (8 * i); len++; }
            if (s + len > e || op + len > ulen) { free(o); return NULL; }
            memcpy(o + op, s, len); s += len; op += len; continue;
        case 1: if (s >= e) { free(o); return NULL; } len = 4 + ((tag >> 2) & 7); off = ((size_t)(tag >> 5) << 8) | *s++; break;
        case 2: if (s + 2 > e) { free(o); return NULL; } len = (tag >> 2) + 1; off = s[0] | (s[1] << 8); s += 2; break;
        default: if (s + 4 > e) { free(o); return NULL; } len = (tag >> 2) + 1; off = s[0] | (s[1] << 8) | (s[2] << 16) | ((size_t)s[3] << 24); s += 4; break;
        }
        if (off == 0 || off > op || op + len > ulen) { free(o); return NULL; }
        for (size_t i = 0; i < len; i++, op++) o[op] = o[op - off];
    }
    *outlen = op; return o;
}

static void find_name(const unsigned char *body, size_t n, int compressed) {
    size_t len = n; unsigned char *buf = NULL; const unsigned char *p = body;
    if (compressed) { buf = snappy_raw(body, n, &len); if (!buf) return; p = buf; }
    const unsigned char *e = p + len;
    while (p < e) {
        uint64_t k = rd_varint(&p, e); int f = (int)(k >> 3), wt = (int)(k & 7);
        if (wt == 0) rd_varint(&p, e);
        else if (wt == 2) {
            uint64_t l = rd_varint(&p, e);
            if (f == 3 && l < sizeof g_player) { memcpy(g_player, p, l); g_player[l] = 0; break; }
            p += l;
        } else if (wt == 1) p += 8; else if (wt == 5) p += 4; else break;
    }
    free(buf);
}

/* splits a byte stream into frames, records them (login token stripped), updates the checklist */
struct framer { unsigned char *buf; size_t len, cap; int dir, conn; };
static void framer_feed(struct framer *fr, const char *data, int n) {
    if (fr->len + n > fr->cap) { fr->cap = (fr->len + n) * 2; fr->buf = (unsigned char *)realloc(fr->buf, fr->cap); }
    memcpy(fr->buf + fr->len, data, n); fr->len += n;
    size_t off = 0;
    while (fr->len - off >= 2) {
        size_t hl = (fr->buf[off] << 8) | fr->buf[off + 1];
        if (fr->len - off < 2 + hl) break;
        struct head h; parse_head(fr->buf + off + 2, fr->buf + off + 2 + hl, &h);
        size_t tot = 2 + hl + h.body_len;
        if (fr->len - off < tot) break;
        const unsigned char *frame = fr->buf + off;
        if (fr->dir == 0 && h.msg_id == 1001) record(0, fr->conn, frame, (uint32_t)(2 + hl));  /* VerifyLoginTokenReq: header only */
        else record(fr->dir, fr->conn, frame, (uint32_t)tot);
        if (fr->dir == 1) {
            if (h.msg_id == 1006 && !g_player[0]) {
                find_name(frame + 2 + hl, h.body_len, h.flag == 1);
                if (g_player[0]) ui_log("Logged in as %s. Now open the menus in the list so they are saved too.", g_player);
            }
            for (int i = 0; i < NCHECK; i++)
                if (!CHECKS[i].done && CHECKS[i].msg_id == (int)h.msg_id) { CHECKS[i].done = 1; PostMessageW(g_win, WM_CHECK, 0, 0); }
        }
        off += tot;
    }
    memmove(fr->buf, fr->buf + off, fr->len - off); fr->len -= off;
}

/* ------------------------------------------------------------------ networking */
static SOCKET tcp_connect(const char *ip, int port) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port);
    inet_pton(AF_INET, ip, &a.sin_addr);
    if (connect(s, (struct sockaddr *)&a, sizeof a) != 0) { closesocket(s); return INVALID_SOCKET; }
    return s;
}

static SOCKET tcp_listen(int port) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s, (struct sockaddr *)&a, sizeof a) != 0 || listen(s, 16) != 0) { closesocket(s); return INVALID_SOCKET; }
    return s;
}

/* read until the peer closes (HTTP/1.0 style); returns malloc'd buffer */
static char *read_all(SOCKET s, int *outlen) {
    int cap = 65536, len = 0, r; char *b = (char *)malloc(cap + 1);
    while ((r = recv(s, b + len, cap - len, 0)) > 0) { len += r; if (len == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
    b[len] = 0; *outlen = len; return b;
}

static int resolve_dispatch(void) {
    struct addrinfo hints = {0}, *res = NULL; hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(DISPATCH_HOST, NULL, &hints, &res) == 0 && res) {
        inet_ntop(AF_INET, &((struct sockaddr_in *)res->ai_addr)->sin_addr, g_upstream_ip, sizeof g_upstream_ip);
        freeaddrinfo(res); return 1;
    }
    SOCKET s = tcp_connect(HTTPDNS_IP, 80);   /* the game's own HTTPDNS service */
    if (s == INVALID_SOCKET) return 0;
    const char *req = "GET /resolve?domain=" DISPATCH_HOST " HTTP/1.0\r\nHost: " HTTPDNS_IP "\r\n\r\n";
    send(s, req, (int)strlen(req), 0);
    int n; char *b = read_all(s, &n); closesocket(s);
    char *ips = strstr(b, "\"ips\""); int ok = 0;
    if (ips) { char *q = strchr(ips + 5, '"'); if (q) { char *q2 = strchr(q + 1, '"'); if (q2 && q2 - q - 1 < 63) { memcpy(g_upstream_ip, q + 1, q2 - q - 1); g_upstream_ip[q2 - q - 1] = 0; ok = 1; } } }
    free(b); return ok;
}

static int find_json_str(const char *body, const char *key, char *out, int outsz) {
    char k[64]; snprintf(k, sizeof k, "\"%s\"", key);
    const char *p = strstr(body, k); if (!p) return 0;
    p = strchr(p + strlen(k), ':'); if (!p) return 0; p++;
    while (*p == ' ') p++;
    if (*p == '"') { p++; const char *e = strchr(p, '"'); if (!e || e - p >= outsz) return 0; memcpy(out, p, e - p); out[e - p] = 0; return 1; }
    int i = 0; while ((*p >= '0' && *p <= '9') && i < outsz - 1) out[i++] = *p++; out[i] = 0; return i > 0;
}

static char *replace_json_value(const char *body, const char *key, const char *newval, int quoted) {
    char k[64]; snprintf(k, sizeof k, "\"%s\"", key);
    const char *p = strstr(body, k); if (!p) return _strdup(body);
    const char *v = strchr(p + strlen(k), ':'); if (!v) return _strdup(body); v++;
    while (*v == ' ') v++;
    const char *e;
    if (*v == '"') { e = strchr(v + 1, '"'); if (!e) return _strdup(body); e++; }
    else { e = v; while (*e && *e != ',' && *e != '}') e++; }
    size_t n = strlen(body) + strlen(newval) + 8; char *o = (char *)malloc(n);
    snprintf(o, n, "%.*s%s%s%s%s", (int)(v - body), body, quoted ? "\"" : "", newval, quoted ? "\"" : "", e);
    return o;
}

/* chunked transfer -> plain body (in place) */
static int dechunk(char *b, int n) {
    char *in = b, *out = b, *end = b + n;
    while (in < end) {
        long sz = strtol(in, NULL, 16);
        char *crlf = strstr(in, "\r\n"); if (!crlf) break;
        in = crlf + 2;
        if (sz <= 0) break;
        if (in + sz > end) sz = (long)(end - in);
        memmove(out, in, sz); out += sz; in += sz + 2;
    }
    return (int)(out - b);
}

static DWORD WINAPI http_client(LPVOID arg) {
    SOCKET c = (SOCKET)(uintptr_t)arg;
    char req[65536]; int len = 0, r; char *hend = NULL;
    while (len < (int)sizeof req - 1 && (r = recv(c, req + len, sizeof req - 1 - len, 0)) > 0) {
        len += r; req[len] = 0;
        if ((hend = strstr(req, "\r\n\r\n"))) break;
    }
    if (!hend) { closesocket(c); return 0; }
    int hlen = (int)(hend + 4 - req), clen = 0;
    char *cl = strstr(req, "Content-Length:"); if (!cl) cl = strstr(req, "content-length:");
    if (cl && cl < hend) clen = atoi(cl + 15);
    while (len < hlen + clen && len < (int)sizeof req - 1 && (r = recv(c, req + len, sizeof req - 1 - len, 0)) > 0) len += r;
    char method[16] = "", path[2048] = "";
    sscanf(req, "%15s %2047s", method, path);
    /* forward: same request line and body, Host = official dispatch, HTTP/1.0 so the reply ends with close */
    char fwd[70000]; int fl = 0;
    fl += snprintf(fwd + fl, sizeof fwd - fl, "%s %s HTTP/1.0\r\nHost: %s:%d\r\n", method, path, DISPATCH_HOST, DISPATCH_PORT);
    for (char *line = strstr(req, "\r\n") + 2; line < hend;) {
        char *e = strstr(line, "\r\n"); if (!e) break;
        if (_strnicmp(line, "Host:", 5) && _strnicmp(line, "Connection:", 11) && _strnicmp(line, "Accept-Encoding:", 16))
            fl += snprintf(fwd + fl, sizeof fwd - fl, "%.*s\r\n", (int)(e - line), line);
        line = e + 2;
    }
    fl += snprintf(fwd + fl, sizeof fwd - fl, "Connection: close\r\n\r\n");
    if (clen > 0 && fl + clen < (int)sizeof fwd) { memcpy(fwd + fl, hend + 4, clen); fl += clen; }
    SOCKET u = tcp_connect(g_upstream_ip, DISPATCH_PORT);
    if (u == INVALID_SOCKET) {
        ui_log("Could not reach the official server (%s). Is it still online?", g_upstream_ip);
        const char *bad = "HTTP/1.0 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"; send(c, bad, (int)strlen(bad), 0);
        closesocket(c); return 0;
    }
    send(u, fwd, fl, 0);
    int rn; char *resp = read_all(u, &rn); closesocket(u);
    char *rb = strstr(resp, "\r\n\r\n");
    int status = 0; sscanf(resp, "HTTP/%*s %d", &status);
    char *body = rb ? rb + 4 : resp; int blen = rb ? rn - (int)(body - resp) : rn;
    if (rb && (strstr(resp, "chunked") && strstr(resp, "chunked") < rb)) blen = dechunk(body, blen);
    body[blen] = 0;
    char *outbody = NULL;
    if (strncmp(path, "/dispatch/region_info", 21) == 0) {
        char port[16];
        if (find_json_str(body, "gate_tcp_ip", g_gate_ip, sizeof g_gate_ip) && find_json_str(body, "gate_tcp_port", port, sizeof port)) {
            g_gate_port = atoi(port);
            char *a = replace_json_value(body, "gate_tcp_ip", "127.0.0.1", 1);
            char p2[16]; snprintf(p2, sizeof p2, "%d", GATE_PORT);
            outbody = replace_json_value(a, "gate_tcp_port", p2, 0); free(a);
            ui_log("Connected to the official game server %s:%d (recording).", g_gate_ip, g_gate_port);
        }
        if (g_cfg_patched) { restore_config(); ui_log("Game settings put back to normal."); }
    }
    const char *ob = outbody ? outbody : body; int obl = outbody ? (int)strlen(outbody) : blen;
    char hdr[256]; int hl = snprintf(hdr, sizeof hdr, "HTTP/1.1 %d OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
                                     status ? status : 200, obl);
    send(c, hdr, hl, 0); send(c, ob, obl, 0);
    free(outbody); free(resp);
    shutdown(c, SD_SEND); closesocket(c);
    return 0;
}

static DWORD WINAPI http_server(LPVOID arg) {
    SOCKET l = (SOCKET)(uintptr_t)arg;
    for (;;) { SOCKET c = accept(l, NULL, NULL); if (c == INVALID_SOCKET) break; CloseHandle(CreateThread(NULL, 0, http_client, (LPVOID)(uintptr_t)c, 0, NULL)); }
    return 0;
}

struct pipe_arg { SOCKET from, to; int dir, conn; };
static DWORD WINAPI pump(LPVOID a) {
    struct pipe_arg *pa = (struct pipe_arg *)a;
    struct framer fr = {0}; fr.dir = pa->dir; fr.conn = pa->conn;
    char buf[65536]; int r;
    while ((r = recv(pa->from, buf, sizeof buf, 0)) > 0) {
        int off = 0;
        while (off < r) { int w = send(pa->to, buf + off, r - off, 0); if (w <= 0) { r = -1; break; } off += w; }
        if (r < 0) break;
        framer_feed(&fr, buf, r);
    }
    shutdown(pa->to, SD_BOTH); shutdown(pa->from, SD_BOTH);
    free(fr.buf); free(pa);
    return 0;
}

static DWORD WINAPI gate_client(LPVOID arg) {
    SOCKET c = (SOCKET)(uintptr_t)arg;
    if (!g_gate_ip[0]) { closesocket(c); return 0; }
    SOCKET u = tcp_connect(g_gate_ip, g_gate_port);
    if (u == INVALID_SOCKET) { ui_log("Could not reach the official game server."); closesocket(c); return 0; }
    int conn = InterlockedIncrement((LONG *)&g_conns);
    struct pipe_arg *a = (struct pipe_arg *)malloc(sizeof *a), *b = (struct pipe_arg *)malloc(sizeof *b);
    a->from = c; a->to = u; a->dir = 0; a->conn = conn;
    b->from = u; b->to = c; b->dir = 1; b->conn = conn;
    HANDLE t[2] = {CreateThread(NULL, 0, pump, a, 0, NULL), CreateThread(NULL, 0, pump, b, 0, NULL)};
    WaitForMultipleObjects(2, t, TRUE, INFINITE);
    CloseHandle(t[0]); CloseHandle(t[1]);
    closesocket(c); closesocket(u);
    return 0;
}

static DWORD WINAPI gate_server(LPVOID arg) {
    SOCKET l = (SOCKET)(uintptr_t)arg;
    for (;;) { SOCKET c = accept(l, NULL, NULL); if (c == INVALID_SOCKET) break; CloseHandle(CreateThread(NULL, 0, gate_client, (LPVOID)(uintptr_t)c, 0, NULL)); }
    return 0;
}

static DWORD find_launcher(void) {
    DWORD pid = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32 e; e.dwSize = sizeof e;
    if (Process32First(snap, &e)) do { if (_stricmp(e.szExeFile, "launcher.exe") == 0) { pid = e.th32ProcessID; break; } } while (Process32Next(snap, &e));
    CloseHandle(snap);
    return pid;
}

static DWORD WINAPI watch_game(LPVOID a) {
    DWORD t0 = GetTickCount();
    WaitForSingleObject(g_game_proc, INFINITE);
    /* Steam may close the copy we started and start the game again through Steam: follow that copy */
    for (int round = 0; round < 3; round++) {
        DWORD pid = 0;
        for (int i = 0; i < 60 && !pid; i++) { Sleep(500); pid = find_launcher(); }
        if (!pid) break;
        HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, pid);
        if (!h) break;
        ui_log("The game was restarted by Steam - still recording (process %lu).", (unsigned long)pid);
        WaitForSingleObject(h, INFINITE); CloseHandle(h);
    }
    (void)t0;
    Sleep(1500);
    PostMessageW(g_win, WM_GAMEEXIT, 0, 0);
    return 0;
}

/* ------------------------------------------------------------------ save */
static int save_backup(char *out, int outsz) {
    if (!g_frames || !g_player[0]) return 0;
    EnterCriticalSection(&g_cs);
    fflush(g_tmp);
    char dir[MAX_PATH]; snprintf(dir, sizeof dir, "%sbackups", g_exedir); CreateDirectoryA(dir, NULL);
    SYSTEMTIME st; GetLocalTime(&st);
    char safe[128]; int j = 0;
    for (unsigned char *c = (unsigned char *)g_player; *c && j < 100; c++) if (*c >= 0x80 || isalnum(*c) || *c == '-' || *c == '_') safe[j++] = *c;
    safe[j] = 0; if (!j) strcpy(safe, "player");
    char path[MAX_PATH]; snprintf(path, sizeof path, "%s\\%s_%04d%02d%02d_%02d%02d.rzsave", dir, safe, st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute);
    wchar_t wpath[MAX_PATH]; MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, MAX_PATH);
    FILE *o = _wfopen(wpath, L"wb");
    int ok = 0;
    if (o) {
        fprintf(o, "RZSAVE2\n{\"format\":\"rzsave/2\",\"player_name\":\"");
        for (char *c = g_player; *c; c++) { if (*c == '"' || *c == '\\') fputc('\\', o); fputc(*c, o); }
        fprintf(o, "\",\"frames\":%ld,\"saved\":\"%04d-%02d-%02d %02d:%02d\",\"tool\":\"RozefieldBackup 1\"}\n", g_frames,
                st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute);
        FILE *in = fopen(g_tmppath, "rb");
        if (in) { char b[65536]; size_t n; while ((n = fread(b, 1, sizeof b, in)) > 0) fwrite(b, 1, n, o); fclose(in); ok = 1; }
        fclose(o);
    }
    LeaveCriticalSection(&g_cs);
    snprintf(out, outsz, "%s", path);
    return ok;
}

/* ------------------------------------------------------------------ actions */
static void start_backup_work(void);
static DWORD WINAPI start_thread(LPVOID a) { start_backup_work(); return 0; }
static volatile LONG g_starting = 0;
static void start_backup(void) {   /* runs in the background so the window never freezes */
    if (InterlockedExchange(&g_starting, 1)) { ui_log("Already starting - please wait..."); return; }
    ui_log("Starting... (button 1 pressed)");
    CloseHandle(CreateThread(NULL, 0, start_thread, NULL, 0, NULL));
}

static void start_backup_work(void) {
    wchar_t wg[MAX_PATH]; GetWindowTextW(g_edit, wg, MAX_PATH);
    WideCharToMultiByte(CP_ACP, 0, wg, -1, g_game, MAX_PATH, NULL, NULL);
    if (!has_launcher(g_game)) { MessageBoxW(g_win, L"launcher.exe was not found in that folder.\nChoose your OverField game folder (Steam: steamapps\\common\\OverField).", L"Rozefield Backup", MB_OK | MB_ICONWARNING); InterlockedExchange(&g_starting, 0); return; }
    char ini[MAX_PATH]; ini_path(ini); WritePrivateProfileStringA("game", "folder", g_game, ini);
    if (!g_running) {
        ui_log("Finding the official server...");
        if (!resolve_dispatch()) { ui_log("Could not find the official server. Check your internet connection."); InterlockedExchange(&g_starting, 0); return; }
        SOCKET h = tcp_listen(DISPATCH_PORT), g = tcp_listen(GATE_PORT);
        if (h == INVALID_SOCKET || g == INVALID_SOCKET) {
            ui_log("Ports %d/%d are busy - close the Rozefield server or another copy of this window first.", DISPATCH_PORT, GATE_PORT);
            if (h != INVALID_SOCKET) closesocket(h); if (g != INVALID_SOCKET) closesocket(g);
            InterlockedExchange(&g_starting, 0); return;
        }
        CloseHandle(CreateThread(NULL, 0, http_server, (LPVOID)(uintptr_t)h, 0, NULL));
        CloseHandle(CreateThread(NULL, 0, gate_server, (LPVOID)(uintptr_t)g, 0, NULL));
        snprintf(g_tmppath, sizeof g_tmppath, "%srecording.tmp", g_exedir);
        g_tmp = fopen(g_tmppath, "wb+");
        g_running = 1;
    }
    if (!patch_config()) { ui_log("Could not change Config.txt in the game folder (is it read-only?)."); InterlockedExchange(&g_starting, 0); return; }
    sdk_official(1);
    char exe[MAX_PATH]; snprintf(exe, sizeof exe, "%s\\launcher.exe", g_game);
    STARTUPINFOA si = {sizeof si}; PROCESS_INFORMATION pi;
    if (!CreateProcessA(exe, NULL, NULL, NULL, FALSE, 0, NULL, g_game, &si, &pi)) { ui_log("Could not start the game."); restore_all(); InterlockedExchange(&g_starting, 0); return; }
    CloseHandle(pi.hThread); g_game_proc = pi.hProcess;
    CloseHandle(CreateThread(NULL, 0, watch_game, NULL, 0, NULL));
    EnableWindow(g_open, FALSE);
    ui_log("OverField started (%s). Log in with your official account as usual.", exe);
    InterlockedExchange(&g_starting, 0);
}

static void do_save(int quiet) {
    char path[MAX_PATH];
    if (!save_backup(path, sizeof path)) {
        if (!quiet) MessageBoxW(g_win, L"Nothing to save yet - start the game with the button above and log in first.", L"Rozefield Backup", MB_OK);
        return;
    }
    ui_log("Backup saved: %s", path);
    wchar_t w[MAX_PATH + 200], wp[MAX_PATH]; MultiByteToWideChar(CP_UTF8, 0, path, -1, wp, MAX_PATH);
    swprintf(w, MAX_PATH + 200, L"Backup saved:\n%ls\n\nKeep this file. Import it in the Rozefield login window (\"Import backup\").", wp);
    MessageBoxW(g_win, w, L"Rozefield Backup", MB_OK | MB_ICONINFORMATION);
    char sel[MAX_PATH + 16]; snprintf(sel, sizeof sel, "/select,\"%s\"", path);
    ShellExecuteA(NULL, "open", "explorer.exe", sel, NULL, SW_SHOWNORMAL);
}

static void browse(void) {
    BROWSEINFOW bi = {0}; bi.hwndOwner = g_win; bi.lpszTitle = L"Choose your OverField game folder (the one with launcher.exe)";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    LPITEMIDLIST id = SHBrowseForFolderW(&bi);
    if (id) { wchar_t p[MAX_PATH]; if (SHGetPathFromIDListW(id, p)) SetWindowTextW(g_edit, p); CoTaskMemFree(id); }
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_COMMAND:
        if (LOWORD(w) == 1) start_backup();
        else if (LOWORD(w) == 2) do_save(0);
        else if (LOWORD(w) == 3) browse();
        return 0;
    case WM_LOG: {
        wchar_t *s = (wchar_t *)l;
        int i = (int)SendMessageW(g_log, LB_ADDSTRING, 0, (LPARAM)s); SendMessageW(g_log, LB_SETTOPINDEX, i, 0);
        SetWindowTextW(g_status, s); free(s); return 0; }
    case WM_CHECK: refresh_checks(); return 0;
    case WM_GAMEEXIT:
        restore_all();
        EnableWindow(g_open, TRUE);
        ui_log("The game was closed.");
        if (g_player[0]) do_save(1);
        return 0;
    case WM_CLOSE:
        if (g_frames && g_player[0] && MessageBoxW(h, L"Save the backup before closing?", L"Rozefield Backup", MB_YESNO | MB_ICONQUESTION) == IDYES) do_save(1);
        restore_all();
        if (g_tmp) { fclose(g_tmp); g_tmp = NULL; DeleteFileA(g_tmppath); }
        DestroyWindow(h); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    GetModuleFileNameA(NULL, g_exedir, MAX_PATH);
    char *sl = strrchr(g_exedir, '\\'); if (sl) sl[1] = 0;
    snprintf(g_logpath, sizeof g_logpath, "%sRozefieldBackup.log", g_exedir);
    InitializeCriticalSection(&g_cs);
    WSADATA wd; WSAStartup(MAKEWORD(2, 2), &wd);
    CoInitialize(NULL);
    find_game();
    if (g_game[0]) restore_all();   /* undo an earlier run that was killed */
    ui_log("RozefieldBackup started. Game folder: %s", g_game[0] ? g_game : "(not found - use Browse)");

    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = hi; wc.lpszClassName = L"RozefieldBackup";
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1); wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClassW(&wc);
    int W = 640, H = 560;
    g_win = CreateWindowW(L"RozefieldBackup", L"Rozefield Backup - save your OverField account", WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                          (GetSystemMetrics(SM_CXSCREEN) - W) / 2, (GetSystemMetrics(SM_CYSCREEN) - H) / 2, W, H, NULL, NULL, hi, NULL);
    HFONT f = CreateFontW(-15, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    HFONT fb = CreateFontW(-17, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    HWND c[12]; int n = 0;
    c[n++] = CreateWindowW(L"STATIC", L"OverField game folder (official Steam version):", WS_CHILD | WS_VISIBLE, 16, 12, 600, 20, g_win, NULL, hi, NULL);
    g_edit = c[n++] = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 16, 34, 500, 26, g_win, NULL, hi, NULL);
    c[n++] = CreateWindowW(L"BUTTON", L"Browse...", WS_CHILD | WS_VISIBLE, 524, 33, 92, 28, g_win, (HMENU)3, hi, NULL);
    g_open = c[n++] = CreateWindowW(L"BUTTON", L"1.  Open OverField (Official)", WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON, 16, 72, 296, 44, g_win, (HMENU)1, hi, NULL);
    g_save = c[n++] = CreateWindowW(L"BUTTON", L"2.  Save backup", WS_CHILD | WS_VISIBLE, 320, 72, 296, 44, g_win, (HMENU)2, hi, NULL);
    c[n++] = CreateWindowW(L"STATIC", L"Open these in the game so they are saved too:", WS_CHILD | WS_VISIBLE, 16, 128, 600, 20, g_win, NULL, hi, NULL);
    g_check = c[n++] = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOSEL, 16, 150, 600, 200, g_win, NULL, hi, NULL);
    c[n++] = CreateWindowW(L"STATIC", L"Log:", WS_CHILD | WS_VISIBLE, 16, 358, 600, 20, g_win, NULL, hi, NULL);
    g_log = c[n++] = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL | LBS_NOSEL, 16, 380, 600, 104, g_win, NULL, hi, NULL);
    g_status = c[n++] = CreateWindowW(L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_ENDELLIPSIS, 16, 492, 600, 20, g_win, NULL, hi, NULL);
    for (int i = 0; i < n; i++) SendMessageW(c[i], WM_SETFONT, (WPARAM)f, TRUE);
    SendMessageW(g_open, WM_SETFONT, (WPARAM)fb, TRUE); SendMessageW(g_save, WM_SETFONT, (WPARAM)fb, TRUE);
    SendMessageW(g_log, LB_SETHORIZONTALEXTENT, 1600, 0);
    wchar_t wg[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_game, -1, wg, MAX_PATH); SetWindowTextW(g_edit, wg);
    refresh_checks();
    ShowWindow(g_win, show); UpdateWindow(g_win);
    ui_log(g_game[0] ? "Ready. Press 1 to start the game, then log in." : "Choose your OverField folder with Browse..., then press 1.");
    ui_log("Nothing is sent on your behalf and your login token is not saved. Your settings are restored automatically.");
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { if (!IsDialogMessageW(g_win, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); } }
    return 0;
}
