#!/usr/bin/env python3
"""Sensewright build-side DBPF / tuning extraction toolkit.

The Sims 4 ships gameplay tuning compiled into DBPF packages. Mod-side tuning
(Buff, Trait, Interaction, ...) is stored as plain XML, while the base game
stores most tuning in binary "SimData" plus a single *combined tuning* XML
resource (type 0x62E94D38) that contains every tuning definition. This toolkit
reads both the game's packages and mod packages so we can recover the exact
schema and values needed to author Sensewright tuning (e.g. Commodity Buffs).

Commands
--------
  types  <package...>                 Resource-type histogram per package.
  list   <package> [--type T] [--name S] [--limit N]
  extract <package...> --out DIR [--type T] [--xml-only]
  scan   <package...> --contains TEXT [--type T] [--max N]
  schema <xml-file> --class buff|statistic|... [--show NAME]
  find   <xml-file> --name TEXT [--class C] [--limit N]

`--type` accepts hex (0x545AC67A) or a known name (simdata, buff, statistic, ...).
Only the standard library is used.
"""
from __future__ import annotations

import argparse
import collections
import re
import struct
import sys
import zlib
from pathlib import Path

# ── DBPF constants ────────────────────────────────────────────────────────
DBPF_MAGIC = b"DBPF"
HEADER_INDEX_COUNT = 0x24
HEADER_INDEX_SIZE = 0x2C
HEADER_INDEX_OFFSET = 0x40
INDEX_ENTRY_SIZE = 32
COMPRESSION_ZLIB = 0x5A42
SIZE_COMPRESSED_FLAG = 0x80000000

# Resource type names. Tuning lives in SIMDATA / COMBINED_TUNING; the distinct
# per-kind values are what S4 Studio writes for mod tuning.
TYPE_NAMES = {
    0x545AC67A: "simdata",
    0x62E94D38: "combined_tuning",
    0x220557DA: "stbl",
    0x6017E896: "buff",
    0xCB5FDDC7: "trait",
    0x7DF2169C: "snippet",
    0xE882D22F: "interaction",
    0x03E9D964: "pie_menu_category",
    0x02D5DF13: "object_definition",
    0x0C772E27: "commodity",
    0xEE17C6AD: "statistic",
}
NAME_TYPES = {v: k for k, v in TYPE_NAMES.items()}


def parse_type(value: str) -> int:
    """Resolve a --type argument (hex or known name) to a u32."""
    if value.lower() in NAME_TYPES:
        return NAME_TYPES[value.lower()]
    return int(value, 0)


class Resource:
    __slots__ = ("type", "group", "instance", "offset", "size", "size2", "compression")

    def __init__(self, rtype, group, instance, offset, size, size2, compression):
        self.type = rtype
        self.group = group
        self.instance = instance
        self.offset = offset
        self.size = size
        self.size2 = size2
        self.compression = compression

    @property
    def compressed_size(self) -> int:
        return self.size & 0x7FFFFFFF

    @property
    def is_compressed(self) -> bool:
        return self.compression == COMPRESSION_ZLIB or bool(self.size & SIZE_COMPRESSED_FLAG)

    def __repr__(self) -> str:
        return "Resource(type=0x{:08X}, group=0x{:08X}, instance=0x{:016X}, size={})".format(
            self.type, self.group, self.instance, self.compressed_size
        )


def read_index(path: str):
    """Parse a DBPF index into a list of Resources."""
    with open(path, "rb") as handle:
        header = handle.read(96)
        if header[:4] != DBPF_MAGIC:
            raise ValueError("{} is not a DBPF package".format(path))
        count = struct.unpack_from("<I", header, HEADER_INDEX_COUNT)[0]
        index_offset = struct.unpack_from("<I", header, HEADER_INDEX_OFFSET)[0]
        handle.seek(index_offset)
        handle.read(4)  # index prefix
        resources = []
        for _ in range(count):
            entry = handle.read(INDEX_ENTRY_SIZE)
            if len(entry) < INDEX_ENTRY_SIZE:
                break
            rtype, group, hi, lo, offset, size, size2, compression, _ = struct.unpack(
                "<IIIIIIIHH", entry
            )
            resources.append(Resource(rtype, group, (hi << 32) | lo, offset, size, size2, compression))
        return resources


