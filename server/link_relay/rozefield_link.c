/* Rozefield link: winhttp.dll in the game folder.
 *
 * The game (UnityPlayer.dll) loads winhttp.dll from its own folder first, so this file starts with the game and
 * stops with it. It passes every WinHTTP call to Windows' real winhttp.dll, and it runs a small relay on this PC:
 *
 *   127.0.0.1:18881  the game's dispatch / resources / login window HTTP  -> chosen server's link port
 *   127.0.0.1:11001  the game connection (gate)                            -> chosen server's link port ("RZL1 gate")
 *   127.0.0.1:80     the game's address lookup (HTTPDNS)                   -> chosen server's link port
 *
 * The chosen server is [link] target=host:port in launcher_Data\Plugins\Win\PCSDK_release\rozefield_sdk.ini (the
 * login window writes it). The game's own settings always point at 127.0.0.1, so the game never needs a restart to
 * change servers, and any server works: home network, router, or a playit.gg tunnel (one port).
 *
 * When the chosen server can't be reached (or none is chosen yet), the relay answers the game's start-up questions
 * itself (with the last answers it saw, else built-in ones), so the game always reaches its login window, where the
 * player picks a server. If a Rozefield server runs on this same PC, its ports are already taken and the game talks
 * to it directly; the relay then stays out of the way.
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 -shared -s rozefield_link.c winhttp_exports.S winhttp.def -o winhttp.dll -lws2_32
 */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

/* ---------------------------------------------------------------- pass-through to the real winhttp.dll */
#include "winhttp_names.h"   /* WH_NAMES[], WH_COUNT */
void *wh_fp[WH_COUNT];       /* used by the jump stubs in winhttp_exports.S */
static HMODULE g_real;

static void load_real(void) {
    char p[MAX_PATH]; UINT n = GetSystemDirectoryA(p, MAX_PATH); if (!n || n > MAX_PATH - 20) return;
    strcat(p, "\\winhttp.dll"); g_real = LoadLibraryA(p); if (!g_real) return;
    for (int i = 0; i < WH_COUNT; i++) wh_fp[i] = (void *)GetProcAddress(g_real, WH_NAMES[i]);
}

