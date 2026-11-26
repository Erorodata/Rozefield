/* Rozefield Backup.exe - save your OverField account while the official server is still online.
 *
 * Click "Open OverField (Official)": the game starts and logs in to the official server as usual, but its
 * connection passes through this window, which records what the server tells the game about your account.
 * After you log in it also asks the server for the rest of your account (bag, gear, life skills, achievements,
 * handbook, friends, mail list, ...) using only the read-only look-ups the game itself sends, so you don't have to
 * open every screen. Nothing in your account is changed. Your login token and device details are not saved. When you close the game
 * (or press "Save backup") you get  backups\<name>_<date>.rzsave  - import it into Rozefield from its login window.
 *
 * How: while the official servers are up the game finds them through a built-in lookup service (HTTPDNS
 * 8.134.240.36), so for the session that one address in global-metadata.dat is pointed at this window (a copy of the
 * original is kept and put back when the game closes, or the next time this window opens). Lookups are forwarded to
 * the real service; only the dispatch server's address is answered with 127.0.0.1. Dispatch HTTP (:18881) is
 * forwarded to the official dispatch server; the game server address in its answer is pointed at the local relay
 * (:11001), which forwards the game's traffic to the official game server and keeps a copy. Config.txt is also
 * switched to RemoteServerIP=127.0.0.1 until the game has asked for the server list.
 *
 * File format (RZSAVE2): "RZSAVE2\n" + JSON meta line + records {u8 dir(0=client,1=server), u16 conn, f64 time,
 * u32 len, frame bytes as on the wire}.
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 rozefield_backup.c -o "Rozefield Backup.exe"
 *        -lws2_32 -lcomdlg32 -lshell32 -lole32 -luser32 -lgdi32 -ladvapi32 -lmsimg32 -liphlpapi -lgdiplus -Wl,--subsystem,windows
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
#include <iphlpapi.h>
#include <mstcpip.h>
#include <math.h>
#include <stdarg.h>
#include "backup_queries.h"
#include "msgids_known.h"
#include "windivert.h"
#include "windivert_embed.h"

#define DISPATCH_HOST "dsp-global-of.inutan.com"
#define DISPATCH_PORT 18881
#define GATE_PORT 11001
#define HTTPDNS_IP "8.134.240.36"
#define HTTPDNS_PORT 80
#define WM_LOG (WM_APP + 1)
#define WM_CHECK (WM_APP + 2)
#define WM_GAMEEXIT (WM_APP + 3)
#define WM_AUTOSAVE (WM_APP + 4)

static HWND g_win;
/* window state for the painted launcher-style UI */
enum { M_IDLE, M_STARTING, M_LOGIN, M_FETCH, M_DONE, M_WATCH };
static volatile LONG g_mode = M_IDLE, g_fetch_got = 0;
static double g_pct_shown = 0;
static wchar_t g_lastlog[512] = L"";
static DWORD g_flash[32];
static int g_hover = 0, g_saved_once = 0;
static wchar_t g_savedpath[MAX_PATH];
static volatile int g_up_bound;
static void *volatile g_cur;          /* the game's live connection through this window */
static volatile LONG g_rebackup;
static SOCKET tcp_connect_up(const char *ip, int port);
static int wd_load(void);
static DWORD WINAPI watch_wd_thread(LPVOID a);
static void start_reconnect(void);
static volatile int g_game_running;
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
    if (g_logpath[0]) {   /* "Rozefield Backup.log" next to the exe: send it when something goes wrong */
        FILE *lf = fopen(g_logpath, "ab");
        if (lf) { SYSTEMTIME t; GetLocalTime(&t); fprintf(lf, "%02d:%02d:%02d  %s\r\n", t.wHour, t.wMinute, t.wSecond, b); fclose(lf); }
    }
    wchar_t *w = (wchar_t *)malloc(2048 * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, b, -1, w, 2048);
    PostMessageW(g_win, WM_LOG, 0, (LPARAM)w);
}

struct check { const char *label; const char *how; int msg_id; int done; const char *icon; COLORREF tint; };
#define MSG_FIELDS -2   /* not a message: a map's SceneDataNotice with its Sequence / Aberrant Field progress */
static struct check CHECKS[] = {
    {"Account & bag", "log in", 1006, 0, "account", RGB(163, 204, 74)},
    {"Achievements", "automatic", 1762, 0, "achieve", RGB(255, 112, 32)},
    {"Life skills", "automatic", 1370, 0, "life", RGB(240, 70, 90)},
    {"Collection book", "automatic", 1366, 0, "lifebook", RGB(80, 170, 240)},
    {"Exploration", "automatic", 1862, 0, "explore", RGB(60, 140, 240)},
    {"Poster album", "automatic", 1424, 0, "poster", RGB(250, 196, 40)},
    {"Friends", "automatic", 1740, 0, "friend", RGB(240, 90, 150)},
    {"Mail", "automatic", 1122, 0, "g_mail", RGB(255, 140, 60)},
    {"Plaza layout", "automatic (be in your own Plaza)", 1016, 0, "g_plaza", RGB(70, 190, 160)},
    {"Plaza presets", "automatic", 2624, 0, "preset", RGB(150, 110, 230)},
    {"Salvager records", "automatic", 1480, 0, "charach", RGB(20, 110, 220)},
    {"Field stages", "map tour", MSG_FIELDS, 0, "g_fields", RGB(220, 60, 70)},
};
#define NCHECK (int)(sizeof CHECKS / sizeof CHECKS[0])

static void mark_check(int msg_id) {
    for (int i = 0; i < NCHECK; i++)
        if (!CHECKS[i].done && CHECKS[i].msg_id == msg_id) { CHECKS[i].done = 1; g_flash[i] = GetTickCount(); PostMessageW(g_win, WM_CHECK, 0, 0); }
}

/* ------------------------------------------------------------------ settings */
static void ini_path(char *out) { snprintf(out, MAX_PATH, "%sRozefield Backup.ini", g_exedir); }

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

/* global-metadata.dat: point the HTTPDNS string literal at 127.0.0.1 for the session (original kept beside it) */
static void meta_paths(char *f, char *bak) {
    snprintf(f, MAX_PATH, "%s\\launcher_Data\\il2cpp_data\\Metadata\\global-metadata.dat", g_game);
    snprintf(bak, MAX_PATH, "%s.rzbackup", f);
}
static int restore_metadata(void) {   /* 1 = nothing to do or restored */
    char f[MAX_PATH], bak[MAX_PATH]; meta_paths(f, bak);
    if (GetFileAttributesA(bak) == INVALID_FILE_ATTRIBUTES) return 1;
    if (CopyFileA(bak, f, FALSE)) { DeleteFileA(bak); return 1; }
    return 0;   /* the game still has it open */
}
static int patch_metadata(void) {
    char f[MAX_PATH], bak[MAX_PATH]; meta_paths(f, bak);
    char orig[MAX_PATH + 8]; snprintf(orig, sizeof orig, "%s.orig", f);   /* a game changed for Rozefield: start from the original */
    FILE *in = fopen(GetFileAttributesA(orig) != INVALID_FILE_ATTRIBUTES ? orig : f, "rb"); if (!in) return 0;
    fseek(in, 0, SEEK_END); long n = ftell(in); fseek(in, 0, SEEK_SET);
    unsigned char *d = (unsigned char *)malloc(n); if (!d || fread(d, 1, n, in) != (size_t)n) { fclose(in); free(d); return 0; }
    fclose(in);
    const char *OLD = HTTPDNS_IP, *NEW = "127.0.0.1"; size_t ol = strlen(OLD), nl = strlen(NEW);
    uint32_t lo, ls, ldo; memcpy(&lo, d + 8, 4); memcpy(&ls, d + 12, 4); memcpy(&ldo, d + 16, 4);
    int ok = 0;
    if (n > 24 && lo + ls <= (uint32_t)n && ldo < (uint32_t)n) {
        for (long i = ldo; i + (long)ol <= n && !ok; i++) {
            if (memcmp(d + i, OLD, ol) != 0) continue;
            int32_t pos = (int32_t)(i - ldo);
            for (uint32_t k = 0; k + 8 <= ls; k += 8) {
                uint32_t len; int32_t idx; memcpy(&len, d + lo + k, 4); memcpy(&idx, d + lo + k + 4, 4);
                if (idx == pos && len == ol) { memcpy(d + i, NEW, nl); len = (uint32_t)nl; memcpy(d + lo + k, &len, 4); ok = 1; break; }
            }
        }
    }
    if (ok) {
        if (GetFileAttributesA(bak) == INVALID_FILE_ATTRIBUTES && !CopyFileA(f, bak, TRUE)) ok = 0;
        FILE *o = ok ? fopen(f, "wb") : NULL;
        if (o) { ok = fwrite(d, 1, n, o) == (size_t)n; fclose(o); } else ok = 0;
        if (!ok) restore_metadata();
    }
    free(d);
    return ok;
}

