"""Mentor's side of the recipes hub (https://mentor-recipes.netlify.app).

Reading it (the list, a recipe), and writing to it (a recipe, a report), where every write is
signed by this Mentor's own key. The protocol is in PROTOCOL.md of the hub's repository; what
the assistant does with it, and when, is in /etc/mentor/RECIPES.md.

The key is made here, on this computer, the first time something is shared, and never leaves
it. Its fingerprint is how the hub tells one Mentor from another; it names no one.

Only the one address below is ever spoken to, over https, and a redirect to anywhere else is
refused. Nothing that comes back is run: a recipe is text.
"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import mentor_recipes

HUB = "https://mentor-recipes.netlify.app"
STATE = os.environ.get("MENTOR_HUB_DIR") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mentor", "hub")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "mentor", "hub-index.json")
POW_BITS = 20
MAX_DOWNLOAD = 200000
MAX_RECIPE = 120000
INDEX_AGE = 300


class HubError(Exception):
    """Something that can be said to the user in a sentence."""


# --- the key --------------------------------------------------------------------------------------

def _openssl(*args, data=None):
    try:
        done = subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HubError("openssl is not available here: " + str(e))
    if done.returncode:
        raise HubError("openssl failed: " + done.stderr.decode(errors="replace").strip()[:200])
    return done.stdout


def key_path():
    return os.path.join(STATE, "key.pem")


def has_key():
    return os.path.isfile(key_path())


def ensure_key():
    """This Mentor's key pair, made on first use (Ed25519, private half in a file only the user reads)."""
    path = key_path()
    if not os.path.isfile(path):
        os.makedirs(STATE, mode=0o700, exist_ok=True)
        _openssl("genpkey", "-algorithm", "ED25519", "-out", path)
        os.chmod(path, 0o600)
    return path


def public_raw():
    der = _openssl("pkey", "-in", ensure_key(), "-pubout", "-outform", "DER")
    if len(der) < 32:
        raise HubError("the key could not be read")
    return der[-32:]  # the 32 bytes of an Ed25519 public key end its DER form


def key_id():
    return hashlib.sha256(public_raw()).hexdigest()[:16]


def _sign(message):
    with tempfile.TemporaryDirectory() as folder:
        source, signature = os.path.join(folder, "m"), os.path.join(folder, "s")
        with open(source, "wb") as f:
            f.write(message)
        _openssl("pkeyutl", "-sign", "-inkey", ensure_key(), "-rawin", "-in", source, "-out", signature)
        with open(signature, "rb") as f:
            return f.read()


def _work(raw_hex, ts):
    """A string that makes sha256("<key>:<ts>:<it>") begin with POW_BITS zero bits (about a second)."""
    whole, rest = divmod(POW_BITS, 8)
    n = 0
    while True:
        digest = hashlib.sha256(f"{raw_hex}:{ts}:{n}".encode()).digest()
        if digest[:whole] == b"\0" * whole and (rest == 0 or digest[whole] >> (8 - rest) == 0):
            return str(n)
        n += 1


def signing_string(kind, ts, fields):
    return "\n".join(["mentor-recipes-v1", kind, str(ts)] + list(fields))


def _signed(kind, fields, body):
    ts = int(time.time())
    raw = public_raw()
    body = dict(body)
    body.update({"v": 1, "key": base64.b64encode(raw).decode(), "ts": ts, "pow": _work(raw.hex(), ts),
                 "sig": base64.b64encode(_sign(signing_string(kind, ts, fields).encode())).decode()})
    return body


# --- talking to the hub ---------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise HubError("the hub sent us somewhere else; not following")


_opener = urllib.request.build_opener(_NoRedirect)


def _request(path, body=None, limit=MAX_DOWNLOAD):
    request = urllib.request.Request(HUB + path, headers={"User-Agent": "mentor-recipes-client/1"})
    if body is not None:
        request.data = json.dumps(body).encode()
        request.add_header("Content-Type", "application/json")
    try:
        with _opener.open(request, timeout=30) as response:
            data = response.read(limit + 1)
            status = response.status
    except urllib.error.HTTPError as e:
        data, status = e.read(limit + 1), e.code
    except (urllib.error.URLError, OSError) as e:
        raise HubError("the recipes site cannot be reached: " + str(getattr(e, "reason", e)))
    if len(data) > limit:
        raise HubError("the answer was larger than it should be")
    return status, data


