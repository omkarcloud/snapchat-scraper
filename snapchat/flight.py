"""Reading a Next.js App Router page.

In October-November 2026 www.snapchat.com moved its profile, Spotlight and
search pages from the Pages Router to the App Router. A Pages Router page
carried all its data in one `<script id="__NEXT_DATA__">` JSON document; an
App Router page has no such script. Its data travels in React's "flight"
stream, cut into `self.__next_f.push([1, "<chunk>"])` script tags.

The stream, once the chunks are joined, is a list of rows:

    <hex id>:<payload>\\n              most rows; the payload is JSON, or a
                                      module import (`I[...]`), a hint (`HL[...]`)
    <hex id>:T<hex length>,<bytes>    a text row of exactly that many BYTES,
                                      with no newline after it (the same
                                      framing is used for binary rows)

A React element inside a row is the list `["$", type, key, props]`. The data a
page shows is the props of its client components, so "the profile" is simply
the one props object that has the keys `variant` and `publicProfile`:
find_props() looks for an object by the keys it must have, wherever it sits.
That survives the site moving components around, which it does often.

Values can point elsewhere in the stream:

    "$undefined"            nothing
    "$L1f" / "$1f"          row 1f (lazily loaded / plain)
    "$22:1:props:items:3"   a path into row 22; `props` on an element is its
                            fourth item, a number is a list index

resolve() follows these. Other `$` forms (`$D<date>`, `$S<symbol>`, `$@`)
are left as they are; no data field of the pages read here uses them.
"""
import re

import fastjson

_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
# Row tags that are followed by a hex byte length and a comma: text and typed arrays.
_FRAMED_RE = re.compile(rb"([TAOoUSsLlGgMmV])([0-9a-f]+),")
_REF_RE = re.compile(r"^\$L?([0-9a-f]+)((?::[^:]+)*)$")


def stream(html):
    """The page's flight stream as one string ('' when the page has none)."""
    return "".join(fastjson.loads('"' + chunk + '"') for chunk in _CHUNK_RE.findall(html))


def rows(text):
    """{row id: value} for the JSON and text rows of a stream. Rows that are
    neither (module imports, hints, binary) are left out."""
    out = {}
    data = text.encode("utf-8")
    at = 0
    while at < len(data):
        colon = data.find(b":", at)
        if colon < 0:
            break
        row_id = data[at:colon].decode("ascii", "replace")
        framed = _FRAMED_RE.match(data, colon + 1)
        if framed:
            start = framed.end()
            length = int(framed.group(2), 16)
            if framed.group(1) == b"T":
                out[row_id] = data[start:start + length].decode("utf-8", "replace")
            at = start + length
            continue
        end = data.find(b"\n", colon)
        if end < 0:
            end = len(data)
        payload = data[colon + 1:end]
        at = end + 1
        if payload[:1] in (b"[", b"{", b'"'):
            try:
                out[row_id] = fastjson.loads(payload)
            except ValueError:
                pass
    return out


class Page:
    """The rows of one page, with lookup by shape and reference following."""

    def __init__(self, html):
        self.rows = rows(stream(html))

    def __bool__(self):
        return bool(self.rows)

    def resolve(self, value, depth=0):
        """`value` with a reference followed to what it points at (one hop
        after another, up to a sane depth). Anything else comes back as is."""
        while isinstance(value, str) and value.startswith("$") and depth < 12:
            if value == "$undefined":
                return None
            match = _REF_RE.match(value)
            if not match or match.group(1) not in self.rows:
                return value
            target = self.rows[match.group(1)]
            for step in filter(None, match.group(2).split(":")):
                if isinstance(target, str):
                    target = self.resolve(target, depth + 1)
                if isinstance(target, list):
                    if step == "props" and target[:1] == ["$"] and len(target) > 3:
                        target = target[3]
                    elif step.isdigit() and int(step) < len(target):
                        target = target[int(step)]
                    else:
                        return None
                elif isinstance(target, dict):
                    target = target.get(step)
                else:
                    return None
            value = target
            depth += 1
        return value

    def find_props(self, *keys):
        """The first object anywhere in the page that has all of `keys`, or
        None. Rows are searched in stream order, each depth-first."""
        wanted = set(keys)
        for row in self.rows.values():
            stack = [row]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if wanted <= node.keys():
                        return node
                    stack.extend(reversed(list(node.values())))
                elif isinstance(node, list):
                    stack.extend(reversed(node))
        return None

    def element_props(self, value):
        """The props of the element `value` is or points at (`["$", type,
        key, props]`), or None."""
        value = self.resolve(value)
        if isinstance(value, list) and value[:1] == ["$"] and len(value) > 3 and isinstance(value[3], dict):
            return value[3]
        return None

    def expand(self, value, depth=0):
        """`value` with every reference inside it followed, at any depth, and
        "$undefined" turned into None. The stream shares objects: the same
        tile can sit in the "All" tab and be pointed at from the "Spotlight"
        tab, whole or field by field. Lists and objects are rebuilt; the rows
        are not changed. Past 40 levels a value is returned unexpanded."""
        if depth > 40:
            return value
        if isinstance(value, str):
            if not value.startswith("$"):
                return value
            target = self.resolve(value)
            return target if isinstance(target, str) or target is None else self.expand(target, depth + 1)
        if isinstance(value, dict):
            return {key: self.expand(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self.expand(item, depth + 1) for item in value]
        return value

    def items(self, values):
        """A list of data objects, fully expanded; entries that are not
        objects are dropped."""
        values = self.resolve(values)
        out = []
        for value in values if isinstance(values, list) else []:
            value = self.expand(value)
            if isinstance(value, dict):
                out.append(value)
        return out


def clean(value):
    """A value read from the stream with "$undefined" turned into None, at
    any depth (lists and objects are rebuilt, the input is not changed)."""
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return None if value == "$undefined" else value