static void restore_all(void) {
    char cfg[MAX_PATH]; snprintf(cfg, sizeof cfg, "%s\\launcher_Data\\StreamingAssets\\Config.txt", g_game);
    snprintf(g_cfg, sizeof g_cfg, "%s", cfg); snprintf(g_cfgbak, sizeof g_cfgbak, "%s.rzbackup", cfg);
    restore_config();
    sdk_official(0);
    for (int i = 0; i < 20 && !restore_metadata(); i++) Sleep(500);
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

/* "ips":[...] -> "ips":["127.0.0.1"] */
static char *set_ips_local(const char *body) {
    const char *p = strstr(body, "\"ips\""); if (!p) return NULL;
    const char *a = strchr(p, '['), *e = a ? strchr(a, ']') : NULL; if (!a || !e) return NULL;
    size_t n = strlen(body) + 32; char *o = (char *)malloc(n);
    snprintf(o, n, "%.*s[\"127.0.0.1\"]%s", (int)(a - body), body, e + 1);
    return o;
}

/* the game's lookup service (pointed here for the session): forward to the real one */
static void httpdns_answer(SOCKET c, const char *path) {
    char out[4096] = "{}"; int ol = 2;
    SOCKET u = tcp_connect(HTTPDNS_IP, HTTPDNS_PORT);
    if (u != INVALID_SOCKET) {
        char rq[2400]; int rl = snprintf(rq, sizeof rq, "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n", path, HTTPDNS_IP);
        send(u, rq, rl, 0);
        int n; char *b = read_all(u, &n); closesocket(u);
        char *body = strstr(b, "\r\n\r\n");
        if (body) {
            body += 4;
            if (strstr(b, "chunked") && strstr(b, "chunked") < body) { int bl = dechunk(body, n - (int)(body - b)); body[bl] = 0; }
            char *rw = strstr(path, "domain=" DISPATCH_HOST) ? set_ips_local(body) : NULL;
            ol = snprintf(out, sizeof out, "%s", rw ? rw : body);
            if (rw) ui_log("Game is looking for its server - pointing it at this window.");
            free(rw);
        }
        free(b);
    }
    char hdr[160]; int hl = snprintf(hdr, sizeof hdr, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n", ol);
    send(c, hdr, hl, 0); send(c, out, ol, 0);
    shutdown(c, SD_SEND); closesocket(c);
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
    if (strncmp(path, "/resolve", 8) == 0 || strstr(path, "/resolve?")) { httpdns_answer(c, path); return 0; }
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

/* One relayed game connection. The game's own frames go through unchanged except that their packet_id / seq_id are
 * shifted past the look-ups this window adds, so the server sees one continuous sequence; answers to the look-ups
 * are recorded but not passed to the game. */
#define PIDMAP 8192
struct gconn {
    SOCKET game, server; int conn;
    CRITICAL_SECTION cs;          /* order of frames sent to the server */
    uint64_t last_pid, last_seq;  /* last ids sent to the server */
    uint64_t pid_off, seq_off;    /* how many look-ups were added so far */
    uint64_t map_srv[PIDMAP], map_game[PIDMAP];   /* server packet_id -> game packet_id */
    unsigned char inj[PIDMAP];    /* server packet_id was one of ours */
    volatile LONG logged_in, done;
    volatile LONG touring;        /* map tour running: the official server's pushes are recorded, not shown to the game */
    volatile LONG seen_scene;     /* sceneId of the last SceneDataNotice */
    uint32_t home_scene, home_label;   /* where the game is (from its own last SceneDataNotice) */
    uint32_t game_scene;          /* map the game itself has loaded (last SceneDataNotice passed to it) */
};

static size_t put_varint(unsigned char *o, uint64_t v) { size_t n = 0; do { unsigned char b = v & 0x7f; v >>= 7; o[n++] = b | (v ? 0x80 : 0); } while (v); return n; }

/* rebuild a PacketHead with new packet_id (field 1) / seq_id (field 6); other fields copied as they are */
static size_t rewrite_head(const unsigned char *p, const unsigned char *e, uint64_t pid, uint64_t seq, unsigned char *o) {
    size_t n = 0; int had_pid = 0, had_seq = 0;
    while (p < e) {
        const unsigned char *st = p;
        uint64_t k = rd_varint(&p, e); int f = (int)(k >> 3), wt = (int)(k & 7);
        if (wt == 0) {
            uint64_t v = rd_varint(&p, e);
            if (f == 1) { had_pid = 1; if (pid) { n += put_varint(o + n, (1 << 3)); n += put_varint(o + n, pid); } continue; }
            if (f == 6) { had_seq = 1; if (seq) { n += put_varint(o + n, (6 << 3)); n += put_varint(o + n, seq); } continue; }
            (void)v;
        } else if (wt == 2) { uint64_t l = rd_varint(&p, e); p += l; }
        else if (wt == 1) p += 8; else if (wt == 5) p += 4; else break;
        memcpy(o + n, st, p - st); n += p - st;
    }
    if (!had_pid && pid) { n += put_varint(o + n, (1 << 3)); n += put_varint(o + n, pid); }
    if (!had_seq && seq) { n += put_varint(o + n, (6 << 3)); n += put_varint(o + n, seq); }
    return n;
}

static int send_all(SOCKET s, const unsigned char *b, size_t n) {
    size_t off = 0; while (off < n) { int w = send(s, (const char *)b + off, (int)(n - off), 0); if (w <= 0) return 0; off += w; } return 1;
}

/* send one frame to the server (caller holds g->cs); game_pid = 0 for our own look-ups */
static int to_server(struct gconn *g, uint64_t msg_id, const unsigned char *head, size_t hl, const unsigned char *body, size_t bl,
                     uint64_t game_pid, uint64_t game_seq, int ours) {
    uint64_t pid, seq;
    if (ours) { pid = g->last_pid + 1; seq = g->last_seq + 1; g->pid_off++; g->seq_off++; }
    else { pid = game_pid ? game_pid + g->pid_off : 0; seq = game_seq ? game_seq + g->seq_off : 0; }
    if (pid) { g->last_pid = pid; g->map_srv[pid % PIDMAP] = pid; g->map_game[pid % PIDMAP] = ours ? 0 : game_pid; g->inj[pid % PIDMAP] = (unsigned char)ours; }
    if (seq) g->last_seq = seq;
    unsigned char nh[256]; size_t nhl;
    if (ours) {
        nhl = 0;
        nhl += put_varint(nh + nhl, (1 << 3)); nhl += put_varint(nh + nhl, pid);
        nhl += put_varint(nh + nhl, (2 << 3)); nhl += put_varint(nh + nhl, msg_id);
        if (bl) { nhl += put_varint(nh + nhl, (4 << 3)); nhl += put_varint(nh + nhl, bl); }
        nhl += put_varint(nh + nhl, (6 << 3)); nhl += put_varint(nh + nhl, seq);
    } else {
        if (hl > 200) return 0;
        nhl = rewrite_head(head, head + hl, pid, seq, nh);
    }
    size_t tot = 2 + nhl + bl;
    unsigned char *f = (unsigned char *)malloc(tot);
    f[0] = (unsigned char)(nhl >> 8); f[1] = (unsigned char)nhl; memcpy(f + 2, nh, nhl); if (bl) memcpy(f + 2 + nhl, body, bl);
    int ok = send_all(g->server, f, tot);
    if (msg_id == 1001) record(0, g->conn, f, (uint32_t)(2 + nhl));   /* VerifyLoginTokenReq: header only, no token */
    else record(0, g->conn, f, (uint32_t)tot);
    free(f);
    return ok;
}

/* sceneId (1) and channel_label (27) from a SceneDataNotice body (SceneData is field 2) */
static void scene_of(const unsigned char *body, size_t n, int compressed, uint32_t *sid, uint32_t *label) {
    size_t len = n; unsigned char *buf = NULL; const unsigned char *p = body;
    *sid = 0; *label = 0;
    if (compressed) { buf = snappy_raw(body, n, &len); if (!buf) return; p = buf; }
    const unsigned char *e = p + len;
    while (p < e) {
        uint64_t k = rd_varint(&p, e); int f = (int)(k >> 3), wt = (int)(k & 7);
        if (wt == 0) rd_varint(&p, e);
        else if (wt == 2) {
            uint64_t l = rd_varint(&p, e);
            if (f == 2) {
                const unsigned char *q = p, *qe = p + l;
                while (q < qe) {
                    uint64_t k2 = rd_varint(&q, qe); int f2 = (int)(k2 >> 3), w2 = (int)(k2 & 7);
                    if (w2 == 0) { uint64_t v = rd_varint(&q, qe); if (f2 == 1) *sid = (uint32_t)v; else if (f2 == 27) *label = (uint32_t)v; }
                    else if (w2 == 2) { uint64_t l2 = rd_varint(&q, qe); q += l2; }
                    else if (w2 == 1) q += 8; else if (w2 == 5) q += 4; else break;
                }
            }
            p += l;
        } else if (wt == 1) p += 8; else if (wt == 5) p += 4; else break;
    }
    free(buf);
}

/* Official only sends a map's progress (crystals, collectibles, landmarks, terminals, chests, puzzles) when the
 * character enters that map. The tour moves the character through every map on the official server and back
 * home; the game keeps showing where it is (the server's map pushes during the tour are recorded, not shown). */
static const uint32_t TOUR[] = {9999, 1, 2, 3, 4, 5, 6, 1001, 1002, 1003};
static const wchar_t *TOUR_NAME[] = {L"Rota Plaza", L"Garden Day", L"Behaim", L"Garden Night", L"Behaim Reverse", L"Cake Day",
                                     L"Cake Night", L"Crystal Ball", L"Hot Pot", L"Orison School"};
/* in the game files but never opened on Global (World Selection doesn't list them; official refuses the move):
 * Behaim Reverse (F-07X) and Cake Night (its picture still says "temporary, image under construction") */
static const int TOUR_UNRELEASED[] = {0, 0, 0, 0, 1, 0, 1, 0, 0, 0};
#define NTOUR (int)(sizeof TOUR / sizeof TOUR[0])
static volatile LONG g_tour_state[NTOUR];   /* 0 waiting, 1 visiting, 2 saved, 3 not open on this account */
#define NTOUR_REAL 8   /* maps that exist on Global */
static volatile LONG g_tour_active, g_tour_done_n;
static volatile LONG g_tour_dirty;          /* a tour moved the character and hasn't brought it back yet */
static uint32_t g_home_scene, g_home_label; /* where the character was before any tour */
static int change_scene(struct gconn *g, uint32_t sid, uint32_t label) {
    unsigned char b[16]; size_t n = 0;
    b[n++] = (1 << 3); n += put_varint(b + n, sid);
    if (label) { b[n++] = (2 << 3); n += put_varint(b + n, label); }
    EnterCriticalSection(&g->cs);
    int ok = to_server(g, 1201, NULL, 0, b, n, 0, 0, 1);
    LeaveCriticalSection(&g->cs);
    return ok;
}
static int wait_scene(struct gconn *g, uint32_t sid, int ms) {
    for (int t = 0; t < ms && !g->done; t += 100) { if ((uint32_t)g->seen_scene == sid) return 1; Sleep(100); }
    return 0;
}
static void map_tour(struct gconn *g) {
    if (!g_home_scene) { ui_log("Map tour skipped: the game's map is not known yet."); return; }
    InterlockedExchange(&g_tour_active, 1);
    InterlockedExchange(&g_tour_dirty, 1);
    ui_log("Visiting every map on official (crystals, collectibles, landmarks, terminals, areas)...");
    InterlockedExchange(&g->touring, 1);
    for (int i = 0; i < NTOUR && !g->done; i++) {
        if (g_tour_state[i] == 2 || TOUR_UNRELEASED[i]) continue;   /* saved earlier / not on Global */
        if (TOUR[i] == 9999) {   /* your Plaza (home) is always sent at login */
            if (g->home_scene == 9999 || g_home_scene == 9999) { InterlockedExchange(&g_tour_state[i], 2); InterlockedIncrement(&g_tour_done_n); }
            continue;
        }
        if (TOUR[i] == g_home_scene && g->home_scene == g_home_scene) {   /* the map you're on was sent at login */
            InterlockedExchange(&g_tour_state[i], 2); InterlockedIncrement(&g_tour_done_n); continue;
        }
        InterlockedExchange(&g_tour_state[i], 1); PostMessageW(g_win, WM_CHECK, 0, 0);
        InterlockedExchange(&g->seen_scene, 0);
        if (!change_scene(g, TOUR[i], 0)) { InterlockedExchange(&g_tour_state[i], 0); break; }
        char nm[64]; WideCharToMultiByte(CP_UTF8, 0, TOUR_NAME[i], -1, nm, sizeof nm, NULL, NULL);
        if (wait_scene(g, TOUR[i], 6000)) { InterlockedExchange(&g_tour_state[i], 2); InterlockedIncrement(&g_tour_done_n); ui_log("Map saved: %s", nm); }
        else if (!g->done) { InterlockedExchange(&g_tour_state[i], 3); ui_log("Map not open on this account (skipped): %s", nm); }
        else InterlockedExchange(&g_tour_state[i], 0);
        PostMessageW(g_win, WM_CHECK, 0, 0);
        Sleep(800);
    }
    InterlockedExchange(&g->seen_scene, 0);
    if (!g->done) {
        /* back home. If the game itself isn't there (it reconnected onto a tour map), let it see the move. */
        if (g->game_scene != g_home_scene) InterlockedExchange(&g->touring, 0);
        change_scene(g, g_home_scene, g_home_label);
        if (wait_scene(g, g_home_scene, 8000)) { InterlockedExchange(&g_tour_dirty, 0); ui_log("Map tour finished: %ld of %d maps saved, character back home.", (long)g_tour_done_n, NTOUR_REAL); }
        else ui_log("Could not bring the character back on official - it may be on another map next time you log in there.");
        Sleep(1500);
    } else ui_log("The connection dropped during the map tour - press the game's Reconnect button and it continues.");
    InterlockedExchange(&g->touring, 0);
    InterlockedExchange(&g_tour_active, 0);
    PostMessageW(g_win, WM_CHECK, 0, 0);
}

static DWORD WINAPI fetch_rest(LPVOID a) {
    struct gconn *g = (struct gconn *)a;
    if (!g_rebackup) Sleep(8000);   /* let the game finish its own login requests first */
    InterlockedExchange(&g_fetch_got, 0); InterlockedExchange(&g_mode, M_FETCH);
    ui_log("Collecting the rest of your account (bag, gear, life skills, achievements, handbook, friends, mail)...");
    int sent = 0;
    for (int i = 0; i < NQUERY && !g->done; i++) {
        EnterCriticalSection(&g->cs);
        int ok = to_server(g, (uint64_t)QUERIES[i].msg_id, NULL, 0, QUERIES[i].body, (size_t)QUERIES[i].len, 0, 0, 1);
        LeaveCriticalSection(&g->cs);
        if (!ok) break;
        sent++;
        Sleep(60);
    }
    Sleep(3000);
    if (!g->done) map_tour(g);
    InterlockedExchange(&g_mode, M_DONE);
    if (InterlockedExchange(&g_rebackup, 0)) { ui_log("Updated: %d look-ups again. Saving a new backup...", sent); PostMessageW(g_win, WM_AUTOSAVE, 0, 0); }
    else if (!g->done) ui_log("Done: %d look-ups saved. Press Save backup, or just close the game - it saves itself.", sent);
    PostMessageW(g_win, WM_CHECK, 1, 0);
    return 0;
}

static DWORD WINAPI game_to_server(LPVOID a) {
    struct gconn *g = (struct gconn *)a;
    unsigned char *buf = NULL; size_t len = 0, cap = 0; char tmp[65536]; int r;
    while ((r = recv(g->game, tmp, sizeof tmp, 0)) > 0) {
        if (len + r > cap) { cap = (len + r) * 2; buf = (unsigned char *)realloc(buf, cap); }
        memcpy(buf + len, tmp, r); len += r;
        size_t off = 0;
        while (len - off >= 2) {
            size_t hl = (buf[off] << 8) | buf[off + 1];
            if (len - off < 2 + hl) break;
            struct head h; parse_head(buf + off + 2, buf + off + 2 + hl, &h);
            size_t tot = 2 + hl + h.body_len;
            if (len - off < tot) break;
            EnterCriticalSection(&g->cs);
            int ok = to_server(g, h.msg_id, buf + off + 2, hl, buf + off + 2 + hl, h.body_len, h.packet_id, h.seq, 0);
            LeaveCriticalSection(&g->cs);
            if (!ok) { r = -1; break; }
            off += tot;
        }
        if (r < 0) break;
        memmove(buf, buf + off, len - off); len -= off;
    }
    free(buf);
    g->done = 1;
    shutdown(g->server, SD_BOTH); shutdown(g->game, SD_BOTH);
    return 0;
}

static DWORD WINAPI server_to_game(LPVOID a) {
    struct gconn *g = (struct gconn *)a;
    unsigned char *buf = NULL; size_t len = 0, cap = 0; char tmp[65536]; int r;
    while ((r = recv(g->server, tmp, sizeof tmp, 0)) > 0) {
        if (len + r > cap) { cap = (len + r) * 2; buf = (unsigned char *)realloc(buf, cap); }
        memcpy(buf + len, tmp, r); len += r;
        size_t off = 0;
        while (len - off >= 2) {
            size_t hl = (buf[off] << 8) | buf[off + 1];
            if (len - off < 2 + hl) break;
            struct head h; parse_head(buf + off + 2, buf + off + 2 + hl, &h);
            size_t tot = 2 + hl + h.body_len;
            if (len - off < tot) break;
            unsigned char *frame = buf + off;
            record(1, g->conn, frame, (uint32_t)tot);
            int ours = 0; uint64_t gpid = h.packet_id;
            if (h.packet_id) {
                EnterCriticalSection(&g->cs);
                size_t k = h.packet_id % PIDMAP;
                if (g->map_srv[k] == h.packet_id) { ours = g->inj[k]; gpid = g->map_game[k]; }
                LeaveCriticalSection(&g->cs);
            }
            if (h.msg_id == 1016) {   /* SceneDataNotice */
                uint32_t sid, lab; scene_of(frame + 2 + hl, h.body_len, h.flag == 1, &sid, &lab);
                if (sid && sid != 9999) mark_check(MSG_FIELDS);   /* a map: its Sequence / Aberrant Field stars, chests, progress */
                if (!g->touring && sid) {
                    g->home_scene = sid; g->home_label = lab; g->game_scene = sid;
                    if (!g_tour_dirty) { g_home_scene = sid; g_home_label = lab; }   /* never a tour map */
                }
                InterlockedExchange(&g->seen_scene, (LONG)sid);
            }
            int drop = ours || (g->touring && !h.packet_id);   /* the tour's map pushes stay out of the game */
            if (!drop) {
                int ok;
                if (gpid != h.packet_id && hl <= 200) {
                    unsigned char nh[256]; size_t nhl = rewrite_head(frame + 2, frame + 2 + hl, gpid, h.seq, nh);
                    unsigned char *f = (unsigned char *)malloc(2 + nhl + h.body_len);
                    f[0] = (unsigned char)(nhl >> 8); f[1] = (unsigned char)nhl; memcpy(f + 2, nh, nhl); memcpy(f + 2 + nhl, frame + 2 + hl, h.body_len);
                    ok = send_all(g->game, f, 2 + nhl + h.body_len); free(f);
                } else ok = send_all(g->game, frame, tot);
                if (!ok) { r = -1; break; }
            }
            if (h.msg_id == 1006 && !g_player[0]) {
                find_name(frame + 2 + hl, h.body_len, h.flag == 1);
                if (g_player[0]) ui_log("Logged in as %s. Nothing else to do - the rest is collected for you.", g_player);
                PostMessageW(g_win, WM_CHECK, 0, 0);
            }
            if ((h.msg_id == 1006 || h.msg_id == 1004) && !InterlockedExchange(&g->logged_in, 1))
                CloseHandle(CreateThread(NULL, 0, fetch_rest, g, 0, NULL));
            if (ours) InterlockedIncrement(&g_fetch_got);
            mark_check((int)h.msg_id);
            off += tot;
        }
        if (r < 0) break;
        memmove(buf, buf + off, len - off); len -= off;
    }
    free(buf);
    g->done = 1;
    shutdown(g->server, SD_BOTH); shutdown(g->game, SD_BOTH);
    return 0;
}

static DWORD WINAPI gate_client(LPVOID arg) {
    SOCKET c = (SOCKET)(uintptr_t)arg;
    if (!g_gate_ip[0]) { closesocket(c); return 0; }
    SOCKET u = g_up_bound ? tcp_connect_up(g_gate_ip, g_gate_port) : tcp_connect(g_gate_ip, g_gate_port);
    if (u == INVALID_SOCKET) { ui_log("Could not reach the official game server."); closesocket(c); return 0; }
    if (g_up_bound) ui_log("The game reconnected through this window - collecting from official now.");
    struct gconn *g = (struct gconn *)calloc(1, sizeof *g);
    g_cur = g;
    g->game = c; g->server = u; g->conn = InterlockedIncrement((LONG *)&g_conns);
    InitializeCriticalSection(&g->cs);
    HANDLE t[2] = {CreateThread(NULL, 0, game_to_server, g, 0, NULL), CreateThread(NULL, 0, server_to_game, g, 0, NULL)};
    WaitForMultipleObjects(2, t, TRUE, INFINITE);
    if (g_cur == g) g_cur = NULL;
    CloseHandle(t[0]); CloseHandle(t[1]);
    closesocket(c); closesocket(u);
    Sleep(20000);   /* a late fetch_rest may still hold g */
    if (g_cur == g) g_cur = NULL;
    DeleteCriticalSection(&g->cs); free(g);
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
/* Messages that carry login or device details (account SDK id, device id and model, analytics id, log-server
 * token, the game's own client logs). Rozefield needs none of them, so the backup keeps only their header. */
static int private_msg(uint64_t id) {
    return id == 1001 || id == 1002 || id == 1003 || id == 1004 || id == 2201 || id == 2203;
}
/* Copy the recording into the backup, record by record, leaving out the bodies of private messages. */
static void copy_records_private(FILE *in, FILE *o) {
    unsigned char hdr[15];
    while (fread(hdr, 1, 15, in) == 15) {
        uint32_t len; memcpy(&len, hdr + 11, 4);
        unsigned char *raw = (unsigned char *)malloc(len ? len : 1);
        if (fread(raw, 1, len, in) != len) { free(raw); break; }
        uint32_t keep = len;
        if (len >= 2) {
            uint32_t hl = ((uint32_t)raw[0] << 8) | raw[1];
            if (2 + hl <= len) {
                struct head h; parse_head(raw + 2, raw + 2 + hl, &h);
                if (private_msg(h.msg_id)) keep = 2 + hl;
            }
        }
        memcpy(hdr + 11, &keep, 4);
        fwrite(hdr, 1, 15, o); fwrite(raw, 1, keep, o);
        free(raw);
    }
}

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
        fprintf(o, "\",\"frames\":%ld,\"saved\":\"%04d-%02d-%02d %02d:%02d\",\"tool\":\"Rozefield Backup 2\"}\n", g_frames,
                st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute);
        FILE *in = fopen(g_tmppath, "rb");
        if (in) { copy_records_private(in, o); fclose(in); ok = 1; }
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
/* Open game: start OverField exactly as normal (nothing changed in its files), wait until you are logged in on
 * official, then take over the connection the same way as Use running game. Steam restarting the game, or the
 * game looking its server up by itself, can't get around this. */
static int is_admin(void);
static int find_game_conn(MIB_TCPROW *out);
static DWORD WINAPI open_then_reconnect(LPVOID a) {
    char exe[MAX_PATH]; snprintf(exe, sizeof exe, "%s\\launcher.exe", g_game);
    STARTUPINFOA si = {sizeof si}; PROCESS_INFORMATION pi;
    if (!CreateProcessA(exe, NULL, NULL, NULL, FALSE, 0, NULL, g_game, &si, &pi)) {
        ui_log("Could not start the game."); InterlockedExchange(&g_starting, 0); InterlockedExchange(&g_mode, M_IDLE); return 0;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    InterlockedExchange(&g_mode, M_LOGIN);
    ui_log("OverField started. Log in with your official account as usual - the backup starts by itself after that.");
    MIB_TCPROW row; int seen = 0;
    for (int t = 0; t < 1800; t++) {          /* up to 30 minutes */
        Sleep(1000);
        if (!find_launcher()) { if (t > 120) break; continue; }
        if (find_game_conn(&row)) { if (++seen >= 25) break; }   /* logged in and settled for 25 s */
        else seen = 0;
    }
    InterlockedExchange(&g_starting, 0);
    if (seen < 25) { ui_log("The game didn't connect to official. Log in, then press Use running game."); InterlockedExchange(&g_mode, M_IDLE); return 0; }
    InterlockedExchange(&g_mode, M_IDLE);
    start_reconnect();
    return 0;
}
static void start_backup(void) {   /* runs in the background so the window never freezes */
    if (find_launcher()) { start_reconnect(); return; }   /* already running: no second copy */
    if (!has_launcher(g_game)) { MessageBoxW(g_win, L"launcher.exe was not found in that folder.\nChoose your OverField game folder (Steam: steamapps\\common\\OverField).", L"Rozefield Backup", MB_OK | MB_ICONWARNING); return; }
    if (!is_admin()) {   /* taking over the connection needs administrator rights: ask now, not halfway */
        wchar_t me[MAX_PATH]; GetModuleFileNameW(NULL, me, MAX_PATH);
        SHELLEXECUTEINFOW ei = {sizeof ei}; ei.lpVerb = L"runas"; ei.lpFile = me; ei.lpParameters = L"--open"; ei.nShow = SW_SHOWNORMAL;
        if (ShellExecuteExW(&ei)) { restore_all(); ExitProcess(0); }
        ui_log("This needs administrator rights (the prompt was closed)."); return;
    }
    if (InterlockedExchange(&g_starting, 1)) { ui_log("Already starting - please wait..."); return; }
    InterlockedExchange(&g_mode, M_STARTING);
    char ini[MAX_PATH]; ini_path(ini); WritePrivateProfileStringA("game", "folder", g_game, ini);
    CloseHandle(CreateThread(NULL, 0, open_then_reconnect, NULL, 0, NULL));
}

static void start_backup_work(void) {
    if (!has_launcher(g_game)) { MessageBoxW(g_win, L"launcher.exe was not found in that folder.\nChoose your OverField game folder (Steam: steamapps\\common\\OverField).", L"Rozefield Backup", MB_OK | MB_ICONWARNING); InterlockedExchange(&g_starting, 0); InterlockedExchange(&g_mode, M_IDLE); return; }
    char ini[MAX_PATH]; ini_path(ini); WritePrivateProfileStringA("game", "folder", g_game, ini);
    if (!g_running) {
        ui_log("Finding the official server...");
        if (!resolve_dispatch()) { ui_log("Could not find the official server. Check your internet connection."); InterlockedExchange(&g_starting, 0); InterlockedExchange(&g_mode, M_IDLE); return; }
        SOCKET h = tcp_listen(DISPATCH_PORT), g = tcp_listen(GATE_PORT), dns = tcp_listen(HTTPDNS_PORT);
        if (h == INVALID_SOCKET || g == INVALID_SOCKET || dns == INVALID_SOCKET) {
            ui_log("Ports %d/%d/%d are busy - close the Rozefield server or another copy of this window first.", HTTPDNS_PORT, DISPATCH_PORT, GATE_PORT);
            if (h != INVALID_SOCKET) closesocket(h); if (g != INVALID_SOCKET) closesocket(g); if (dns != INVALID_SOCKET) closesocket(dns);
            InterlockedExchange(&g_starting, 0); return;
        }
        CloseHandle(CreateThread(NULL, 0, http_server, (LPVOID)(uintptr_t)h, 0, NULL));
        CloseHandle(CreateThread(NULL, 0, http_server, (LPVOID)(uintptr_t)dns, 0, NULL));
        CloseHandle(CreateThread(NULL, 0, gate_server, (LPVOID)(uintptr_t)g, 0, NULL));
        snprintf(g_tmppath, sizeof g_tmppath, "%srecording.tmp", g_exedir);
        g_tmp = fopen(g_tmppath, "wb+");
        g_running = 1;
    }
    if (!patch_config()) { ui_log("Could not change Config.txt in the game folder (is it read-only?)."); InterlockedExchange(&g_starting, 0); InterlockedExchange(&g_mode, M_IDLE); return; }
    if (!patch_metadata()) ui_log("Note: could not point the game's server lookup at this window (game running, or this copy is already changed). Trying anyway.");
    sdk_official(1);
    char exe[MAX_PATH]; snprintf(exe, sizeof exe, "%s\\launcher.exe", g_game);
    STARTUPINFOA si = {sizeof si}; PROCESS_INFORMATION pi;
    if (!CreateProcessA(exe, NULL, NULL, NULL, FALSE, 0, NULL, g_game, &si, &pi)) { ui_log("Could not start the game."); restore_all(); InterlockedExchange(&g_starting, 0); InterlockedExchange(&g_mode, M_IDLE); return; }
    CloseHandle(pi.hThread); g_game_proc = pi.hProcess;
    CloseHandle(CreateThread(NULL, 0, watch_game, NULL, 0, NULL));
    InterlockedExchange(&g_mode, M_LOGIN);
    ui_log("OverField started. Log in with your official account as usual.");
    InterlockedExchange(&g_starting, 0);
}

static void do_save(int quiet) {
    char path[MAX_PATH];
    if (!save_backup(path, sizeof path)) {
        if (!quiet) MessageBoxW(g_win, g_mode == M_WATCH ? L"Nothing to save yet. In the game, go back to the title screen and log in again - the login is what holds your account."
                                                        : L"Nothing to save yet - press Open game and log in first.", L"Rozefield Backup", MB_OK);
        return;
    }
    ui_log("Backup saved: %s", path);
    g_saved_once = 1; MultiByteToWideChar(CP_UTF8, 0, path, -1, g_savedpath, MAX_PATH);
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
    if (id) {
        wchar_t p[MAX_PATH];
        if (SHGetPathFromIDListW(id, p)) {
            WideCharToMultiByte(CP_ACP, 0, p, -1, g_game, MAX_PATH, NULL, NULL);
            char ini[MAX_PATH]; ini_path(ini); WritePrivateProfileStringA("game", "folder", g_game, ini);
            ui_log(has_launcher(g_game) ? "Game folder: %s" : "launcher.exe is not in %s - choose the OverField folder.", g_game);
        }
        CoTaskMemFree(id);
    }
}

/* ------------------------------------------------------------------ watch a game that is already running
 * The game is already talking to the official server, so nothing can be fetched for it; this only listens.
 * Windows lets an administrator read the PC's own network traffic (a raw socket with SIO_RCVALL). The game's
 * connection to its game server is picked out, put back in order, and recorded like a relayed one. */
#define SEGMAX 64
struct tcpdir { int synced; uint32_t next; int have; unsigned char *buf; size_t len, cap; struct { uint32_t seq; int n; unsigned char *d; } seg[SEGMAX]; };
struct tcpflow { uint16_t lport; struct tcpdir d[2]; };
static struct tcpflow g_flows[16];
static uint32_t g_watch_ip, g_watch_local; static uint16_t g_watch_port;
static volatile LONG g_pk_all, g_pk_game, g_pk_frames;
static FILE *g_dbg; static int g_dbg_n;

static int known_id(uint64_t id) {
    int lo = 0, hi = NKNOWN - 1;
    while (lo <= hi) { int m = (lo + hi) / 2; if (KNOWN_IDS[m] == id) return 1; if (KNOWN_IDS[m] < id) lo = m + 1; else hi = m - 1; }
    return 0;
}
/* 1 = a whole frame, 0 = need more bytes, -1 = not a frame start. When joining a connection mid-stream the
 * first bytes are the middle of a frame: a frame start needs a known message id, a sane size, and (when the
 * bytes are there) another frame right after it. */
static int frame_ok(const unsigned char *p, size_t avail, size_t *tot, struct head *h, int synced) {
    if (avail < 2) return 0;
    size_t hl = (p[0] << 8) | p[1];
    if (hl < 2 || hl > 48) return -1;
    if (avail < 2 + hl) return 0;
    if (p[2] != 0x08 && p[2] != 0x10) return -1;   /* PacketHead starts with field 1 or 2 */
    parse_head(p + 2, p + 2 + hl, h);
    if (!known_id(h->msg_id) || h->body_len > (4u << 20) || h->flag > 1) return -1;
    *tot = 2 + hl + h->body_len;
    if (avail < *tot) return 0;
    if (!synced) {   /* confirm with the next frame's header */
        if (avail < *tot + 3) return 0;
        const unsigned char *q = p + *tot; size_t hl2 = (q[0] << 8) | q[1];
        if (hl2 < 2 || hl2 > 48 || (q[2] != 0x08 && q[2] != 0x10)) return -1;
    }
    return 1;
}

static void watch_feed(struct tcpdir *t, int dir, int conn, const unsigned char *d, size_t n) {
    if (t->len + n > t->cap) { t->cap = (t->len + n) * 2 + 4096; t->buf = (unsigned char *)realloc(t->buf, t->cap); }
    memcpy(t->buf + t->len, d, n); t->len += n;
    size_t off = 0;
    for (;;) {
        size_t tot; struct head h;
        int r = frame_ok(t->buf + off, t->len - off, &tot, &h, t->synced);
        if (r < 0) { off++; t->synced = 0; continue; }   /* joined mid-frame: slide until a frame lines up */
        if (r == 0) {
            if (!t->synced && t->len - off > (1u << 20)) { off++; continue; }   /* a false start waiting forever */
            break;
        }
        t->synced = 1;
        const unsigned char *f = t->buf + off;
        size_t hl = (f[0] << 8) | f[1];
        if (dir == 0 && h.msg_id == 1001) record(0, conn, f, (uint32_t)(2 + hl));
        else record(dir, conn, f, (uint32_t)tot);
        InterlockedIncrement(&g_pk_frames);
        if (dir == 1) {
            if (h.msg_id == 1006 && !g_player[0]) {
                find_name(f + 2 + hl, h.body_len, h.flag == 1);
                if (g_player[0]) ui_log("Caught the login: %s. Open the screens the checklist still shows.", g_player);
                PostMessageW(g_win, WM_CHECK, 0, 0);
            }
            mark_check((int)h.msg_id);
        }
        off += tot;
    }
    memmove(t->buf, t->buf + off, t->len - off); t->len -= off;
}

static void watch_drain(struct tcpflow *fl, int dir) {
    struct tcpdir *t = &fl->d[dir];
    for (int again = 1; again;) {
        again = 0;
        for (int i = 0; i < SEGMAX; i++) {
            if (!t->seg[i].d) continue;
            int32_t a2 = (int32_t)(t->seg[i].seq - t->next);
            if (a2 <= 0) {
                if (-a2 < t->seg[i].n) { watch_feed(t, dir, fl->lport, t->seg[i].d + -a2, t->seg[i].n - -a2); t->next += t->seg[i].n - -a2; }
                free(t->seg[i].d); t->seg[i].d = NULL; again = 1;
            }
        }
    }
}

static void watch_segment(struct tcpflow *fl, int dir, uint32_t seq, int syn, const unsigned char *d, int n) {
    struct tcpdir *t = &fl->d[dir];
    if (syn) { t->next = seq + 1; t->have = 1; t->len = 0; t->synced = 1; return; }
    if (!t->have) { t->next = seq; t->have = 1; }
    if (n <= 0) return;
    int32_t ahead = (int32_t)(seq - t->next);
    if (ahead > 0) {                              /* early: keep it until the gap is filled */
        int slot = -1;
        for (int i = 0; i < SEGMAX; i++) if (!t->seg[i].d) { slot = i; break; }
        if (slot < 0) {   /* a packet was missed for good: skip the gap and find the next frame start */
            uint32_t mn = seq;
            for (int i = 0; i < SEGMAX; i++) if ((int32_t)(t->seg[i].seq - mn) < 0) mn = t->seg[i].seq;
            t->next = mn; t->len = 0; t->synced = 0;
            watch_drain(fl, dir);
            ahead = (int32_t)(seq - t->next);
            if (ahead > 0) {   /* still a gap after what was held: skip to this one */
                t->next = seq; t->len = 0; t->synced = 0; ahead = 0;
            }
        } else {
            t->seg[slot].seq = seq; t->seg[slot].n = n; t->seg[slot].d = (unsigned char *)malloc(n); memcpy(t->seg[slot].d, d, n);
            return;
        }
    }
    if (-ahead >= n) return;                      /* already have it */
    d += -ahead; n -= -ahead;
    watch_feed(t, dir, fl->lport, d, n); t->next += n;
    watch_drain(fl, dir);
}

static void watch_packet(unsigned char *pkt, int n);
static DWORD WINAPI watch_thread(LPVOID a) {
    SOCKET s = socket(AF_INET, SOCK_RAW, IPPROTO_IP);
    struct sockaddr_in sa = {0}; sa.sin_family = AF_INET; sa.sin_addr.s_addr = g_watch_local;
    DWORD on = RCVALL_ON, br = 0;
    if (s == INVALID_SOCKET || bind(s, (struct sockaddr *)&sa, sizeof sa) != 0 ||
        WSAIoctl(s, SIO_RCVALL, &on, sizeof on, NULL, 0, &br, NULL, NULL) != 0) {
        ui_log("Could not listen to the network (error %d). Try Open game instead.", WSAGetLastError());
        InterlockedExchange(&g_mode, M_IDLE); PostMessageW(g_win, WM_CHECK, 0, 0); return 0;
    }
    snprintf(g_tmppath, sizeof g_tmppath, "%srecording.tmp", g_exedir);
    if (!g_tmp) g_tmp = fopen(g_tmppath, "wb+");
    { char dp[MAX_PATH]; snprintf(dp, sizeof dp, "%swatch_debug.bin", g_exedir); g_dbg = fopen(dp, "wb"); }
    ui_log("Watching your running game. To save your account, go back to the title screen in the game and log in again.");
    static unsigned char pkt[65536];
    int n;
    while ((n = recv(s, (char *)pkt, sizeof pkt, 0)) > 0) watch_packet(pkt, n);
    closesocket(s);
    return 0;
}

static void watch_packet(unsigned char *pkt, int n) {
    {
        InterlockedIncrement(&g_pk_all);
        if (n < 20 || (pkt[0] >> 4) != 4 || pkt[9] != 6) return;
        int ihl = (pkt[0] & 15) * 4, tl = (pkt[2] << 8) | pkt[3];
        if (tl > n || tl < ihl + 20) tl = n;   /* coalesced receives can carry a 0 / short IP length */
        uint32_t src, dst; memcpy(&src, pkt + 12, 4); memcpy(&dst, pkt + 16, 4);
        const unsigned char *tcp = pkt + ihl; if (ihl + 20 > tl) return;
        uint16_t sp = (tcp[0] << 8) | tcp[1], dp = (tcp[2] << 8) | tcp[3];
        uint32_t seq = ((uint32_t)tcp[4] << 24) | (tcp[5] << 16) | (tcp[6] << 8) | tcp[7];
        int thl = (tcp[12] >> 4) * 4, syn = tcp[13] & 2;
        int dir;
        if (dp == g_watch_port && (!g_watch_ip || dst == g_watch_ip)) dir = 0;
        else if (sp == g_watch_port && (!g_watch_ip || src == g_watch_ip)) dir = 1;
        else return;
        InterlockedIncrement(&g_pk_game);
        if (g_dbg && g_dbg_n < 400) {   /* first packets of the game's connection, for diagnosis */
            uint32_t len = (uint32_t)n; fwrite(&len, 4, 1, g_dbg); fwrite(pkt, 1, n, g_dbg); fflush(g_dbg); g_dbg_n++;
        }
        uint16_t lport = dir == 0 ? sp : dp;
        struct tcpflow *fl = NULL;
        for (int i = 0; i < 16; i++) if (g_flows[i].lport == lport) { fl = &g_flows[i]; break; }
        if (!fl) for (int i = 0; i < 16; i++) if (!g_flows[i].lport) { fl = &g_flows[i]; fl->lport = lport; break; }
        if (!fl) return;
        watch_segment(fl, dir, seq, syn, tcp + thl, tl - ihl - thl);
    }
}

static DWORD WINAPI watch_stats(LPVOID a) {
    LONG la = -1, lg = -1, lf = -1;
    for (int i = 0; g_mode == M_WATCH; i++) {
        Sleep(5000);
        if (g_pk_all != la || g_pk_game != lg || g_pk_frames != lf) {
            la = g_pk_all; lg = g_pk_game; lf = g_pk_frames;
            ui_log("Listening: %ld packets on this PC, %ld from the game's connection, %ld game messages saved.", la, lg, lf);
        }
    }
    return 0;
}

static int is_admin(void) {
    BOOL r = FALSE; HANDLE tok;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        TOKEN_ELEVATION e; DWORD sz;
        if (GetTokenInformation(tok, TokenElevation, &e, sizeof e, &sz)) r = e.TokenIsElevated;
        CloseHandle(tok);
    }
    return r;
}

static void start_watch(void) {
    if (g_mode != M_IDLE && g_mode != M_DONE) return;
    if (!is_admin()) {   /* reading the PC's own traffic needs one admin prompt: reopen this window elevated */
        wchar_t me[MAX_PATH]; GetModuleFileNameW(NULL, me, MAX_PATH);
        SHELLEXECUTEINFOW ei = {sizeof ei}; ei.lpVerb = L"runas"; ei.lpFile = me; ei.lpParameters = L"--watch"; ei.nShow = SW_SHOWNORMAL;
        if (ShellExecuteExW(&ei)) { restore_all(); ExitProcess(0); }
        ui_log("Watching needs administrator rights (the prompt was closed).");
        return;
    }
    /* find the game's connection to its game server */
    DWORD pid = find_launcher(), sz = 0;
    g_watch_ip = 0; g_watch_port = 11001; g_watch_local = 0;
    GetExtendedTcpTable(NULL, &sz, FALSE, AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS, 0);
    MIB_TCPTABLE_OWNER_PID *tb = (MIB_TCPTABLE_OWNER_PID *)malloc(sz + 1024);
    if (tb && GetExtendedTcpTable(tb, &sz, FALSE, AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS, 0) == NO_ERROR) {
        for (DWORD i = 0; i < tb->dwNumEntries; i++) {
            MIB_TCPROW_OWNER_PID *r = &tb->table[i];
            if (pid && r->dwOwningPid == pid && ntohs((u_short)r->dwRemotePort) == 11001) {
                g_watch_ip = r->dwRemoteAddr; g_watch_local = r->dwLocalAddr; break;
            }
        }
    }
    free(tb);
    if (!g_watch_local) {   /* not connected yet: listen on the network card that reaches the internet */
        SOCKET u = socket(AF_INET, SOCK_DGRAM, 0); struct sockaddr_in t = {0}; t.sin_family = AF_INET; t.sin_port = htons(53);
        inet_pton(AF_INET, "8.8.8.8", &t.sin_addr); connect(u, (struct sockaddr *)&t, sizeof t);
        struct sockaddr_in me; int ml = sizeof me; getsockname(u, (struct sockaddr *)&me, &ml); closesocket(u);
        g_watch_local = me.sin_addr.s_addr;
    }
    InterlockedExchange(&g_mode, M_WATCH);
    {
        char a[32], b[32]; struct in_addr x;
        x.s_addr = g_watch_ip; inet_ntop(AF_INET, &x, a, sizeof a); x.s_addr = g_watch_local; inet_ntop(AF_INET, &x, b, sizeof b);
        if (g_watch_ip) ui_log("Found the game's connection: official %s:%d, this PC %s.", a, g_watch_port, b);
        else ui_log("Game connection not found yet (port %d); listening on %s for it.", g_watch_port, b);
    }
    CloseHandle(CreateThread(NULL, 0, watch_stats, NULL, 0, NULL));
    if (wd_load()) {
        snprintf(g_tmppath, sizeof g_tmppath, "%srecording.tmp", g_exedir);
        if (!g_tmp) g_tmp = fopen(g_tmppath, "wb+");
        ui_log("Watching your running game (WinDivert).");
        CloseHandle(CreateThread(NULL, 0, watch_wd_thread, NULL, 0, NULL));
        return;
    }
    if (!pid) ui_log("OverField is not running yet - start it any way you like; this window is listening.");
    CloseHandle(CreateThread(NULL, 0, watch_thread, NULL, 0, NULL));
}

/* ------------------------------------------------------------------ WinDivert (WinDivert.dll + WinDivert64.sys next to the exe)
 * Used two ways, both only for the game's own connection to the OFFICIAL game server (port 11001):
 *  - reconnect: the game's next connection is steered into this window's relay (packet addresses swapped, the
 *    streamdump way), so the relay can fetch everything; the relay talks to the official server itself.
 *  - watch: a read-only copy of the traffic, if the reconnect isn't wanted or fails. */
typedef HANDLE (*tWDOpen)(const char *, WINDIVERT_LAYER, INT16, UINT64);
typedef BOOL (*tWDRecv)(HANDLE, VOID *, UINT, UINT *, WINDIVERT_ADDRESS *);
typedef BOOL (*tWDSend)(HANDLE, const VOID *, UINT, UINT *, const WINDIVERT_ADDRESS *);
typedef BOOL (*tWDCalc)(VOID *, UINT, WINDIVERT_ADDRESS *, UINT64);
typedef BOOL (*tWDClose)(HANDLE);
static tWDOpen pWDOpen; static tWDRecv pWDRecv; static tWDSend pWDSend; static tWDCalc pWDCalc; static tWDClose pWDClose;
static HANDLE g_wd_redirect = INVALID_HANDLE_VALUE;
#define PROXY_PORT 41101
#define UP_PORT0 41110
#define UP_PORT1 41125

static int write_if_changed(const char *path, const unsigned char *d, DWORD n) {
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) { DWORD sz = GetFileSize(f, NULL); CloseHandle(f); if (sz == n) return 1; }
    f = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return 0;
    DWORD w = 0; WriteFile(f, d, n, &w, NULL); CloseHandle(f);
    return w == n;
}
static int wd_load(void) {
    if (pWDOpen) return 1;
    /* the driver ships inside this exe: unpack it to %LOCALAPPDATA%\RozefieldBackup once */
    char dir[MAX_PATH], p[MAX_PATH], sy[MAX_PATH];
    if (!GetEnvironmentVariableA("LOCALAPPDATA", dir, MAX_PATH)) snprintf(dir, sizeof dir, "%s", g_exedir);
    strncat(dir, "\\RozefieldBackup", sizeof dir - strlen(dir) - 1); CreateDirectoryA(dir, NULL);
    snprintf(p, sizeof p, "%s\\WinDivert.dll", dir); snprintf(sy, sizeof sy, "%s\\WinDivert64.sys", dir);
    if (!write_if_changed(p, WD_DLL, sizeof WD_DLL) || !write_if_changed(sy, WD_SYS, sizeof WD_SYS)) return 0;
    HMODULE m = LoadLibraryA(p);
    if (!m) return 0;
    pWDOpen = (tWDOpen)GetProcAddress(m, "WinDivertOpen"); pWDRecv = (tWDRecv)GetProcAddress(m, "WinDivertRecv");
    pWDSend = (tWDSend)GetProcAddress(m, "WinDivertSend"); pWDCalc = (tWDCalc)GetProcAddress(m, "WinDivertHelperCalcChecksums");
    pWDClose = (tWDClose)GetProcAddress(m, "WinDivertClose");
    return pWDOpen && pWDRecv && pWDSend && pWDCalc && pWDClose;
}

static DWORD WINAPI watch_wd_thread(LPVOID a) {
    HANDLE h = pWDOpen("tcp and (tcp.SrcPort == 11001 or tcp.DstPort == 11001)", WINDIVERT_LAYER_NETWORK, 0,
                       WINDIVERT_FLAG_SNIFF | WINDIVERT_FLAG_RECV_ONLY);
    if (h == INVALID_HANDLE_VALUE) { ui_log("Could not start listening (WinDivert error %lu).", GetLastError()); InterlockedExchange(&g_mode, M_IDLE); return 0; }
    static unsigned char pkt[65536 + 64]; UINT n; WINDIVERT_ADDRESS addr;
    while (g_mode == M_WATCH && pWDRecv(h, pkt, sizeof pkt, &n, &addr)) watch_packet(pkt, (int)n);
    pWDClose(h);
    return 0;
}

static DWORD WINAPI redirect_thread(LPVOID a) {
    static unsigned char pkt[65536 + 64]; UINT n; WINDIVERT_ADDRESS addr;
    while (pWDRecv(g_wd_redirect, pkt, sizeof pkt, &n, &addr)) {
        if (n < 40 || (pkt[0] >> 4) != 4) { pWDSend(g_wd_redirect, pkt, n, NULL, &addr); continue; }
        int ihl = (pkt[0] & 15) * 4; unsigned char *tcp = pkt + ihl;
        uint16_t sp = (tcp[0] << 8) | tcp[1], dp = (tcp[2] << 8) | tcp[3];
        unsigned char tmp[4];
        memcpy(tmp, pkt + 16, 4); memcpy(pkt + 16, pkt + 12, 4); memcpy(pkt + 12, tmp, 4);   /* swap addresses */
        if (dp == 11001) { tcp[2] = PROXY_PORT >> 8; tcp[3] = PROXY_PORT & 255; }            /* game -> relay */
        else if (sp == PROXY_PORT) { tcp[0] = 11001 >> 8; tcp[1] = 11001 & 255; }           /* relay -> game */
        addr.Outbound = 0;
        pWDCalc(pkt, n, &addr, 0);
        pWDSend(g_wd_redirect, pkt, n, NULL, &addr);
    }
    return 0;
}

static SOCKET tcp_listen_any(int port) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port); a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(s, (struct sockaddr *)&a, sizeof a) != 0 || listen(s, 16) != 0) { closesocket(s); return INVALID_SOCKET; }
    return s;
}

