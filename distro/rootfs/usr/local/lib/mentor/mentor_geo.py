"""Where an internet address is: its city and country, for the cards and lists of programs going online
(SECURITY.md, "Programs going online"; the user's wish, 2026-10-23).

Looked up on this computer, in DB-IP's free "IP to City Lite" database (db-ip.com, CC BY 4.0: Mentor Settings,
Security, names it), so no address is ever sent anywhere to be looked up. `update()` brings the newest one, once a
month (mentor-geo.service, run daily by its timer, does nothing while this month's is there):
https://download.db-ip.com/free/dbip-city-lite-YYYY-MM.mmdb.gz, about 60 MB, unpacked into DATABASE. A month's file
comes out in the first days of it: until then last month's is fetched. One that does not open, or does not know a
well-known address, is not put in place; the old one stays.

    python3 /usr/local/lib/mentor/mentor_geo.py update     as root: fetch this month's database if it is not there
    python3 /usr/local/lib/mentor/mentor_geo.py 1.1.1.1    where an address is

Big services answer from a data centre near the user, so the place is where that server is, not the company.
"""
import datetime
import gzip
import ipaddress
import json
import locale
import os
import shutil
import sys
import urllib.request

FOLDER = "/var/lib/mentor/geo"
DATABASE = os.path.join(FOLDER, "dbip-city-lite.mmdb")
STATE = os.path.join(FOLDER, "state.json")    # {"month": "2026-10", "time": when it was put in place}
URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
CHECK = "8.8.8.8"                             # an address every month's database places somewhere

_reader = {"stamp": None, "db": None}


def _open():
    """The database, opened again when it was replaced; None when it is not there (yet)."""
    try:
        stamp = os.stat(DATABASE).st_mtime
    except OSError:
        return None
    if stamp != _reader["stamp"]:
        try:
            import maxminddb
            _reader["db"], _reader["stamp"] = maxminddb.open_database(DATABASE), stamp
        except Exception:
            _reader["db"], _reader["stamp"] = None, stamp
    return _reader["db"]


def _name(names):
    """A name in the user's language when the database has it (de, en, es, fr, ja, pt-BR, ru, zh-CN), else English."""
    if not isinstance(names, dict):
        return ""
    language = (locale.getlocale()[0] or os.environ.get("LANG", "") or "en").replace("_", "-")
    for key in (language, language.split("-")[0], "en"):
        if names.get(key):
            return names[key]
    return next(iter(names.values()), "")


def place(ip):
    """'Frankfurt am Main, Germany' for an address, or '' (no database, a local address, not known)."""
    try:
        address = ipaddress.ip_address(str(ip).strip("[]"))
    except ValueError:
        return ""
    if not address.is_global:
        return ""
    db = _open()
    if db is None:
        return ""
    try:
        found = db.get(str(address)) or {}
    except Exception:
        return ""
    city = _name((found.get("city") or {}).get("names"))
    country = _name((found.get("country") or {}).get("names"))
    return ", ".join(part for part in (city, country) if part)


def lookup(host, wait=8.0):
    """An address for a name, or "": a program kept offline is mostly refused at its name lookup, so the guard never
    learns where it would have gone; Mentor looks the name up itself (the same question, asked by Mentor: no more is
    told to anyone). Never longer than `wait` seconds: more than the 5 s of a name lookup asked again (the first
    connection of a program may be refused while another is being answered). Not on a window's thread."""
    import socket
    import threading
    found = []

    def ask():
        try:
            found.append(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4][0])
        except (OSError, IndexError, UnicodeError):
            pass
    asking = threading.Thread(target=ask, daemon=True)
    asking.start()
    asking.join(wait)
    return found[0] if found else ""


def where(destination, ips, resolve=False):
    """A place a program went, as the user sees it: 'example.com · Frankfurt am Main, Germany' ("host:port" and
    the address it had, net.json's "destinations" and "ips"). The port is left out: it means nothing to them. With
    `resolve`, a name without an address is looked up (lookup: not on a window's thread)."""
    host = destination.rsplit(":", 1)[0]  # mentor-netguard always writes the port last, IPv6 addresses too
    found = place((ips or {}).get(destination) or host)  # a name lookup's address is the local DNS server's: none
    if not found and resolve and is_name(host):
        found = place(lookup(host))
    return f"{host} · {found}" if found else host


def is_name(host):
    """Whether a destination is a name (example.com), not an address."""
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        return bool(host)


def is_global(ip):
    try:
        return ipaddress.ip_address(str(ip).strip("[]")).is_global
    except ValueError:
        return False


def _months():
    today = datetime.date.today()
    last = today.replace(day=1) - datetime.timedelta(days=1)
    return [today.strftime("%Y-%m"), last.strftime("%Y-%m")]


def update():
    """Fetch this month's database when it is not in place. Returns what happened, in a line."""
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    months = _months()
    if state.get("month") == months[0] and os.path.exists(DATABASE):
        return f"up to date ({months[0]})"
    os.makedirs(FOLDER, mode=0o755, exist_ok=True)
    for month in months:
        if state.get("month") == month and os.path.exists(DATABASE):
            return f"up to date ({month}; {months[0]}'s is not out yet)"
        part = DATABASE + ".new"
        try:
            request = urllib.request.Request(URL.format(month=month), headers={"User-Agent": "Mentor"})
            with urllib.request.urlopen(request, timeout=60) as answer, gzip.open(answer) as unpacked, \
                    open(part, "wb") as out:
                shutil.copyfileobj(unpacked, out, 1 << 20)
            import maxminddb
            with maxminddb.open_database(part) as db:
                if not (db.get(CHECK) or {}).get("country"):
                    raise ValueError("it does not know where " + CHECK + " is")
        except Exception as e:
            try:
                os.remove(part)
            except FileNotFoundError:
                pass
            print(f"mentor-geo: {month}: {e}", file=sys.stderr)
            continue
        os.chmod(part, 0o644)
        os.replace(part, DATABASE)
        with open(STATE + ".new", "w") as f:
            json.dump({"month": month, "time": datetime.datetime.now().timestamp()}, f)
        os.replace(STATE + ".new", STATE)
        return f"put in place: {month}"
    return "not fetched; the one there stays" if os.path.exists(DATABASE) else "not fetched; no database yet"


if __name__ == "__main__":
    if sys.argv[1:] == ["update"]:
        print(update())
    elif len(sys.argv) == 2:
        print(place(sys.argv[1]) or "not known")
    else:
        print(__doc__)
        sys.exit(2)