/* ---------------------------------------------------------------- settings and log */
static char g_game[MAX_PATH], g_ini[MAX_PATH], g_cache[MAX_PATH], g_logp[MAX_PATH];
static CRITICAL_SECTION g_lk;
static void lg(const char *fmt, ...) {
    EnterCriticalSection(&g_lk);
    FILE *f = fopen(g_logp, "a");
    if (f) { SYSTEMTIME t; GetLocalTime(&t); fprintf(f, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
             va_list a; va_start(a, fmt); vfprintf(f, fmt, a); va_end(a); fputc('\n', f); fclose(f); }
    LeaveCriticalSection(&g_lk);
}
static void target(char *host, int hn, int *port) {   /* [link] target = host[:port] */
    char t[300]; GetPrivateProfileStringA("link", "target", "", t, sizeof t, g_ini);
    char *s = t; while (*s == ' ') s++;
    if (!strncmp(s, "http://", 7)) s += 7;
    char *c = strrchr(s, ':'); *port = 18880;
    if (c) { *c = 0; int p = atoi(c + 1); if (p > 0 && p < 65536) *port = p; }
    char *e = s + strlen(s); while (e > s && (e[-1] == ' ' || e[-1] == '/')) *--e = 0;
    snprintf(host, hn, "%s", s);
}
static SOCKET dial(const char *host, int port, int ms) {
    char ps[16]; snprintf(ps, sizeof ps, "%d", port);
    struct addrinfo h = {0}, *r = NULL; h.ai_family = AF_INET; h.ai_socktype = SOCK_STREAM;
    if (!host[0] || getaddrinfo(host, ps, &h, &r) != 0 || !r) return INVALID_SOCKET;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    u_long nb = 1; ioctlsocket(s, FIONBIO, &nb);
    connect(s, r->ai_addr, (int)r->ai_addrlen); freeaddrinfo(r);
    fd_set w, e; FD_ZERO(&w); FD_ZERO(&e); FD_SET(s, &w); FD_SET(s, &e);
    struct timeval tv = {ms / 1000, (ms % 1000) * 1000};
    if (select(0, NULL, &w, &e, &tv) != 1 || FD_ISSET(s, &e)) { closesocket(s); return INVALID_SOCKET; }
    nb = 0; ioctlsocket(s, FIONBIO, &nb);
    return s;
}
/* reach the chosen server: its link port, else (an older server, or one on the home network) the plain ports */
static volatile DWORD g_failed_at; static char g_failed_for[300];   /* don't keep the game waiting on a server that just didn't answer */
static SOCKET up(int gate) {
    char host[256], key[300]; int port; target(host, sizeof host, &port);
    if (!host[0]) return INVALID_SOCKET;
    snprintf(key, sizeof key, "%s:%d", host, port);
    EnterCriticalSection(&g_lk);
    int recent = g_failed_at && GetTickCount() - g_failed_at < 15000 && !strcmp(key, g_failed_for);
    LeaveCriticalSection(&g_lk);
    if (recent && !gate) return INVALID_SOCKET;
    SOCKET s = dial(host, port, 4000);
    if (s != INVALID_SOCKET) {
        const char *m = gate ? "RZL1 gate\n" : "RZL1 http\n"; send(s, m, (int)strlen(m), 0); return s;
    }
    if (port == 18880) s = dial(host, gate ? 11001 : 18881, 2500);
    if (s == INVALID_SOCKET) { EnterCriticalSection(&g_lk); g_failed_at = GetTickCount(); snprintf(g_failed_for, sizeof g_failed_for, "%s", key); LeaveCriticalSection(&g_lk);
                               lg("can't reach %s", key); }
    return s;
}

/* ---------------------------------------------------------------- piping */
static void pipe2(SOCKET a, SOCKET b) {
    char buf[65536];
    for (;;) {
        fd_set r; FD_ZERO(&r); FD_SET(a, &r); FD_SET(b, &r);
        if (select(0, &r, NULL, NULL, NULL) <= 0) break;
        SOCKET from = FD_ISSET(a, &r) ? a : b, to = from == a ? b : a;
        int n = recv(from, buf, sizeof buf, 0); if (n <= 0) break;
        for (int off = 0; off < n;) { int w = send(to, buf + off, n - off, 0); if (w <= 0) goto done; off += w; }
    }
done:
    shutdown(a, SD_BOTH); shutdown(b, SD_BOTH);
}
static void send_all(SOCKET s, const char *d, int n) { for (int off = 0; off < n;) { int w = send(s, d + off, n - off, 0); if (w <= 0) return; off += w; } }

/* ---------------------------------------------------------------- start-up answers when no server answers */
static void cache_file(const char *name, char *out, int n) {
    snprintf(out, n, "%s%s.json", g_cache, name);
}
static char *read_file(const char *p) {
    FILE *f = fopen(p, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = (char *)malloc(n + 1); size_t g = fread(b, 1, n, f); fclose(f); b[g] = 0; return b;
}
static void reply(SOCKET c, int code, const char *body) {
    char h[256]; int bl = (int)strlen(body);
    int hl = snprintf(h, sizeof h, "HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
                      code, code == 200 ? "OK" : "Not Found", bl);
    send_all(c, h, hl); send_all(c, body, bl);
}
static const char *DEF_VER = "2026-10-24-12-00-58_2026-11-23-15-53-19";
static void offline_answer(SOCKET c, const char *path) {
    char p[MAX_PATH], body[2048];
    const char *name = strstr(path, "/resolve") ? "resolve" : strstr(path, "client_hot_update") ? "client_hot_update" :
                       strstr(path, "region_info") ? "region_info" : NULL;
    if (name && strcmp(name, "resolve")) {
        cache_file(name, p, sizeof p); char *b = read_file(p);
        if (b) { reply(c, 200, b); free(b); return; }
    }
    if (name && !strcmp(name, "resolve")) {
        snprintf(body, sizeof body, "{\"host\":\"\",\"ttl\":600,\"ips\":[\"127.0.0.1\"],\"cip\":\"127.0.0.1\",\"cl\":[3]}");
    } else if (name && !strcmp(name, "client_hot_update")) {
        snprintf(body, sizeof body,
                 "{\"status\":true,\"message\":\"success\",\"hotOssUrl\":\"http://127.0.0.1:18881/Resources\",\"currentVersion\":\"%s\","
                 "\"server\":\"rozefield_local\",\"ssAppId\":\"\",\"ssServerUrl\":\"http://127.0.0.1:18881/ta\",\"open_gm\":false,"
                 "\"open_error_log\":false,\"open_netConnecting_log\":false,\"ipAddress\":\"127.0.0.1\",\"payUrl\":\"http://127.0.0.1:18881/pay\","
                 "\"isTestServer\":false,\"error_log_level\":2,\"server_id\":\"31000\",\"open_cs\":false,\"serverTime\":0}", DEF_VER);
    } else if (name) {
        snprintf(body, sizeof body,
                 "{\"status\":true,\"message\":\"success\",\"gate_tcp_ip\":\"127.0.0.1\",\"gate_tcp_port\":11001,\"is_server_open\":true,"
                 "\"text\":\"\",\"client_log_tcp_ip\":\"127.0.0.1\",\"client_log_tcp_port\":21001,\"currentVersion\":\"%s\","
                 "\"photo_share_cdn_url\":\"http://127.0.0.1:18881/photo\"}", DEF_VER);
    } else if (strstr(path, "get_login_url_list")) {
        body[0] = 0;
    } else if (strstr(path, "/dispatch/")) {
        snprintf(body, sizeof body, "{\"status\":true,\"message\":\"success\",\"data\":[]}");
    } else { reply(c, 404, "{}"); return; }
    reply(c, 200, body);
}
/* remember the server's start-up answers, for the next time no server answers */
static void keep_answer(const char *path, const char *resp, int n) {
    const char *name = strstr(path, "client_hot_update") ? "client_hot_update" : strstr(path, "region_info") ? "region_info" : NULL;
    if (!name) return;
    const char *b = strstr(resp, "\r\n\r\n"); if (!b || strncmp(resp + 9, "200", 3)) return; b += 4;
    if (*b != '{') return;
    char p[MAX_PATH]; cache_file(name, p, sizeof p);
    CreateDirectoryA(g_cache, NULL);
    FILE *f = fopen(p, "wb"); if (f) { fwrite(b, 1, n - (b - resp), f); fclose(f); }
}

/* ---------------------------------------------------------------- one connection */
struct conn { SOCKET c; int kind; };   /* kind 0 = http, 1 = gate */
static DWORD WINAPI serve(LPVOID a) {
    struct conn cn = *(struct conn *)a; free(a);
    SOCKET c = cn.c;
    if (cn.kind == 1) {
        SOCKET u = up(1);
        if (u == INVALID_SOCKET) { lg("game connection: no server answers (pick one in the login window)"); closesocket(c); return 0; }
        pipe2(c, u); closesocket(u); closesocket(c); return 0;
    }
    /* HTTP: read the request head to see what it is */
    char head[16384]; int hl = 0;
    DWORD to = 15000; setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    while (hl < (int)sizeof head - 1) {
        int n = recv(c, head + hl, sizeof head - 1 - hl, 0); if (n <= 0) break; hl += n; head[hl] = 0;
        if (strstr(head, "\r\n\r\n")) break;
    }
    if (hl <= 0) { closesocket(c); return 0; }
    head[hl] = 0;
    char path[1024] = ""; sscanf(head, "%*s %1023s", path);
    int startup = strstr(path, "/dispatch/") || strstr(path, "/resolve");
    to = 0; setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, (char *)&to, sizeof to);
    SOCKET u = up(0);
    if (u == INVALID_SOCKET) {
        if (startup) { offline_answer(c, path); lg("no server answers: answered %s here", path); }
        closesocket(c); return 0;
    }
    send_all(u, head, hl);
    if (startup) {   /* small answers: read it whole, remember it, pass it on */
        size_t cap = 65536, n = 0; char *b = (char *)malloc(cap + 1); int r;
        DWORD t2 = 15000; setsockopt(u, SOL_SOCKET, SO_RCVTIMEO, (char *)&t2, sizeof t2);
        while ((r = recv(u, b + n, (int)(cap - n), 0)) > 0) { n += r; if (n == cap) { cap *= 2; b = (char *)realloc(b, cap + 1); } }
        b[n] = 0;
        if (n) { keep_answer(path, b, (int)n); send_all(c, b, (int)n); } else offline_answer(c, path);
        free(b); closesocket(u); closesocket(c); return 0;
    }
    pipe2(c, u); closesocket(u); closesocket(c); return 0;
}

/* ---------------------------------------------------------------- listeners */
struct lis { int port, kind; };
static DWORD WINAPI listen_on(LPVOID a) {
    struct lis L = *(struct lis *)a; free(a);
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in sa = {0}; sa.sin_family = AF_INET; sa.sin_port = htons((u_short)L.port); sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s, (struct sockaddr *)&sa, sizeof sa) || listen(s, 64)) {
        lg("port %d is taken (a Rozefield server on this PC?): the game uses it directly", L.port); closesocket(s); return 0;
    }
    for (;;) {
        SOCKET c = accept(s, NULL, NULL); if (c == INVALID_SOCKET) break;
        struct conn *cn = (struct conn *)malloc(sizeof *cn); cn->c = c; cn->kind = L.kind;
        HANDLE t = CreateThread(NULL, 0, serve, cn, 0, NULL); if (t) CloseHandle(t); else { closesocket(c); free(cn); }
    }
    return 0;
}
static DWORD WINAPI relay_main(LPVOID a) {
    WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
    char host[256]; int port; target(host, sizeof host, &port);
    lg("Rozefield link started; server: %s:%d", host[0] ? host : "(none yet)", port);
    int ports[][2] = {{18881, 0}, {11001, 1}, {80, 0}};
    for (int i = 0; i < 3; i++) {
        struct lis *L = (struct lis *)malloc(sizeof *L); L->port = ports[i][0]; L->kind = ports[i][1];
        HANDLE t = CreateThread(NULL, 0, listen_on, L, 0, NULL); if (t) CloseHandle(t);
    }
    return 0;
}