/* the relay's own connection to the official game server uses a local port the redirect leaves alone */
static SOCKET tcp_connect_up(const char *ip, int port) {
    for (int q = UP_PORT0; q <= UP_PORT1; q++) {
        SOCKET s = socket(AF_INET, SOCK_STREAM, 0); BOOL yes = 1;
        setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (char *)&yes, sizeof yes);
        struct sockaddr_in me = {0}; me.sin_family = AF_INET; me.sin_port = htons((u_short)q);
        if (bind(s, (struct sockaddr *)&me, sizeof me) != 0) { closesocket(s); continue; }
        struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_port = htons((u_short)port); inet_pton(AF_INET, ip, &a.sin_addr);
        if (connect(s, (struct sockaddr *)&a, sizeof a) == 0) return s;
        closesocket(s);
    }
    return INVALID_SOCKET;
}

static int find_game_conn(MIB_TCPROW *out) {
    DWORD pid = find_launcher(), sz = 0; int ok = 0;
    GetExtendedTcpTable(NULL, &sz, FALSE, AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS, 0);
    MIB_TCPTABLE_OWNER_PID *tb = (MIB_TCPTABLE_OWNER_PID *)malloc(sz + 4096);
    if (tb && GetExtendedTcpTable(tb, &sz, FALSE, AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS, 0) == NO_ERROR)
        for (DWORD i = 0; i < tb->dwNumEntries && !ok; i++) {
            MIB_TCPROW_OWNER_PID *r = &tb->table[i];
            if (pid && r->dwOwningPid == pid && ntohs((u_short)r->dwRemotePort) == 11001 && r->dwState == MIB_TCP_STATE_ESTAB) {
                out->dwState = r->dwState; out->dwLocalAddr = r->dwLocalAddr; out->dwLocalPort = r->dwLocalPort;
                out->dwRemoteAddr = r->dwRemoteAddr; out->dwRemotePort = r->dwRemotePort; ok = 1;
            }
        }
    free(tb);
    return ok;
}

