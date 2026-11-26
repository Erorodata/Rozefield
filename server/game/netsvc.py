"""Network helpers for hosting: public address, opening
router ports (UPnP), and answering launchers that look for servers on the home network.

Everything runs in background threads and only reports status; a failure never stops the game server.
"""
import json
import logging
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from game import hostcfg

log = logging.getLogger('rozefield')
DISCOVERY_PORT = 18882
STATUS = {'public_ip': '', 'router': 'off', 'lan_ip': ''}


B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'


def invite_code(ip):
    """RZ-XXXX-XXX: an IPv4 address in base32, typed into the launcher's Add server."""
    try:
        v = int.from_bytes(socket.inet_aton(ip), 'big')
    except OSError:
        return ''
    c = ''.join(B32[(v >> (5 * i)) & 31] for i in range(6, -1, -1))
    return f'RZ-{c[:4]}-{c[4:]}'


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={'User-Agent': 'Rozefield-Server'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace').strip()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('192.168.0.1', 9))   # no packet is sent; picks the interface used for the LAN
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def public_ip():
    for url in ('https://api.ipify.org', 'https://ifconfig.me/ip', 'https://checkip.amazonaws.com'):
        try:
            ip = _get(url, 8)
            if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', ip):
                return ip
        except Exception:
            continue
    return ''


def servers_json(s=None):
    """Content for a server-list file (e.g. servers.json in a GitHub repo) that launchers can read."""
    s = s or hostcfg.load()
    addr = s.get('tunnel_address') or STATUS['public_ip'] or lan_ip()
    return json.dumps({'format': 'rozefield-servers/1', 'servers': [{'name': s.get('display_name', 'Rozefield'), 'address': addr}]},
                      ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- UPnP (router ports)
def _ssdp():
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
           'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n').encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(3)
    try:
        s.sendto(msg, ('239.255.255.250', 1900))
        while True:
            data, _ = s.recvfrom(4096)
            m = re.search(rb'(?im)^location:\s*(\S+)', data)
            if m:
                return m.group(1).decode()
    except OSError:
        return None
    finally:
        s.close()


def _control_url(location):
    xml = _get(location, 5)
    root = ET.fromstring(xml)
    ns = {'d': 'urn:schemas-upnp-org:device-1-0'}
    for svc in root.iter('{urn:schemas-upnp-org:device-1-0}service'):
        st = svc.findtext('d:serviceType', '', ns)
        if 'WANIPConnection' in st or 'WANPPPConnection' in st:
            ctl = svc.findtext('d:controlURL', '', ns)
            return urllib.parse.urljoin(location, ctl), st
    return None, None


def _soap(url, st, action, args):
    body = ''.join(f'<{k}>{v}</{k}>' for k, v in args)
    env = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
           f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{action} xmlns:u="{st}">{body}'
           f'</u:{action}></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(url, data=env, headers={'Content-Type': 'text/xml; charset="utf-8"',
                                                         'SOAPAction': f'"{st}#{action}"'})
    with urllib.request.urlopen(req, timeout=6) as r:
        return r.read().decode('utf-8', 'replace')


def open_ports(ports):
    """Ask the router to forward TCP <ports> to this PC. Returns a status line."""
    loc = _ssdp()
    if not loc:
        return 'router did not answer (UPnP off or not supported) - forward the ports by hand'
    try:
        url, st = _control_url(loc)
        if not url:
            return 'router has no port-forwarding service - forward the ports by hand'
        me = lan_ip()
        done = []
        for p in ports:
            _soap(url, st, 'AddPortMapping', [('NewRemoteHost', ''), ('NewExternalPort', p), ('NewProtocol', 'TCP'),
                                                ('NewInternalPort', p), ('NewInternalClient', me), ('NewEnabled', 1),
                                                ('NewPortMappingDescription', f'Rozefield {p}'), ('NewLeaseDuration', 0)])
            done.append(str(p))
        try:
            ext = re.search(r'<NewExternalIPAddress>([^<]*)<', _soap(url, st, 'GetExternalIPAddress', []))
            if ext and ext.group(1):
                STATUS['public_ip'] = ext.group(1)
        except Exception:
            pass
        return f'open (UPnP): TCP {", ".join(done)} -> {me}'
    except Exception as e:
        return f'router refused ({e.__class__.__name__}) - forward TCP {", ".join(map(str, ports))} to {lan_ip()} by hand'


# ---------------------------------------------------------------- home network discovery
def discovery_loop(info):
    """Answer 'ROZEFIELD?' broadcasts on UDP 18882 with this server's name, address and player count."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', DISCOVERY_PORT))
    except OSError as e:
        log.warning('home network discovery off (UDP %s busy: %s)', DISCOVERY_PORT, e)
        return
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.strip() != b'ROZEFIELD?' or not hostcfg.load().get('lan_discovery', True):
                continue
            s.sendto(json.dumps(info()).encode('utf-8'), addr)
        except Exception:
            time.sleep(1)


def start(ports, info):
    """Background jobs: LAN discovery, then UPnP and the server name once, the name again every 10 minutes."""
    STATUS['lan_ip'] = lan_ip()
    threading.Thread(target=discovery_loop, args=(info,), daemon=True).start()

    def loop():
        s = hostcfg.load()
        STATUS['public_ip'] = public_ip()
        if s.get('upnp', True):
            STATUS['router'] = open_ports(ports)
            log.info('router ports: %s', STATUS['router'])
    threading.Thread(target=loop, daemon=True).start()