/* ---------------------------------------------------------------- entry */
BOOL WINAPI DllMain(HINSTANCE h, DWORD why, LPVOID r) {
    if (why != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(h);
    load_real();
    /* only inside the game itself (launcher.exe), never in other programs that happen to start from this folder */
    char exe[MAX_PATH]; GetModuleFileNameA(NULL, exe, MAX_PATH);
    const char *base = strrchr(exe, '\\'); base = base ? base + 1 : exe;
    if (_stricmp(base, "launcher.exe")) return TRUE;
    GetModuleFileNameA(h, g_game, MAX_PATH); char *sl = strrchr(g_game, '\\'); if (sl) sl[1] = 0;
    snprintf(g_ini, sizeof g_ini, "%slauncher_Data\\Plugins\\Win\\PCSDK_release\\rozefield_sdk.ini", g_game);
    snprintf(g_cache, sizeof g_cache, "%slauncher_Data\\Plugins\\Win\\PCSDK_release\\rozefield_link\\", g_game);
    snprintf(g_logp, sizeof g_logp, "%slauncher_Data\\Plugins\\Win\\PCSDK_release\\rozefield_link.log", g_game);
    InitializeCriticalSection(&g_lk);
    HANDLE t = CreateThread(NULL, 0, relay_main, NULL, 0, NULL); if (t) CloseHandle(t);
    return TRUE;
}