static void start_reconnect(void) {
    if (g_mode != M_IDLE && g_mode != M_DONE && g_mode != M_WATCH) return;
    if (!is_admin()) {
        wchar_t me[MAX_PATH]; GetModuleFileNameW(NULL, me, MAX_PATH);
        SHELLEXECUTEINFOW ei = {sizeof ei}; ei.lpVerb = L"runas"; ei.lpFile = me; ei.lpParameters = L"--reconnect"; ei.nShow = SW_SHOWNORMAL;
        if (ShellExecuteExW(&ei)) { restore_all(); ExitProcess(0); }
        ui_log("This needs administrator rights (the prompt was closed).");
        return;
    }
    if (!wd_load()) { ui_log("Could not unpack the network helper (WinDivert) - only watching is possible."); start_watch(); return; }
    MIB_TCPROW row;
    if (!find_game_conn(&row)) { ui_log("OverField isn't connected to its server yet. Log in first, then press Use running game."); return; }
    struct in_addr ga; ga.s_addr = row.dwRemoteAddr; inet_ntop(AF_INET, &ga, g_gate_ip, sizeof g_gate_ip); g_gate_port = 11001;
    g_up_bound = 1;
    if (!g_running) {
        SOCKET l = tcp_listen_any(PROXY_PORT);
        if (l == INVALID_SOCKET) { ui_log("Port %d is busy - close other copies of this window.", PROXY_PORT); return; }
        CloseHandle(CreateThread(NULL, 0, gate_server, (LPVOID)(uintptr_t)l, 0, NULL));
        snprintf(g_tmppath, sizeof g_tmppath, "%srecording.tmp", g_exedir);
        if (!g_tmp) g_tmp = fopen(g_tmppath, "wb+");
        g_running = 1;
    }
    if (g_wd_redirect == INVALID_HANDLE_VALUE) {
        char f[400];
        snprintf(f, sizeof f, "outbound and tcp and ((ip.DstAddr == %s and tcp.DstPort == 11001 and (tcp.SrcPort < %d or tcp.SrcPort > %d)) or tcp.SrcPort == %d)",
                 g_gate_ip, UP_PORT0, UP_PORT1, PROXY_PORT);
        g_wd_redirect = pWDOpen(f, WINDIVERT_LAYER_NETWORK, 0, 0);
        if (g_wd_redirect == INVALID_HANDLE_VALUE) { ui_log("Could not start WinDivert (error %lu). Falling back to watching.", GetLastError()); start_watch(); return; }
        CloseHandle(CreateThread(NULL, 0, redirect_thread, NULL, 0, NULL));
    }
    InterlockedExchange(&g_mode, M_LOGIN);
    row.dwState = MIB_TCP_STATE_DELETE_TCB;
    DWORD e = SetTcpEntry(&row);
    if (e != NO_ERROR) { ui_log("Could not make the game reconnect (error %lu).", e); return; }
    ui_log("Asked the game to reconnect to official through this window. If the game shows a reconnect button, press it.");
}