def get_index(fresh=False):
    """The list: categories (with parent) and recipes (id, title, summary, category, group, sha256)."""
    if not fresh:
        try:
            if time.time() - os.path.getmtime(CACHE) < INDEX_AGE:
                with open(CACHE, encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
    status, data = _request("/index.json")
    if status != 200:
        raise HubError(f"the recipes site answered {status}")
    try:
        index = json.loads(data.decode("utf-8"))
        assert isinstance(index.get("recipes"), list) and isinstance(index.get("categories"), list)
    except (ValueError, AssertionError):
        raise HubError("the recipes site did not send a list")
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(index, f)
    except OSError:
        pass
    return index


def fetch(recipe_id):
    """(text, sha256) of a published recipe, checked against the list. Not inspected: that is the caller's."""
    if not mentor_recipes.re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", recipe_id or ""):
        raise HubError("that is not the name of a recipe")
    entry = next((r for r in get_index(True)["recipes"] if r.get("id") == recipe_id), None)
    if not entry:
        raise HubError("there is no recipe called " + recipe_id + " on the site")
    status, data = _request("/raw/" + recipe_id + ".md")
    if status != 200:
        raise HubError(f"the recipe could not be downloaded (answer {status})")
    sha = hashlib.sha256(data).hexdigest()
    if sha != str(entry.get("sha256", "")).lower():
        raise HubError("what was downloaded is not what the site lists (the checksum differs); not kept")
    return data.decode("utf-8", errors="replace"), sha


def setup_difference(entry):
    """A sentence when the recipe was written for a different GNOME or kernel than this computer's, else ''."""
    setup = (entry or {}).get("setup") or {}
    if not setup:
        return "It does not say what it was written for."
    wrote = "GNOME " + str(setup.get("gnome", "?")) + (" or later" if setup.get("or_later") else "")
    text = "Written for " + wrote + (", kernel " + str(setup["kernel"]) if setup.get("kernel") else "")
    probe = f"| Made on | {text.replace('Written for ', '')} |\n"
    notes = mentor_recipes.setup_notes(probe)
    return (text + ". " + " ".join(s for _sev, s in notes)) if notes else text + ", the same as this computer."


def on_hub(sha):
    """The listed recipe with this checksum, or None: is this file one that the site published?"""
    try:
        return next((r for r in get_index()["recipes"] if str(r.get("sha256", "")).lower() == sha), None)
    except HubError:
        return None


def _answer(status, data):
    try:
        said = json.loads(data.decode("utf-8"))
    except ValueError:
        said = {}
    if status == 202:
        return {"ok": True, "note": said.get("note", "queued")}
    reasons = {400: "the time on this computer is wrong, or the request was malformed", 401: "the signature was refused",
               409: "that exact request was already made", 413: "it is too long", 422: "it is not in the form of a recipe",
               429: "the work for the request was not accepted", 502: "the site could not queue it just now"}
    raise HubError(reasons.get(status, f"the site answered {status}") + (": " + said["error"] if said.get("error") else ""))


# --- writing ---------------------------------------------------------------------------------------------

def submit(recipe_text, category="", new_category=None):
    """Post a recipe. Signed; the hub decides what becomes of it."""
    if len(recipe_text.encode("utf-8")) > MAX_RECIPE:
        raise HubError("the recipe is too long to share")
    n = new_category if isinstance(new_category, dict) else None
    proposed = "|".join(str(n.get(k, "")) for k in ("id", "parent", "name", "description")) if n else ""
    fields = [hashlib.sha256(recipe_text.encode("utf-8")).hexdigest(), category or "", proposed]
    body = _signed("submit", fields, {"recipe": recipe_text, "category": category or "", "new_category": n})
    return _answer(*_request("/.netlify/functions/submit", body))


def rate(recipe_id, sha256, vote):
    """Say that a recipe of the site worked ("up") or did not ("down") here. One vote for each key
    and recipe: a later one replaces the earlier one."""
    vote = "up" if vote == "up" else "down"
    fields = [recipe_id, sha256.lower(), vote]
    body = _signed("rate", fields, {"id": recipe_id, "sha256": sha256.lower(), "vote": vote})
    return _answer(*_request("/.netlify/functions/rate", body))


def standing(entry):
    """How the Mentors that used a recipe of the list rated it: (up, down, short phrase or '')."""
    up, down = int((entry or {}).get("up") or 0), int((entry or {}).get("down") or 0)
    if not (up or down):
        return up, down, ""
    low = down >= 2 and down * 2 > up
    return up, down, f"{up} up, {down} down" + (": rated badly, so be careful with it" if low else "")


def report(recipe_id, sha256, kind, findings=None, rules=None):
    """Tell the hub that a recipe it published looks harmful. It looks again itself; this only says what was found."""
    kind = "rules" if kind == "rules" else "reading"
    fields = [recipe_id, sha256.lower(), kind]
    body = _signed("report", fields, {"id": recipe_id, "sha256": sha256.lower(), "kind": kind,
                                      "findings": {"high": int((findings or {}).get("high", 0)),
                                                   "medium": int((findings or {}).get("medium", 0))},
                                      "rules": [str(r)[:120] for r in (rules or [])][:8]})
    return _answer(*_request("/.netlify/functions/report", body))


# --- looking before posting -------------------------------------------------------------------------------

def tree(index):
    """[(main category, [sub-categories])] as dicts with id, name, description."""
    cats = index.get("categories", [])
    mains = [c for c in cats if not c.get("parent")]
    return [(m, [c for c in cats if c.get("parent") == m["id"]]) for m in mains]


def similar_to(recipe_text, index, most=3):
    """[(published recipe entry, score)] most like this one, best first. Candidates are chosen by
    their words, then the likeliest are downloaded and compared by what they do."""
    words = mentor_recipes.title_words(recipe_text)
    summary = next((l.lstrip("> ").strip() for l in recipe_text.splitlines() if l.startswith(">")), "")
    words |= {w for w in mentor_recipes.re.findall(r"[a-z0-9]+", summary.lower()) if w not in mentor_recipes.STOP and len(w) > 3}
    scored = []
    for r in index.get("recipes", []):
        have = {w for w in mentor_recipes.re.findall(r"[a-z0-9]+", (r.get("title", "") + " " + r.get("summary", "")).lower())}
        scored.append((len(words & have), r))
    scored.sort(key=lambda item: -item[0])
    out = []
    for hits, r in scored[:most + 2]:
        try:
            text, _sha = fetch(r["id"])
        except HubError:
            continue
        body = text
        if body.startswith("---\n") and "\n---" in body[4:]:
            body = body[body.find("\n---", 4) + 4:].lstrip("\n")
        out.append((r, mentor_recipes.similarity(recipe_text, body)))
    out.sort(key=lambda item: -item[1])
    return out[:most]