def read_resource(path: str, resource: Resource) -> bytes:
    """Read and decompress a resource payload."""
    with open(path, "rb") as handle:
        handle.seek(resource.offset)
        data = handle.read(resource.compressed_size)
    if resource.is_compressed:
        try:
            return zlib.decompress(data)
        except zlib.error:
            return data
    return data


def type_name(rtype: int) -> str:
    return TYPE_NAMES.get(rtype, "0x{:08X}".format(rtype))


# ── XML tuning parsing helpers ────────────────────────────────────────────
_ITEM_RE = re.compile(
    r'<I\b[^>]*\bc="([^"]+)"[^>]*\bi="([^"]+)"[^>]*\bm="([^"]+)"[^>]*\bn="([^"]+)"[^>]*\bs="([^"]*)"',
    re.DOTALL,
)
_FIELD_RE = re.compile(r'<(?P<tag>E|T|V|L|U|r|R)\b[^>]*\bn="(?P<name>[^"]+)"')
_REF_RE = re.compile(r'<[A-Za-z]+\b[^>]*\bn="([^"]+)"[^>]*\bx="(\d+)"')


def iter_items(text: str, class_filter: str = ""):
    """Yield (class, kind, module, name, instance, block_text).

    Tuning items are `<I ...>...</I>`; they do not nest, so a non-greedy scan is
    safe and far cheaper than DOM parsing a multi-megabyte combined file.
    """
    for match in _ITEM_RE.finditer(text):
        c, i, m, n, s = match.groups()
        if class_filter and i != class_filter and c.lower() != class_filter.lower():
            continue
        end = text.find("</I>", match.end())
        block = text[match.start():end + 4 if end != -1 else len(text)]
        yield c, i, m, n, s, block


def item_fields(block: str):
    """Field names present in an item block (union of all element `n=` attrs)."""
    return sorted({m.group("name") for m in _FIELD_RE.finditer(block)})


# ── combined-tuning value table + reference resolution ────────────────────
_TAG_NAME_RE = re.compile(r"<([A-Za-z0-9_]+)")
_X_ATTR_RE = re.compile(r'\bx="(\d+)"')


def iter_toplevel(text: str, start: int = 0, end: int = None):
    """Yield (start, end, element_text) for each top-level XML element."""
    if end is None:
        end = len(text)
    i = start
    while i < end:
        lt = text.find("<", i)
        if lt == -1 or lt >= end:
            break
        if text.startswith("</", lt):
            gt = text.find(">", lt)
            i = gt + 1 if gt != -1 else end
            continue
        gt = text.find(">", lt)
        if gt == -1:
            break
        tag = text[lt:gt + 1]
        if tag.rstrip().endswith("/>"):
            yield lt, gt + 1, tag
            i = gt + 1
            continue
        name_match = _TAG_NAME_RE.match(tag)
        if not name_match:
            i = gt + 1
            continue
        name = name_match.group(1)
        depth = 1
        p = gt + 1
        while p < end and depth > 0:
            nxt = text.find("<", p)
            if nxt == -1:
                p = end
                break
            if text.startswith("</", nxt):
                cgt = text.find(">", nxt)
                closed = text[nxt + 2:cgt].split()[0] if cgt != -1 else ""
                if closed == name:
                    depth -= 1
                    if depth == 0:
                        p = cgt + 1
                        break
                p = cgt + 1 if cgt != -1 else end
            else:
                ogt = text.find(">", nxt)
                inner = text[nxt:ogt + 1] if ogt != -1 else ""
                inner_match = _TAG_NAME_RE.match(inner)
                if inner_match and not inner.rstrip().endswith("/>") and inner_match.group(1) == name:
                    depth += 1
                p = ogt + 1 if ogt != -1 else end
        yield lt, p, text[lt:p]
        i = p


def parse_value_table(text: str):
    """Map the combined file's `x="N"` value-table indices to element text."""
    start = text.find('<g s="merged">')
    if start == -1:
        return {}
    gt = text.find(">", start)
    table = {}
    for s, e, element in iter_toplevel(text, gt + 1):
        match = _X_ATTR_RE.search(element[:element.find(">") + 1])
        if match:
            table[int(match.group(1))] = element
    return table


def _inner_text(element: str) -> str:
    gt = element.find(">")
    lt = element.rfind("</")
    if gt == -1 or lt == -1:
        return ""
    return element[gt + 1:lt]