/* ------------------------------------------------------------------ painted launcher-style window */
#define WW 1100
#define WH 800
#define C_INK RGB(244, 246, 248)   /* OverField UI theme: soft white */
#define C_ACC RGB(19, 181, 197)    /* cyan (the game's Confirm) */
#define C_BLUE RGB(45, 156, 219)   /* Over Field blue */
#define C_PINK RGB(230, 0, 110)    /* badge pink */
#define C_CARD RGB(255, 255, 255)
#define C_TILE RGB(236, 237, 241)
#define C_LINE RGB(214, 218, 226)
#define C_OK RGB(60, 194, 122)
#define C_TXT RGB(42, 44, 54)
#define C_MUTE RGB(122, 126, 142)
#define C_WARN RGB(232, 140, 20)
enum { B_NONE, B_CLOSE, B_MIN, B_MAIN, B_RUNNING, B_SAVE, B_FOLDER, B_LOG, B_OPENDIR,
       B_TAB0, B_TAB1, B_PCHANGE, B_PFOUND0, B_PFOUND1, B_PCOPY, B_PINPLACE, B_PGO, B_PUNDO };
static RECT r_close = {WW - 52, 10, WW - 12, 46}, r_min = {WW - 96, 10, WW - 56, 46};
static RECT r_main = {WW - 252, WH - 92, WW - 36, WH - 32}, r_run = {WW - 618, WH - 86, WW - 444, WH - 38}, r_save = {WW - 432, WH - 86, WW - 268, WH - 38};
static RECT r_folder = {14, WH - 128, 58, WH - 84}, r_logb = {14, WH - 74, 58, WH - 30}, r_opendir = {0};
static HFONT f_title, f_big, f_h, f_body, f_small, f_btn, f_pct;
static HBITMAP g_bg; static int g_bgw, g_bgh;

typedef struct { UINT32 GdiplusVersion; void *cb; BOOL a, b; } GpInput;
int WINAPI GdiplusStartup(ULONG_PTR *, const GpInput *, void *);
int WINAPI GdipCreateBitmapFromFile(const WCHAR *, void **);
int WINAPI GdipCreateHBITMAPFromBitmap(void *, HBITMAP *, DWORD);
int WINAPI GdipDisposeImage(void *);
int WINAPI GdipCreateFromHDC(HDC, void **);
int WINAPI GdipDeleteGraphics(void *);
int WINAPI GdipSetInterpolationMode(void *, int);
int WINAPI GdipGetImageWidth(void *, UINT *);
int WINAPI GdipGetImageHeight(void *, UINT *);
int WINAPI GdipDrawImageRectRectI(void *, void *, int, int, int, int, int, int, int, int, int, void *, void *, void *);
static int g_gdip;
static void *img_load(const char *name) {   /* assets\<name>.png next to the exe (tools/extract_backup_assets.py) */
    if (!g_gdip) { ULONG_PTR tok; GpInput in = {1, NULL, FALSE, FALSE}; g_gdip = GdiplusStartup(&tok, &in, NULL) == 0 ? 1 : -1; }
    if (g_gdip < 0) return NULL;
    char p[MAX_PATH]; snprintf(p, sizeof p, "%sassets\\%s.png", g_exedir, name);
    wchar_t w[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, p, -1, w, MAX_PATH);
    void *bmp = NULL;
    return GdipCreateBitmapFromFile(w, &bmp) == 0 ? bmp : NULL;
}
/* draw img into r, cropped to fill it (cover); top-aligned when 'top' */
static void img_draw(HDC dc, void *img, RECT r, int top) {
    if (!img) return;
    UINT iw = 0, ih = 0; GdipGetImageWidth(img, &iw); GdipGetImageHeight(img, &ih);
    if (!iw || !ih) return;
    int rw = r.right - r.left, rh = r.bottom - r.top;
    double sc = (double)rw / iw > (double)rh / ih ? (double)rw / iw : (double)rh / ih;
    int sw = (int)(rw / sc), sh = (int)(rh / sc), sx = ((int)iw - sw) / 2, sy = top ? 0 : ((int)ih - sh) / 2;
    void *g = NULL; if (GdipCreateFromHDC(dc, &g) != 0) return;
    GdipSetInterpolationMode(g, 7);
    GdipDrawImageRectRectI(g, img, r.left, r.top, rw, rh, sx, sy, sw, sh, 2, NULL, NULL, NULL);
    GdipDeleteGraphics(g);
}
/* draw img inside r keeping its shape (contain) */
static void img_fit(HDC dc, void *img, RECT r) {
    if (!img) return;
    UINT iw = 0, ih = 0; GdipGetImageWidth(img, &iw); GdipGetImageHeight(img, &ih);
    if (!iw || !ih) return;
    int rw = r.right - r.left, rh = r.bottom - r.top;
    double sc = (double)rw / iw < (double)rh / ih ? (double)rw / iw : (double)rh / ih;
    int dw = (int)(iw * sc), dh = (int)(ih * sc);
    void *g = NULL; if (GdipCreateFromHDC(dc, &g) != 0) return;
    GdipSetInterpolationMode(g, 7);
    GdipDrawImageRectRectI(g, img, r.left + (rw - dw) / 2, r.top + (rh - dh) / 2, dw, dh, 0, 0, iw, ih, 2, NULL, NULL, NULL);
    GdipDeleteGraphics(g);
}
static void *g_icon[16], *g_map[16]; static int g_imgs_loaded;
static void load_images(void) {
    if (g_imgs_loaded) return; g_imgs_loaded = 1;
    for (int i = 0; i < (int)(sizeof CHECKS / sizeof CHECKS[0]) && i < 16; i++) { char n[64]; snprintf(n, 64, "icon_%s", CHECKS[i].icon); g_icon[i] = img_load(n); }
    for (int i = 0; i < NTOUR && i < 16; i++) { char n[64]; snprintf(n, 64, "map_%u", TOUR[i]); g_map[i] = img_load(n); }
}
static void load_background(void) {   /* background.jpg / .png next to the exe: a screenshot of your own Plaza */
    static const char *names[] = {"background.jpg", "background.png", "background.jpeg"};
    ULONG_PTR tok; GpInput in = {1, NULL, FALSE, FALSE};
    if (GdiplusStartup(&tok, &in, NULL) != 0) return;
    for (int i = 0; i < 3 && !g_bg; i++) {
        char p[MAX_PATH]; snprintf(p, sizeof p, "%s%s", g_exedir, names[i]);
        wchar_t w[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, p, -1, w, MAX_PATH);
        void *bmp = NULL;
        if (GdipCreateBitmapFromFile(w, &bmp) == 0 && bmp) { GdipCreateHBITMAPFromBitmap(bmp, &g_bg, 0xff11121b); GdipDisposeImage(bmp); }
    }
    if (g_bg) { BITMAP b; GetObject(g_bg, sizeof b, &b); g_bgw = b.bmWidth; g_bgh = b.bmHeight; }
}

static void fill_alpha(HDC dc, RECT r, COLORREF c, BYTE alpha, int radius) {
    int w = r.right - r.left, h = r.bottom - r.top; if (w <= 0 || h <= 0) return;
    HDC m = CreateCompatibleDC(dc); HBITMAP b = CreateCompatibleBitmap(dc, 1, 1); HGDIOBJ o = SelectObject(m, b);
    SetPixel(m, 0, 0, c);
    HRGN rg = radius ? CreateRoundRectRgn(r.left, r.top, r.right + 1, r.bottom + 1, radius, radius) : CreateRectRgn(r.left, r.top, r.right, r.bottom);
    SelectClipRgn(dc, rg);
    BLENDFUNCTION bf = {AC_SRC_OVER, 0, alpha, 0};
    AlphaBlend(dc, r.left, r.top, w, h, m, 0, 0, 1, 1, bf);
    SelectClipRgn(dc, NULL); DeleteObject(rg);
    SelectObject(m, o); DeleteObject(b); DeleteDC(m);
}
static void fill_round(HDC dc, RECT r, COLORREF c, int radius) {
    HBRUSH br = CreateSolidBrush(c); HRGN rg = CreateRoundRectRgn(r.left, r.top, r.right + 1, r.bottom + 1, radius, radius);
    FillRgn(dc, rg, br); DeleteObject(rg); DeleteObject(br);
}
static void outline_round(HDC dc, RECT r, COLORREF c, int radius) {
    HPEN p = CreatePen(PS_SOLID, 1, c); HGDIOBJ op = SelectObject(dc, p), ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    RoundRect(dc, r.left, r.top, r.right, r.bottom, radius, radius);
    SelectObject(dc, op); SelectObject(dc, ob); DeleteObject(p);
}
static void txt(HDC dc, HFONT f, COLORREF c, RECT r, const wchar_t *s, UINT fmt) {
    SelectObject(dc, f); SetTextColor(dc, c); SetBkMode(dc, TRANSPARENT); DrawTextW(dc, s, -1, &r, fmt | DT_NOPREFIX);
}
static void circle(HDC dc, int cx, int cy, int r, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c); HPEN p = CreatePen(PS_SOLID, 1, c);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p); Ellipse(dc, cx - r, cy - r, cx + r + 1, cy + r + 1);
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(b); DeleteObject(p);
}
static void tick(HDC dc, int cx, int cy, COLORREF c) {
    HPEN p = CreatePen(PS_SOLID, 2, c); HGDIOBJ o = SelectObject(dc, p);
    MoveToEx(dc, cx - 5, cy, NULL); LineTo(dc, cx - 1, cy + 4); LineTo(dc, cx + 6, cy - 4);
    SelectObject(dc, o); DeleteObject(p);
}
static void pill(HDC dc, RECT r, int primary, int hover, int enabled, const wchar_t *label) {
    int rad = r.bottom - r.top;
    if (primary) fill_round(dc, r, !enabled ? RGB(166, 216, 222) : hover ? RGB(14, 160, 176) : C_ACC, rad);
    else { fill_round(dc, r, hover && enabled ? RGB(232, 246, 248) : C_CARD, rad); outline_round(dc, r, C_LINE, rad); }
    txt(dc, primary ? f_btn : f_body, primary ? RGB(255, 255, 255) : (enabled ? C_TXT : C_MUTE), r, label, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static int target_pct(void) {
    int done = 0; for (int i = 0; i < NCHECK; i++) done += CHECKS[i].done;
    switch (g_mode) {
    case M_STARTING: return 2;
    case M_LOGIN: return g_player[0] ? 10 : 5;
    case M_FETCH: { int v = 10 + (int)(78.0 * (g_fetch_got > NQUERY ? NQUERY : g_fetch_got) / NQUERY) + (int)(10.0 * g_tour_done_n / NTOUR_REAL); return v > 98 ? 98 : v; }
    case M_DONE: return 100;
    case M_WATCH: return (int)(100.0 * done / NCHECK);
    default: return g_player[0] ? 100 : 0;
    }
}


/* ---------------------------------------------------------------- Play on Rozefield (second tab)
 * Points an existing OverField install (Steam, the OverField launcher, or a copy) at a Rozefield server:
 *   - login window: launcher_Data\Plugins\Win\PCSDK_release\PCSDKUI.exe -> the Rozefield login (official kept as .orig)
 *   - StreamingAssets\Config.txt: UseCustomConfig = TRUE, RemoteServerIP = the server (original kept as .orig)
 *   - il2cpp global-metadata.dat: the game's address lookup -> the server (or this PC), original kept as .orig
 *   - rozefield_servers.json in the game folder: the default server for the login window's list
 * "Make a Rozefield copy" copies the whole game first, so the official one stays as it is. Undo puts every file back.
 * The Rozefield login comes from rozefield\PCSDKUI.exe next to this exe. */
static int g_tab;                                  /* 0 = back up, 1 = play on Rozefield */
static char g_pgame[MAX_PATH], g_found[2][MAX_PATH];
static int g_pmode;                                /* 0 = make a copy first, 1 = change this game */
static HWND g_psrv;
static wchar_t g_pmsg[400] = L"";
static COLORREF g_pmsgc = RGB(122, 126, 142);
static volatile LONG g_pbusy; static volatile LONGLONG g_pdone, g_ptotal;
static RECT r_tab0 = {WW - 420, 34, WW - 300, 70}, r_tab1 = {WW - 292, 34, WW - 110, 70};
static RECT r_pchange = {WW - 250, 186, WW - 140, 218}, r_pfound[2] = {{124, 226, 330, 254}, {338, 226, 560, 254}};
static RECT r_pcopy = {124, 296, 640, 336}, r_pinplace = {124, 344, 640, 384}, r_pgo = {124, 560, 470, 612}, r_pundo = {486, 560, 700, 612};

static void find_launcher_install(char *out) {   /* the OverField launcher (Uninstall entry) installs into <dir>\OverField Game */
    out[0] = 0;
    const char *roots[] = {"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall", "Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"};
    HKEY hives[] = {HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER};
    for (int h = 0; h < 2 && !out[0]; h++) for (int r = 0; r < 2 && !out[0]; r++) {
        HKEY k; if (RegOpenKeyExA(hives[h], roots[r], 0, KEY_READ, &k)) continue;
        char sub[256]; for (DWORD i = 0; !out[0]; i++) {
            DWORD sl = sizeof sub; if (RegEnumKeyExA(k, i, sub, &sl, NULL, NULL, NULL, NULL)) break;
            char name[256] = "", loc[MAX_PATH] = ""; DWORD n1 = sizeof name, n2 = sizeof loc;
            RegGetValueA(k, sub, "DisplayName", RRF_RT_REG_SZ, NULL, name, &n1);
            if (!strstr(name, "OverField") || strstr(name, "Steam")) continue;
            if (RegGetValueA(k, sub, "InstallLocation", RRF_RT_REG_SZ, NULL, loc, &n2) == ERROR_SUCCESS && loc[0]) {
                char p[MAX_PATH]; size_t l = strlen(loc); if (l && (loc[l - 1] == '\\' || loc[l - 1] == '"')) loc[l - 1] = 0;
                snprintf(p, sizeof p, "%s\\OverField Game", loc[0] == '"' ? loc + 1 : loc);
                if (has_launcher(p)) snprintf(out, MAX_PATH, "%s", p);
            }
        }
        RegCloseKey(k);
    }
}
static void pmsg(COLORREF c, const wchar_t *fmt, ...) {
    va_list ap; va_start(ap, fmt); vswprintf(g_pmsg, 400, fmt, ap); va_end(ap); g_pmsgc = c;
}
static const char B32[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
static int read_code(const char *s, char *ip) {   /* RZ-XXXX-XXX: an IPv4 address in base32 */
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
static int keep_orig(const char *f) {   /* first change only: the file as it came becomes <f>.orig */
    char o[MAX_PATH + 8]; snprintf(o, sizeof o, "%s.orig", f);
    return GetFileAttributesA(o) != INVALID_FILE_ATTRIBUTES || CopyFileA(f, o, TRUE);
}
static char *slurp(const char *f, long *n) {
    FILE *in = fopen(f, "rb"); if (!in) return NULL;
    fseek(in, 0, SEEK_END); *n = ftell(in); fseek(in, 0, SEEK_SET);
    char *d = (char *)malloc(*n + 1); if (fread(d, 1, *n, in) != (size_t)*n) { fclose(in); free(d); return NULL; }
    fclose(in); d[*n] = 0; return d;
}
static int spill(const char *f, const char *d, long n) { FILE *o = fopen(f, "wb"); if (!o) return 0; int ok = fwrite(d, 1, n, o) == (size_t)n; fclose(o); return ok; }

static int rz_apply(const char *dir, const char *name, const char *ip, wchar_t *err) {
    char f[MAX_PATH], src[MAX_PATH];
    /* 1. login window */
    snprintf(src, sizeof src, "%srozefield\\PCSDKUI.exe", g_exedir);
    snprintf(f, sizeof f, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe", dir);
    if (GetFileAttributesA(src) == INVALID_FILE_ATTRIBUTES) { wcscpy(err, L"The Rozefield login (rozefield\\PCSDKUI.exe) is missing next to Rozefield Backup.exe."); return 0; }
    if (GetFileAttributesA(f) == INVALID_FILE_ATTRIBUTES) { wcscpy(err, L"This folder has no login window (launcher_Data\\Plugins\\Win\\PCSDK_release)."); return 0; }
    if (!keep_orig(f) || !CopyFileA(src, f, FALSE)) { wcscpy(err, L"Couldn't replace the login window. Close the game and try again."); return 0; }
    { char ini[MAX_PATH]; snprintf(ini, sizeof ini, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\rozefield_sdk.ini", dir);
      WritePrivateProfileStringA("server", "ip", ip, ini); WritePrivateProfileStringA("server", "address", name, ini); }
    /* 2. Config.txt */
    snprintf(f, sizeof f, "%s\\launcher_Data\\StreamingAssets\\Config.txt", dir);
    long n; char *t = slurp(f, &n);
    if (t && keep_orig(f)) {
        char *o = (char *)calloc(n + 256, 1); int c = 0, r = 0;
        for (char *line = t; *line;) {
            char *nl = strchr(line, '\n'); size_t len = nl ? (size_t)(nl - line + 1) : strlen(line);
            char *k = line; while (*k == ' ' || *k == '\t') k++;
            if (!_strnicmp(k, "UseCustomConfig", 15)) { strcat(o, "UseCustomConfig = TRUE\r\n"); c = 1; }
            else if (!_strnicmp(k, "RemoteServerIP", 14)) { sprintf(o + strlen(o), "RemoteServerIP = %s\r\n", ip); r = 1; }
            else strncat(o, line, len);
            line += len;
        }
        if (!c) strcat(o, "\r\nUseCustomConfig = TRUE\r\n");
        if (!r) sprintf(o + strlen(o), "RemoteServerIP = %s\r\n", ip);
        spill(f, o, (long)strlen(o)); free(o);
    }
    free(t);
    /* 3. the address lookup, always from the original file */
    snprintf(f, sizeof f, "%s\\launcher_Data\\il2cpp_data\\Metadata\\global-metadata.dat", dir);
    char fo[MAX_PATH + 8]; snprintf(fo, sizeof fo, "%s.orig", f);
    unsigned char *d = (unsigned char *)slurp(GetFileAttributesA(fo) != INVALID_FILE_ATTRIBUTES ? fo : f, &n);
    if (d) {
        const char *target = strlen(ip) <= 12 ? ip : "127.0.0.1"; uint32_t lo, ls, ldo; memcpy(&lo, d + 8, 4); memcpy(&ls, d + 12, 4); memcpy(&ldo, d + 16, 4);
        int ok = 0;
        for (long i = ldo; i + 12 <= n && !ok; i++) {
            if (memcmp(d + i, HTTPDNS_IP, 12)) continue;
            int32_t pos = (int32_t)(i - ldo);
            for (uint32_t k = 0; k + 8 <= ls; k += 8) { uint32_t len; int32_t idx; memcpy(&len, d + lo + k, 4); memcpy(&idx, d + lo + k + 4, 4);
                if (idx == pos && len == 12) { memcpy(d + i, target, strlen(target)); len = (uint32_t)strlen(target); memcpy(d + lo + k, &len, 4); ok = 1; break; } }
        }
        if (ok && keep_orig(f)) spill(f, (char *)d, n);
        free(d);
    }
    /* 4. the default server for the login window */
    snprintf(f, sizeof f, "%s\\rozefield_servers.json", dir);
    char js[700]; snprintf(js, sizeof js, "{\"format\": \"rozefield-servers/1\", \"default\": \"%s\", \"servers\": [{\"name\": \"%s\", \"address\": \"%s\"}]}\n", name, name, name);
    spill(f, js, (long)strlen(js));
    return 1;
}
static int rz_undo(const char *dir) {
    const char *files[] = {"\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe", "\\launcher_Data\\StreamingAssets\\Config.txt", "\\launcher_Data\\il2cpp_data\\Metadata\\global-metadata.dat"};
    int n = 0;
    for (int i = 0; i < 3; i++) {
        char f[MAX_PATH], o[MAX_PATH + 8]; snprintf(f, sizeof f, "%s%s", dir, files[i]); snprintf(o, sizeof o, "%s.orig", f);
        if (GetFileAttributesA(o) != INVALID_FILE_ATTRIBUTES && CopyFileA(o, f, FALSE)) { DeleteFileA(o); n++; }
    }
    char f[MAX_PATH]; snprintf(f, sizeof f, "%s\\rozefield_servers.json", dir); DeleteFileA(f);
    return n;
}
static int is_patched(const char *dir) {
    char o[MAX_PATH]; snprintf(o, sizeof o, "%s\\launcher_Data\\Plugins\\Win\\PCSDK_release\\PCSDKUI.exe.orig", dir);
    return GetFileAttributesA(o) != INVALID_FILE_ATTRIBUTES;
}

static LONGLONG tree_size(const char *dir) {
    char pat[MAX_PATH]; snprintf(pat, sizeof pat, "%s\\*", dir); WIN32_FIND_DATAA fd; HANDLE h = FindFirstFileA(pat, &fd); LONGLONG t = 0;
    if (h == INVALID_HANDLE_VALUE) return 0;
    do { if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue; char p[MAX_PATH]; snprintf(p, sizeof p, "%s\\%s", dir, fd.cFileName);
         if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) t += tree_size(p); else t += ((LONGLONG)fd.nFileSizeHigh << 32) | fd.nFileSizeLow; } while (FindNextFileA(h, &fd));
    FindClose(h); return t;
}
static int tree_copy(const char *from, const char *to) {
    CreateDirectoryA(to, NULL);
    char pat[MAX_PATH]; snprintf(pat, sizeof pat, "%s\\*", from); WIN32_FIND_DATAA fd; HANDLE h = FindFirstFileA(pat, &fd); int ok = 1;
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
        char a[MAX_PATH], b[MAX_PATH]; snprintf(a, sizeof a, "%s\\%s", from, fd.cFileName); snprintf(b, sizeof b, "%s\\%s", to, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ok = tree_copy(a, b) && ok;
        else { if (!CopyFileA(a, b, FALSE)) ok = 0; InterlockedExchangeAdd64(&g_pdone, ((LONGLONG)fd.nFileSizeHigh << 32) | fd.nFileSizeLow); }
    } while (FindNextFileA(h, &fd));
    FindClose(h); return ok;
}

static char g_pname[256], g_pip[64], g_pdest[MAX_PATH];
static DWORD WINAPI patch_thread(LPVOID a) {
    wchar_t err[300] = L"";
    const char *dir = g_pgame;
    if (g_pmode == 0) {   /* copy first */
        g_ptotal = tree_size(g_pgame); g_pdone = 0;
        ULARGE_INTEGER freeb; char root[4] = {g_pdest[0], ':', '\\', 0};
        if (GetDiskFreeSpaceExA(root, &freeb, NULL, NULL) && (LONGLONG)freeb.QuadPart < g_ptotal + (200LL << 20)) {
            pmsg(RGB(220, 60, 70), L"Not enough free space on %hs (needs %lld MB).", root, (g_ptotal >> 20) + 200); InterlockedExchange(&g_pbusy, 0); return 0;
        }
        pmsg(RGB(122, 126, 142), L"Copying the game to %hs\x2026", g_pdest);
        if (!tree_copy(g_pgame, g_pdest)) { pmsg(RGB(220, 60, 70), L"Copying stopped (is the game open, or the disk full?). Try again."); InterlockedExchange(&g_pbusy, 0); return 0; }
        rz_undo(g_pdest);   /* a copy of an already changed game starts clean */
        dir = g_pdest;
    }
    if (rz_apply(dir, g_pname, g_pip, err)) {
        pmsg(RGB(40, 160, 80), g_pmode == 0 ? L"Done. Play on Rozefield with %hs\\launcher.exe (your official game is unchanged)." : L"Done. Start %hs\\launcher.exe to play on Rozefield. Undo puts the official login back.", dir);
        if (g_pmode == 0) ShellExecuteA(NULL, "open", dir, NULL, NULL, SW_SHOWNORMAL);
    } else pmsg(RGB(220, 60, 70), L"%ls", err);
    InterlockedExchange(&g_pbusy, 0); return 0;
}
static void patch_go(void) {
    if (g_pbusy) return;
    if (!g_pgame[0] || !has_launcher(g_pgame)) { pmsg(RGB(220, 60, 70), L"Choose the game folder first (the one with launcher.exe)."); return; }
    if (find_launcher()) { pmsg(RGB(220, 60, 70), L"Close the game first."); return; }
    wchar_t w[256]; GetWindowTextW(g_psrv, w, 256); char a[256]; WideCharToMultiByte(CP_UTF8, 0, w, -1, a, sizeof a, NULL, NULL);
    char *b = a; while (*b == ' ') b++; char *e = b + strlen(b); while (e > b && (e[-1] == ' ' || e[-1] == '/')) *--e = 0; if (!strncmp(b, "http://", 7)) b += 7;
    if (!*b) { pmsg(RGB(220, 60, 70), L"Type the server: invite code (RZ-XXXX-XXX), name or address."); return; }
    char ip[64];
    if (!read_code(b, ip)) {
        struct addrinfo hn = {0}, *r = NULL; hn.ai_family = AF_INET;
        if (getaddrinfo(b, NULL, &hn, &r) || !r) { pmsg(RGB(220, 60, 70), L"Can't find that server name."); return; }
        inet_ntop(AF_INET, &((struct sockaddr_in *)r->ai_addr)->sin_addr, ip, sizeof ip); freeaddrinfo(r);
    }
    snprintf(g_pname, sizeof g_pname, "%s", b); snprintf(g_pip, sizeof g_pip, "%s", ip);
    if (g_pmode == 0) {
        char parent[MAX_PATH]; snprintf(parent, sizeof parent, "%s", g_pgame); char *sl = strrchr(parent, '\\'); if (sl) *sl = 0;
        snprintf(g_pdest, sizeof g_pdest, "%s\\OverField Rozefield", parent);
        if (!_stricmp(g_pdest, g_pgame)) { g_pmode = 1; }
        else if (has_launcher(g_pdest)) {
            wchar_t q[MAX_PATH + 200]; swprintf(q, MAX_PATH + 200, L"A Rozefield copy already exists:\n%hs\n\nYes: point that copy at this server (fast).\nNo: copy the game again over it.", g_pdest);
            int rr = MessageBoxW(g_win, q, L"Play on Rozefield", MB_YESNOCANCEL | MB_ICONQUESTION);
            if (rr == IDCANCEL) return;
            if (rr == IDYES) { snprintf(g_pgame, sizeof g_pgame, "%s", g_pdest); g_pmode = 1; }
        }
    } else if (MessageBoxW(g_win, L"Change this game so it plays on Rozefield?\n\nIt stops logging in to the official servers until you press Undo. Make your backup with Rozefield Backup first.", L"Play on Rozefield", MB_OKCANCEL | MB_ICONQUESTION) != IDOK) return;
    InterlockedExchange(&g_pbusy, 1); pmsg(RGB(122, 126, 142), L"Working\x2026");
    CloseHandle(CreateThread(NULL, 0, patch_thread, NULL, 0, NULL));
}
static void patch_undo(void) {
    if (g_pbusy || !g_pgame[0]) return;
    if (find_launcher()) { pmsg(RGB(220, 60, 70), L"Close the game first."); return; }
    int n = rz_undo(g_pgame);
    if (n) pmsg(RGB(40, 160, 80), L"Undone: %d file%ls put back. This game uses the official servers again.", n, n == 1 ? L"" : L"s");
    else pmsg(RGB(122, 126, 142), L"Nothing to undo in this folder.");
}
static void patch_browse(void) {
    BROWSEINFOW bi = {0}; bi.hwndOwner = g_win; bi.lpszTitle = L"Choose the OverField game folder to play on Rozefield (the one with launcher.exe)";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    LPITEMIDLIST id = SHBrowseForFolderW(&bi);
    if (id) { wchar_t p[MAX_PATH]; if (SHGetPathFromIDListW(id, p)) WideCharToMultiByte(CP_ACP, 0, p, -1, g_pgame, MAX_PATH, NULL, NULL); CoTaskMemFree(id); }
    if (g_pgame[0] && !has_launcher(g_pgame)) pmsg(RGB(220, 60, 70), L"launcher.exe isn't in that folder."); else g_pmsg[0] = 0;
}
static void set_tab(int t) {
    g_tab = t; ShowWindow(g_psrv, t ? SW_SHOW : SW_HIDE);
    if (t && !g_pgame[0]) { snprintf(g_pgame, sizeof g_pgame, "%s", g_game); }
    if (t) { snprintf(g_found[0], MAX_PATH, "%s", g_game); find_launcher_install(g_found[1]); }
}

static void paint_patch(HDC dc) {
    RECT card = {104, 132, WW - 36, WH - 36}; fill_round(dc, card, C_CARD, 22); outline_round(dc, card, C_LINE, 22);
    RECT h1 = {124, 150, 700, 176}; txt(dc, f_h, C_TXT, h1, L"Play on Rozefield", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    RECT h2 = {340, 150, WW - 60, 176}; txt(dc, f_small, C_MUTE, h2, L"Use your own game on a Rozefield server after the shutdown, or as a copy now.", DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
    /* game folder */
    RECT gf = {124, 186, WW - 260, 218}; fill_round(dc, gf, C_TILE, 10);
    wchar_t wg[MAX_PATH + 40]; if (g_pgame[0]) { wchar_t t[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_pgame, -1, t, MAX_PATH); swprintf(wg, MAX_PATH + 40, L"%ls%ls", t, is_patched(g_pgame) ? L"   (plays on Rozefield)" : L""); } else wcscpy(wg, L"No game folder yet - press Change");
    RECT gt = {gf.left + 10, gf.top, gf.right - 8, gf.bottom}; txt(dc, f_body, g_pgame[0] ? C_TXT : C_MUTE, gt, wg, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_PATH_ELLIPSIS);
    pill(dc, r_pchange, 0, g_hover == B_PCHANGE, !g_pbusy, L"Change\x2026");
    const wchar_t *fl[] = {L"Steam", L"OverField launcher"};
    for (int i = 0; i < 2; i++) { int ok = g_found[i][0] != 0; wchar_t lb[80]; swprintf(lb, 80, L"%ls%ls", fl[i], ok ? L"" : L" (not found)");
        pill(dc, r_pfound[i], 0, g_hover == B_PFOUND0 + i, ok && !g_pbusy, lb); }
    /* how */
    RECT hw = {124, 270, 600, 292}; txt(dc, f_small, C_MUTE, hw, L"How", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    RECT rr[2] = {r_pcopy, r_pinplace}; const wchar_t *ht[] = {L"Make a Rozefield copy first  \x00B7  your official game stays as it is (needs free space)", L"Change this game  \x00B7  after 8 Feb 2027, or if you don't need official any more"};
    for (int i = 0; i < 2; i++) { fill_round(dc, rr[i], g_pmode == i ? RGB(232, 248, 250) : C_CARD, 10); outline_round(dc, rr[i], g_pmode == i ? C_ACC : C_LINE, 10);
        circle(dc, rr[i].left + 18, (rr[i].top + rr[i].bottom) / 2, 7, g_pmode == i ? C_ACC : C_LINE); if (g_pmode != i) circle(dc, rr[i].left + 18, (rr[i].top + rr[i].bottom) / 2, 5, C_CARD);
        RECT t = {rr[i].left + 34, rr[i].top, rr[i].right - 8, rr[i].bottom}; txt(dc, f_small, C_TXT, t, ht[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS); }
    RECT sv = {124, 398, 600, 420}; txt(dc, f_small, C_MUTE, sv, L"Default server (ask the server owner)", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    /* what it changes */
    RECT wc2 = {124, 474, WW - 60, 544}; fill_round(dc, wc2, C_TILE, 12);
    const wchar_t *wl[] = {L"Login window: the Rozefield login (official one kept as .orig)", L"The game points at the server: Config.txt and the address lookup (originals kept)", L"The Rozefield update downloads from the server the first time you start"};
    for (int i = 0; i < 3; i++) { RECT t = {wc2.left + 34, wc2.top + 6 + i * 21, wc2.right - 10, wc2.top + 27 + i * 21}; circle(dc, wc2.left + 18, t.top + 10, 6, C_OK); tick(dc, wc2.left + 18, t.top + 10, RGB(255, 255, 255));
        txt(dc, f_small, C_TXT, t, wl[i], DT_LEFT | DT_VCENTER | DT_SINGLELINE); }
    wchar_t gl[60]; if (g_pbusy && g_ptotal) swprintf(gl, 60, L"Copying %d%%", (int)(g_pdone * 100 / g_ptotal)); else wcscpy(gl, g_pbusy ? L"Working\x2026" : g_pmode == 0 ? L"Make Rozefield copy" : L"Change this game");
    pill(dc, r_pgo, 1, g_hover == B_PGO, !g_pbusy, gl);
    pill(dc, r_pundo, 0, g_hover == B_PUNDO, !g_pbusy && g_pgame[0] && is_patched(g_pgame), L"Undo on this game");
    RECT ms = {124, 620, WW - 60, 680}; txt(dc, f_small, g_pmsgc, ms, g_pmsg, DT_LEFT | DT_WORDBREAK);
    RECT nt = {124, WH - 92, WW - 60, WH - 52};
    txt(dc, f_small, C_MUTE, nt, L"Steam may put the official login back when it updates or checks the game files: run this again. A Rozefield copy isn't affected. Back up your account first: after the change this game can't log in to official.", DT_LEFT | DT_WORDBREAK);
}

static void paint(HWND h) {
    PAINTSTRUCT ps; HDC wdc = BeginPaint(h, &ps);
    HDC dc = CreateCompatibleDC(wdc); HBITMAP bb = CreateCompatibleBitmap(wdc, WW, WH); HGDIOBJ ob = SelectObject(dc, bb);
    DWORD now = GetTickCount();
    /* background: your picture (cover), else a quiet ink field with one large accent disc */
    RECT all = {0, 0, WW, WH};
    HBRUSH ink = CreateSolidBrush(C_INK); FillRect(dc, &all, ink); DeleteObject(ink);
    if (g_bg) {
        HDC m = CreateCompatibleDC(dc); HGDIOBJ o = SelectObject(m, g_bg);
        double sc = (double)WW / g_bgw > (double)WH / g_bgh ? (double)WW / g_bgw : (double)WH / g_bgh;
        int sw = (int)(WW / sc), sh = (int)(WH / sc);
        SetStretchBltMode(dc, HALFTONE); StretchBlt(dc, 0, 0, WW, WH, m, (g_bgw - sw) / 2, (g_bgh - sh) / 2, sw, sh, SRCCOPY);
        SelectObject(m, o); DeleteDC(m);
    } else {
        HRGN rg = CreateEllipticRgn(560, -220, 1380, 600);
        SelectClipRgn(dc, rg); fill_alpha(dc, all, C_ACC, 22, 0); SelectClipRgn(dc, NULL); DeleteObject(rg);
        HRGN rg2 = CreateEllipticRgn(720, 260, 1240, 780);
        SelectClipRgn(dc, rg2); fill_alpha(dc, all, C_BLUE, 18, 0); SelectClipRgn(dc, NULL); DeleteObject(rg2);
    }
    /* left rail */
    RECT rail = {0, 0, 72, WH}; fill_alpha(dc, rail, C_CARD, 235, 0); { RECT ln = {71, 0, 72, WH}; fill_alpha(dc, ln, C_LINE, 255, 0); }
    circle(dc, 36, 40, 18, C_ACC);
    RECT rl = {18, 22, 54, 58}; txt(dc, f_h, RGB(255, 255, 255), rl, L"R", DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    /* folder + log icons */
    RECT rf = r_folder; if (g_hover == B_FOLDER) fill_alpha(dc, rf, C_ACC, 40, 12);
    { HPEN p = CreatePen(PS_SOLID, 2, C_MUTE); HGDIOBJ o = SelectObject(dc, p), b0 = SelectObject(dc, GetStockObject(NULL_BRUSH));
      int x = rf.left + 12, y = rf.top + 13; RoundRect(dc, x, y + 3, x + 21, y + 18, 4, 4); MoveToEx(dc, x, y + 3, NULL); LineTo(dc, x, y); LineTo(dc, x + 8, y); LineTo(dc, x + 10, y + 3);
      RECT rg = r_logb; int lx = rg.left + 13, ly = rg.top + 12; Rectangle(dc, lx, ly, lx + 18, ly + 21);
      for (int i = 0; i < 3; i++) { MoveToEx(dc, lx + 4, ly + 6 + i * 5, NULL); LineTo(dc, lx + 14, ly + 6 + i * 5); }
      SelectObject(dc, o); SelectObject(dc, b0); DeleteObject(p); }
    if (g_hover == B_LOG) fill_alpha(dc, r_logb, C_ACC, 40, 12);
    /* window buttons */
    if (g_hover == B_CLOSE) fill_alpha(dc, r_close, RGB(232, 72, 85), 200, 8);
    if (g_hover == B_MIN) fill_alpha(dc, r_min, C_TILE, 255, 8);
    { HPEN p = CreatePen(PS_SOLID, 2, C_TXT); HGDIOBJ o = SelectObject(dc, p);
      int cx = (r_close.left + r_close.right) / 2, cy = (r_close.top + r_close.bottom) / 2;
      MoveToEx(dc, cx - 6, cy - 6, NULL); LineTo(dc, cx + 7, cy + 7); MoveToEx(dc, cx + 6, cy - 6, NULL); LineTo(dc, cx - 7, cy + 7);
      cx = (r_min.left + r_min.right) / 2; MoveToEx(dc, cx - 7, cy, NULL); LineTo(dc, cx + 8, cy);
      SelectObject(dc, o); DeleteObject(p); }
    /* title (asymmetric, top-left) */
    RECT rt = {104, 34, 700, 84}; txt(dc, f_title, C_TXT, rt, L"Rozefield Backup", DT_LEFT | DT_SINGLELINE);
    RECT rs = {106, 84, 700, 108}; txt(dc, f_small, C_MUTE, rs, L"Keep your OverField account. The official servers close on 8 Feb 2027.", DT_LEFT | DT_SINGLELINE);
    { RECT t0 = r_tab0, t1 = r_tab1;
      fill_round(dc, t0, g_tab == 0 ? C_ACC : C_CARD, 18); if (g_tab) outline_round(dc, t0, C_LINE, 18);
      fill_round(dc, t1, g_tab == 1 ? C_ACC : C_CARD, 18); if (!g_tab) outline_round(dc, t1, C_LINE, 18);
      txt(dc, f_body, g_tab == 0 ? RGB(255, 255, 255) : C_TXT, t0, L"Back up", DT_CENTER | DT_VCENTER | DT_SINGLELINE);
      txt(dc, f_body, g_tab == 1 ? RGB(255, 255, 255) : C_TXT, t1, L"Play on Rozefield", DT_CENTER | DT_VCENTER | DT_SINGLELINE); }
    if (g_tab == 1) { paint_patch(dc); goto blit; }

    /* status card */
    RECT card = {104, 132, 560, 408}; fill_round(dc, card, C_CARD, 22); outline_round(dc, card, C_LINE, 22);
    const wchar_t *st; COLORREF sc;
    switch (g_mode) {
    case M_STARTING: st = L"Starting the game"; sc = C_WARN; break;
    case M_LOGIN: st = g_up_bound ? L"Reconnecting the game through this window" : (g_player[0] ? L"Logged in" : L"Waiting for you to log in"); sc = C_WARN; break;
    case M_FETCH: st = g_tour_active ? L"Visiting every map on official" : L"Collecting your account"; sc = C_OK; break;
    case M_DONE: st = L"Everything collected"; sc = C_OK; break;
    case M_WATCH: st = L"Watching your running game"; sc = C_OK; break;
    default: st = g_player[0] ? L"Ready to save" : L"Not started"; sc = C_MUTE;
    }
    int pulse = (g_mode == M_FETCH || g_mode == M_WATCH || g_mode == M_LOGIN) ? (int)(3 + 2 * sin(now / 260.0)) : 4;
    circle(dc, 132, 164, pulse, sc);
    RECT rst = {146, 152, 540, 176}; txt(dc, f_small, sc, rst, st, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    wchar_t nm[160]; if (g_player[0]) MultiByteToWideChar(CP_UTF8, 0, g_player, -1, nm, 160); else wcscpy(nm, L"No account yet");
    RECT rn = {128, 182, 540, 230}; txt(dc, f_big, C_TXT, rn, nm, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    /* percentage + animated bar */
    wchar_t pc[16]; swprintf(pc, 16, L"%d%%", (int)(g_pct_shown + 0.5));
    RECT rp = {128, 238, 400, 306}; txt(dc, f_pct, g_mode == M_IDLE && !g_player[0] ? C_MUTE : C_TXT, rp, pc, DT_LEFT | DT_SINGLELINE);
    wchar_t sub[160];
    if (g_mode == M_FETCH && g_tour_active) swprintf(sub, 160, L"%ld of %d maps saved", (long)g_tour_done_n, NTOUR_REAL);
    else if (g_mode == M_FETCH) swprintf(sub, 160, L"%ld of %d look-ups answered", (long)(g_fetch_got > NQUERY ? NQUERY : g_fetch_got), NQUERY);
    else if (g_mode == M_WATCH) { int d = 0; for (int i = 0; i < NCHECK; i++) d += CHECKS[i].done; swprintf(sub, 160, L"%d of %d parts seen", d, NCHECK); }
    else if (g_mode == M_DONE) wcscpy(sub, g_saved_once ? L"Saved. Back up again any time your account changes." : L"Press Save backup, or close the game.");
    else if (g_mode == M_LOGIN) wcscpy(sub, L"Log in with your official account");
    else wcscpy(sub, L"Press Open game to begin");
    RECT rsub = {300, 262, 540, 298}; txt(dc, f_small, C_MUTE, rsub, sub, DT_RIGHT | DT_BOTTOM | DT_SINGLELINE);
    RECT track = {128, 312, 536, 322}; fill_round(dc, track, C_TILE, 10);
    int fw = (int)((track.right - track.left) * g_pct_shown / 100.0);
    if (fw > 0) {
        RECT fill = {track.left, track.top, track.left + fw, track.bottom}; fill_round(dc, fill, g_mode == M_DONE ? C_OK : C_ACC, 10);
        if (g_mode == M_FETCH || g_mode == M_LOGIN || g_mode == M_WATCH) {   /* shimmer travels along the filled part */
            int span = fw + 90, x = track.left - 90 + (int)((now / 4) % (DWORD)span);
            HRGN clip = CreateRoundRectRgn(fill.left, fill.top, fill.right + 1, fill.bottom + 1, 10, 10);
            SelectClipRgn(dc, clip);
            for (int i = 0; i < 6; i++) { RECT sh = {x + i * 10, track.top, x + i * 10 + 10, track.bottom}; fill_alpha(dc, sh, RGB(255, 255, 255), (BYTE)(18 + 14 * (i < 3 ? i : 5 - i)), 0); }
            SelectClipRgn(dc, NULL); DeleteObject(clip);
        }
    }
    RECT rnote = {128, 340, 540, 396};
    txt(dc, f_small, C_MUTE, rnote, L"Look-ups are read-only. The map tour moves your character through each map on official and back home; nothing else in your account changes. Your login token and device details are not saved.", DT_LEFT | DT_WORDBREAK);

    load_images();
    /* checklist (right): the in-game phone menu - icon tiles, ticked when saved */
    RECT cl = {WW - 392, 84, WW - 36, 520}; fill_round(dc, cl, C_CARD, 22); outline_round(dc, cl, C_LINE, 22);
    int done = 0; for (int i = 0; i < NCHECK; i++) done += CHECKS[i].done;
    RECT rch = {cl.left + 20, cl.top + 14, cl.right - 20, cl.top + 40}; txt(dc, f_h, RGB(40, 42, 54), rch, L"Checklist", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    wchar_t cnt[40]; swprintf(cnt, 40, L"%d of %d saved", done, NCHECK); txt(dc, f_small, RGB(110, 112, 126), rch, cnt, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
    for (int i = 0; i < NCHECK; i++) {
        int c = i % 4, r = i / 4, tw = 77, th = 120;
        RECT t = {cl.left + 14 + c * (tw + 5), cl.top + 50 + r * (th + 6), cl.left + 14 + c * (tw + 5) + tw, cl.top + 50 + r * (th + 6) + th};
        DWORD age = CHECKS[i].done ? now - g_flash[i] : 99999;
        fill_round(dc, t, CHECKS[i].done && age < 700 ? RGB(214, 244, 236) : C_TILE, 14);
        int cx = (t.left + t.right) / 2, cy = t.top + 40;
        RECT ic = {cx - 30, cy - 30, cx + 30, cy + 30};
        if (g_icon[i]) {
            if (!strncmp(CHECKS[i].icon, "g_", 2)) { circle(dc, cx, cy, 29, CHECKS[i].tint); RECT gi = {cx - 16, cy - 16, cx + 16, cy + 16}; img_fit(dc, g_icon[i], gi); }   /* white glyph on colour */
            else img_fit(dc, g_icon[i], ic);
        } else circle(dc, cx, cy, 29, CHECKS[i].tint);
        if (!CHECKS[i].done) fill_alpha(dc, ic, C_TILE, 120, 60);   /* not saved yet: faded */
        wchar_t lb[80]; MultiByteToWideChar(CP_UTF8, 0, CHECKS[i].label, -1, lb, 80);
        RECT rl = {t.left + 2, t.top + 76, t.right - 2, t.top + 96}; txt(dc, f_small, RGB(40, 42, 54), rl, lb, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
        const wchar_t *tag; COLORREF tc = RGB(130, 132, 146);
        if (CHECKS[i].done) { tag = L"saved"; tc = RGB(40, 160, 80); }
        else if (g_mode == M_FETCH) { tag = CHECKS[i].msg_id == MSG_FIELDS ? L"map tour" : L"collecting"; tc = RGB(220, 140, 20); }
        else if (g_mode == M_WATCH) { tag = L"open in game"; tc = RGB(220, 140, 20); }
        else tag = L"after login";
        RECT rtg = {t.left + 2, t.top + 96, t.right - 2, t.top + 114}; txt(dc, f_small, tc, rtg, tag, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        if (CHECKS[i].done) { int r2 = age < 220 ? 4 + (int)(age / 40) : 10; circle(dc, t.right - 14, t.top + 14, r2, C_OK); if (age >= 160) tick(dc, t.right - 14, t.top + 14, RGB(255, 255, 255)); }
    }

    /* world maps (map tour): World Selection pictures */
    RECT mc = {104, 532, WW - 36, WH - 122}; fill_round(dc, mc, C_CARD, 18); outline_round(dc, mc, C_LINE, 18);
    RECT mh = {124, 538, WW - 56, 560}; txt(dc, f_small, C_TXT, mh, L"World maps", DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    wchar_t mcnt[60]; swprintf(mcnt, 60, L"%ld of %d saved", (long)g_tour_done_n, NTOUR_REAL); txt(dc, f_small, C_MUTE, mh, mcnt, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
    int cw = (mc.right - mc.left - 20 - (NTOUR - 1) * 6) / NTOUR;
    for (int i = 0; i < NTOUR; i++) {
        RECT card = {mc.left + 10 + i * (cw + 6), 564, mc.left + 10 + i * (cw + 6) + cw, mc.bottom - 26};
        LONG stt = TOUR_UNRELEASED[i] ? 4 : g_tour_state[i];
        HRGN clip = CreateRoundRectRgn(card.left, card.top, card.right + 1, card.bottom + 1, 12, 12); SelectClipRgn(dc, clip);
        if (g_map[i]) img_draw(dc, g_map[i], card, 1); else fill_alpha(dc, card, RGB(40, 42, 54), 255, 0);
        if (stt == 4 || stt == 3) fill_alpha(dc, card, RGB(10, 10, 14), 170, 0);
        else if (stt == 0) fill_alpha(dc, card, RGB(10, 10, 14), 90, 0);
        SelectClipRgn(dc, NULL); DeleteObject(clip);
        if (stt == 1) { int a = (int)(150 + 100 * sin(now / 180.0)); outline_round(dc, card, C_ACC, 12); (void)a; RECT in2 = {card.left + 1, card.top + 1, card.right - 1, card.bottom - 1}; outline_round(dc, in2, C_ACC, 12); }
        if (stt == 2) { circle(dc, card.right - 13, card.top + 13, 10, C_OK); tick(dc, card.right - 13, card.top + 13, RGB(255, 255, 255)); }
        if (stt == 4 || stt == 3) { RECT rn2 = card; txt(dc, f_small, RGB(220, 222, 232), rn2, stt == 4 ? L"Not on\nGlobal" : L"Not open", DT_CENTER | DT_VCENTER | DT_WORDBREAK); }
        RECT rl = {card.left - 2, card.bottom + 2, card.right + 2, card.bottom + 22};
        txt(dc, f_small, stt >= 3 ? C_MUTE : C_TXT, rl, TOUR_NAME[i], DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
    }

    /* bottom bar */
    RECT bar = {72, WH - 112, WW, WH}; fill_alpha(dc, bar, C_CARD, 240, 0); { RECT ln = {72, WH - 112, WW, WH - 111}; fill_alpha(dc, ln, C_LINE, 255, 0); }
    RECT rlog = {104, WH - 92, WW - 640, WH - 64}; txt(dc, f_body, C_TXT, rlog, g_lastlog, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    wchar_t gf[MAX_PATH + 32]; wchar_t wg[MAX_PATH]; MultiByteToWideChar(CP_ACP, 0, g_game, -1, wg, MAX_PATH);
    swprintf(gf, MAX_PATH + 32, L"Game folder: %ls", g_game[0] ? wg : L"not found - use the folder button");
    RECT rgf = {104, WH - 60, WW - 640, WH - 36}; txt(dc, f_small, C_MUTE, rgf, gf, DT_LEFT | DT_SINGLELINE | DT_PATH_ELLIPSIS);
    int busy = g_mode == M_STARTING || g_mode == M_LOGIN || g_mode == M_FETCH || g_mode == M_WATCH;
    pill(dc, r_run, 0, g_hover == B_RUNNING, !busy, g_mode == M_WATCH ? L"Watching\x2026" : L"Use running game");
    pill(dc, r_save, 0, g_hover == B_SAVE, g_player[0] != 0, L"Save backup now");
    const wchar_t *ml; wchar_t mlb[40];
    switch (g_mode) {
    case M_STARTING: ml = L"Starting\x2026"; break;
    case M_LOGIN: ml = g_up_bound ? L"Reconnecting\x2026" : L"Log in to continue"; break;
    case M_FETCH: swprintf(mlb, 40, L"Collecting %d%%", (int)(g_pct_shown + 0.5)); ml = mlb; break;
    case M_DONE: ml = g_saved_once ? L"Back up again" : L"Save backup"; break;
    case M_WATCH: ml = L"Save backup"; break;
    default: ml = g_player[0] ? (g_saved_once ? L"Back up again" : L"Save backup") : (g_game_running ? L"Back up now" : L"Open game");
    }
    pill(dc, r_main, 1, g_hover == B_MAIN, !(g_mode == M_STARTING || g_mode == M_LOGIN || g_mode == M_FETCH) || (g_mode == M_WATCH), ml);

blit:
    BitBlt(wdc, 0, 0, WW, WH, dc, 0, 0, SRCCOPY);
    SelectObject(dc, ob); DeleteObject(bb); DeleteDC(dc);
    EndPaint(h, &ps);
}

/* Back up again: the account may have changed since the last backup. Ask official for everything again over the
 * live connection (no reconnect, no login), then save a new backup file next to the old ones. */
static void rebackup(void) {
    struct gconn *g = (struct gconn *)g_cur;
    if (g && !g->done) {
        for (int i = 0; i < NCHECK; i++) { CHECKS[i].done = 0; g_flash[i] = 0; }
        g_saved_once = 0; g_pct_shown = 10;
        InterlockedExchange(&g_rebackup, 1); for (int i = 0; i < NTOUR; i++) g_tour_state[i] = 0; g_tour_done_n = 0;
        ui_log("Backing up again - collecting your latest data from official...");
        CloseHandle(CreateThread(NULL, 0, fetch_rest, g, 0, NULL));
        return;
    }
    /* not connected through this window any more: reconnect the running game (or start it) */
    for (int i = 0; i < NCHECK; i++) { CHECKS[i].done = 0; g_flash[i] = 0; }
    g_saved_once = 0; g_player[0] = 0; InterlockedExchange(&g_mode, M_IDLE);
    if (find_launcher()) start_reconnect(); else start_backup();
}

static int hit(int x, int y) {
    POINT pt = {x, y};
    if (PtInRect(&r_close, pt)) return B_CLOSE;
    if (PtInRect(&r_min, pt)) return B_MIN;
    if (PtInRect(&r_tab0, pt)) return B_TAB0;
    if (PtInRect(&r_tab1, pt)) return B_TAB1;
    if (g_tab == 1) {
        if (PtInRect(&r_pchange, pt)) return B_PCHANGE;
        if (PtInRect(&r_pfound[0], pt)) return B_PFOUND0;
        if (PtInRect(&r_pfound[1], pt)) return B_PFOUND1;
        if (PtInRect(&r_pcopy, pt)) return B_PCOPY;
        if (PtInRect(&r_pinplace, pt)) return B_PINPLACE;
        if (PtInRect(&r_pgo, pt)) return B_PGO;
        if (PtInRect(&r_pundo, pt)) return B_PUNDO;
        if (PtInRect(&r_folder, pt)) return B_FOLDER;
        if (PtInRect(&r_logb, pt)) return B_LOG;
        return B_NONE;
    }
    if (PtInRect(&r_main, pt)) return B_MAIN;
    if (PtInRect(&r_run, pt)) return B_RUNNING;
    if (PtInRect(&r_save, pt)) return B_SAVE;
    if (PtInRect(&r_folder, pt)) return B_FOLDER;
    if (PtInRect(&r_logb, pt)) return B_LOG;
    return B_NONE;
}

static void on_click(int b) {
    switch (b) {
    case B_CLOSE: PostMessageW(g_win, WM_CLOSE, 0, 0); break;
    case B_MIN: ShowWindow(g_win, SW_MINIMIZE); break;
    case B_MAIN:
        if (g_mode == M_IDLE && !g_player[0]) { if (find_launcher()) start_reconnect(); else start_backup(); }
        else if ((g_mode == M_DONE || (g_mode == M_IDLE && g_player[0])) && g_saved_once) rebackup();
        else if (g_mode == M_DONE || g_mode == M_WATCH || (g_mode == M_IDLE && g_player[0])) do_save(0);
        break;
    case B_RUNNING: start_reconnect(); break;
    case B_SAVE: do_save(0); break;
    case B_FOLDER: if (g_mode == M_IDLE) browse(); break;
    case B_LOG: ShellExecuteA(NULL, "open", g_logpath, NULL, NULL, SW_SHOWNORMAL); break;
    case B_TAB0: set_tab(0); break;
    case B_TAB1: set_tab(1); break;
    case B_PCHANGE: if (!g_pbusy) patch_browse(); break;
    case B_PFOUND0: case B_PFOUND1: if (!g_pbusy && g_found[b - B_PFOUND0][0]) { snprintf(g_pgame, sizeof g_pgame, "%s", g_found[b - B_PFOUND0]); g_pmsg[0] = 0; } break;
    case B_PCOPY: if (!g_pbusy) g_pmode = 0; break;
    case B_PINPLACE: if (!g_pbusy) g_pmode = 1; break;
    case B_PGO: patch_go(); break;
    case B_PUNDO: patch_undo(); break;
    }
    InvalidateRect(g_win, NULL, FALSE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: paint(h); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLOREDIT: { static HBRUSH fb; if (!fb) fb = CreateSolidBrush(C_TILE); SetTextColor((HDC)w, C_TXT); SetBkColor((HDC)w, C_TILE); return (LRESULT)fb; }
    case WM_TIMER: {
        static int tk; if (tk++ % 33 == 0) g_game_running = find_launcher() != 0;
        double t = target_pct();
        g_pct_shown += (t - g_pct_shown) * 0.10; if (fabs(t - g_pct_shown) < 0.05) g_pct_shown = t;
        InvalidateRect(h, NULL, FALSE); return 0; }
    case WM_NCHITTEST: {
        LRESULT r = DefWindowProcW(h, m, w, l);
        if (r == HTCLIENT) {
            POINT pt = {(short)LOWORD(l), (short)HIWORD(l)}; ScreenToClient(h, &pt);
            if (pt.y < 120 && hit(pt.x, pt.y) == B_NONE && pt.x > 72) return HTCAPTION;
        }
        return r; }
    case WM_MOUSEMOVE: {
        int b = hit((short)LOWORD(l), (short)HIWORD(l));
        if (b != g_hover) { g_hover = b; TRACKMOUSEEVENT te = {sizeof te, TME_LEAVE, h, 0}; TrackMouseEvent(&te); }
        return 0; }
    case WM_MOUSELEAVE: g_hover = 0; return 0;
    case WM_SETCURSOR:
        if (LOWORD(l) == HTCLIENT && g_hover) { SetCursor(LoadCursor(NULL, IDC_HAND)); return TRUE; }
        break;
    case WM_LBUTTONUP: on_click(hit((short)LOWORD(l), (short)HIWORD(l))); return 0;
    case WM_LOG: { wchar_t *s = (wchar_t *)l; wcsncpy(g_lastlog, s, 511); g_lastlog[511] = 0; free(s); return 0; }
    case WM_CHECK: return 0;
    case WM_AUTOSAVE: do_save(1); return 0;
    case WM_GAMEEXIT:
        restore_all();
        if (g_mode != M_WATCH) InterlockedExchange(&g_mode, M_IDLE);
        ui_log("The game was closed.");
        if (g_player[0] && !g_saved_once) do_save(1);
        return 0;
    case WM_CLOSE:
        if (g_frames && g_player[0] && !g_saved_once && MessageBoxW(h, L"Save the backup before closing?", L"Rozefield Backup", MB_YESNO | MB_ICONQUESTION) == IDYES) do_save(1);
        restore_all();
        if (g_wd_redirect != INVALID_HANDLE_VALUE) { pWDClose(g_wd_redirect); g_wd_redirect = INVALID_HANDLE_VALUE; }
        if (g_tmp) { fclose(g_tmp); g_tmp = NULL; DeleteFileA(g_tmppath); }
        DestroyWindow(h); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    GetModuleFileNameA(NULL, g_exedir, MAX_PATH);
    char *sl = strrchr(g_exedir, '\\'); if (sl) sl[1] = 0;
    snprintf(g_logpath, sizeof g_logpath, "%sRozefield Backup.log", g_exedir);
    InitializeCriticalSection(&g_cs);
    WSADATA wd; WSAStartup(MAKEWORD(2, 2), &wd);
    CoInitialize(NULL);
    find_game();
    if (g_game[0]) restore_all();   /* undo an earlier run that was killed */
    load_background();

    f_title = CreateFontW(-40, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_big = CreateFontW(-34, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_pct = CreateFontW(-60, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift");
    f_h = CreateFontW(-19, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");
    f_body = CreateFontW(-15, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_small = CreateFontW(-13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    f_btn = CreateFontW(-20, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Bahnschrift SemiBold");

    WNDCLASSW wc = {0}; wc.lpfnWndProc = WndProc; wc.hInstance = hi; wc.lpszClassName = L"RozefieldBackup";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW); wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClassW(&wc);
    g_win = CreateWindowExW(WS_EX_APPWINDOW, L"RozefieldBackup", L"Rozefield Backup", WS_POPUP | WS_MINIMIZEBOX | WS_SYSMENU,
                            (GetSystemMetrics(SM_CXSCREEN) - WW) / 2, (GetSystemMetrics(SM_CYSCREEN) - WH) / 2, WW, WH, NULL, NULL, hi, NULL);
    SetWindowRgn(g_win, CreateRoundRectRgn(0, 0, WW + 1, WH + 1, 16, 16), TRUE);
    g_psrv = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_TABSTOP | ES_AUTOHSCROLL, 124, 424, 520, 34, g_win, NULL, hi, NULL);
    SendMessageW(g_psrv, WM_SETFONT, (WPARAM)f_body, TRUE); SendMessageW(g_psrv, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELONG(8, 8));
    SendMessageW(g_psrv, 0x1501 /* EM_SETCUEBANNER */, TRUE, (LPARAM)L"Invite code RZ-XXXX-XXX, or a name like myserver.duckdns.org");
    ShowWindow(g_win, show); UpdateWindow(g_win);
    SetTimer(g_win, 1, 30, NULL);
    if (strstr(cmd, "--play")) set_tab(1);
    ui_log("Rozefield Backup started. Game folder: %s", g_game[0] ? g_game : "(not found - use the folder button)");
    if (strstr(cmd, "--reconnect")) start_reconnect();
    else if (strstr(cmd, "--open")) start_backup();
    else if (strstr(cmd, "--watch")) start_watch();
    else ui_log(g_game[0] ? "Press Open game, or Use running game if OverField is already open." : "Choose your OverField folder with the folder button on the left.");
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return 0;
}