_SELFCLOSE_REF_RE = re.compile(r'<([A-Za-z0-9_]+)\b([^>]*?)\bx="(\d+)"([^>]*?)/>')


def resolve_block(block: str, table, depth: int = 3, seen=None) -> str:
    """Inline `x="N"` references as readable text, preserving all attributes.

    Only self-closing reference elements are expanded; `<T x="N">literal</T>`
    becomes `<key n="key">literal</key>`, complex nodes keep their attributes
    and gain a resolved inner body. Non-references are left byte-for-byte.
    """
    seen = seen or set()
    if depth <= 0 or 'x="' not in block:
        return block

    def repl(match):
        tag, pre, idx, post = match.group(1), match.group(2), int(match.group(3)), match.group(4)
        if idx in seen:
            return match.group(0)
        target = table.get(idx)
        if target is None:
            return match.group(0)
        name = re.search(r'\bn="([^"]+)"', pre + post)
        name_attr = ' n="{}"'.format(name.group(1)) if name else ""
        inner = _inner_text(target).strip()
        if inner and "<" not in inner:
            return "<{0}{1}>{2}</{0}>".format(tag, name_attr, inner)
        resolved = resolve_block(inner, table, depth - 1, seen | {idx})
        return "<{0}{1}{2}>{3}</{0}>".format(tag, pre, post, resolved)

    return _SELFCLOSE_REF_RE.sub(repl, block)


# ── commands ──────────────────────────────────────────────────────────────
def cmd_types(args) -> int:
    for path in args.packages:
        index = read_index(path)
        hist = collections.Counter(r.type for r in index)
        print("{}: {} resources".format(path, len(index)))
        for rtype, count in hist.most_common(30):
            print("  0x{:08X} {:<18} {}".format(rtype, type_name(rtype), count))
    return 0


def cmd_list(args) -> int:
    wanted = parse_type(args.type) if args.type else None
    index = read_index(args.package)
    shown = 0
    for resource in index:
        if wanted is not None and resource.type != wanted:
            continue
        print(resource)
        shown += 1
        if args.limit and shown >= args.limit:
            break
    print("{} of {} resources".format(shown, len(index)))
    return 0


def _safe_name(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]', "_", name)


def cmd_extract(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = parse_type(args.type) if args.type else None
    total = 0
    for path in args.packages:
        for resource in read_index(path):
            if wanted is not None and resource.type != wanted:
                continue
            data = read_resource(path, resource)
            is_xml = data[:1] == b"<"
            if args.xml_only and not is_xml:
                continue
            ext = "xml" if is_xml else "bin"
            fname = "{}_{:016X}.{}".format(type_name(resource.type), resource.instance, ext)
            (out / _safe_name(fname)).write_bytes(data)
            total += 1
    print("extracted {} resources to {}".format(total, out))
    return 0


def cmd_scan(args) -> int:
    needle = args.contains.encode("utf-8")
    wanted = parse_type(args.type) if args.type else None
    matches = collections.Counter()
    found = 0
    for path in args.packages:
        for resource in read_index(path):
            if wanted is not None and resource.type != wanted:
                continue
            data = read_resource(path, resource)
            if needle not in data:
                continue
            matches[resource.type] += 1
            found += 1
            if args.max and found > args.max:
                break
    for rtype, count in matches.most_common():
        print("0x{:08X} {:<18} {}".format(rtype, type_name(rtype), count))
    print("{} resource(s) contained {!r}".format(found, args.contains))
    return 0


def cmd_schema(args) -> int:
    text = Path(args.xml).read_text(encoding="utf-8", errors="replace")
    table = parse_value_table(text)
    union = set()
    count = 0
    for c, i, m, n, s, block in iter_items(text, args.cls):
        union.update(item_fields(block))
        count += 1
        if args.show and n == args.show:
            print("=== {} (c={} s={}) ===".format(n, c, s))
            print(resolve_block(block, table))
    print("class={!r} items={} distinct fields={}".format(args.cls, count, len(union)))
    for field in sorted(union):
        print("  " + field)
    return 0


def cmd_find(args) -> int:
    text = Path(args.xml).read_text(encoding="utf-8", errors="replace")
    table = parse_value_table(text)
    shown = 0
    needle = args.name.lower() if args.name else None
    field = args.field
    for c, i, m, n, s, block in iter_items(text, args.cls):
        if needle and needle not in n.lower():
            continue
        if field and field not in item_fields(block):
            continue
        print("{:<60} c={} s={}".format(n, c, s))
        if args.resolve:
            print(resolve_block(block, table)[: args.max_chars])
        else:
            print("  fields: " + ", ".join(item_fields(block))[: args.max_chars])
        shown += 1
        if args.limit and shown >= args.limit:
            break
    print("{} match(es)".format(shown))
    return 0


def cmd_dump_class(args) -> int:
    text = Path(args.xml).read_text(encoding="utf-8", errors="replace")
    table = parse_value_table(text)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for c, i, m, n, s, block in iter_items(text, args.cls):
        if args.field and args.field not in item_fields(block):
            continue
        body = resolve_block(block, table) if args.resolve else block
        (out / (_safe_name(n) + ".xml")).write_text(body, encoding="utf-8")
        written += 1
    print("dumped {} {!r} items to {}".format(written, args.cls, out))
    return 0


def cmd_autonomy(args) -> int:
    """Export base-game autonomy commodities (the real bias levers).

    TS4 traits bias native autonomy by adding `commodity_Trait_Autonomy_*`
    commodities through a hidden buff's `autonomy_modifier.commodities_to_add`.
    This lists every such commodity with its numeric tuning id so Sensewright
    bias buffs can reference them.
    """
    text = Path(args.xml).read_text(encoding="utf-8", errors="replace")
    export = {}
    for c, i, m, n, s, block in iter_items(text, "commodity"):
        if n.startswith("commodity_Trait_Autonomy_") or n.startswith("commodity_Emotion_Autonomy_"):
            try:
                export[n] = int(s)
            except ValueError:
                continue
    if args.out:
        Path(args.out).write_text(
            __import__("json").dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("wrote {} autonomy commodities to {}".format(len(export), args.out))
    else:
        for name, tid in sorted(export.items()):
            print("{}\t{}".format(tid, name))
    return 0


def cmd_show(args) -> int:
    text = Path(args.xml).read_text(encoding="utf-8", errors="replace")
    table = parse_value_table(text)
    for c, i, m, n, s, block in iter_items(text, args.cls):
        if n == args.name:
            print("=== {} (c={} i={} s={}) ===".format(n, c, i, s))
            print(resolve_block(block, table) if not args.raw else block)
            return 0
    print("not found: {}".format(args.name))
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DBPF / tuning extraction toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("types"); p.add_argument("packages", nargs="+"); p.set_defaults(func=cmd_types)
    p = sub.add_parser("list"); p.add_argument("package"); p.add_argument("--type")
    p.add_argument("--name"); p.add_argument("--limit", type=int, default=0); p.set_defaults(func=cmd_list)
    p = sub.add_parser("extract"); p.add_argument("packages", nargs="+"); p.add_argument("--out", required=True)
    p.add_argument("--type"); p.add_argument("--xml-only", action="store_true"); p.set_defaults(func=cmd_extract)
    p = sub.add_parser("scan"); p.add_argument("packages", nargs="+"); p.add_argument("--contains", required=True)
    p.add_argument("--type"); p.add_argument("--max", type=int, default=0); p.set_defaults(func=cmd_scan)
    p = sub.add_parser("schema"); p.add_argument("xml"); p.add_argument("--class", dest="cls", required=True)
    p.add_argument("--show"); p.set_defaults(func=cmd_schema)
    p = sub.add_parser("find"); p.add_argument("xml"); p.add_argument("--name")
    p.add_argument("--class", dest="cls", default=""); p.add_argument("--field")
    p.add_argument("--resolve", action="store_true"); p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--limit", type=int, default=20); p.set_defaults(func=cmd_find)
    p = sub.add_parser("dump-class"); p.add_argument("xml"); p.add_argument("--class", dest="cls", required=True)
    p.add_argument("--field"); p.add_argument("--resolve", action="store_true")
    p.add_argument("--out", required=True); p.set_defaults(func=cmd_dump_class)
    p = sub.add_parser("show"); p.add_argument("xml"); p.add_argument("--name", required=True)
    p.add_argument("--class", dest="cls", default=""); p.add_argument("--raw", action="store_true")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("autonomy"); p.add_argument("xml"); p.add_argument("--out")
    p.set_defaults(func=cmd_autonomy)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
