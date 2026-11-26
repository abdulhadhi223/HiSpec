"""Resolve synthetic XML links inside each document, then audit the saved records."""

from collections import defaultdict
from lxml import etree


SIDES = ("Source", "Destination")
FIELDS = {"ObjectId", "SourceClass", "DestinationClass", "SourceId", "DestinationId"}


def index_document(root):
    objects = {}
    pools = defaultdict(list)
    links = []
    class_tags = {}
    for record in root.iter():
        fields = {}
        for child in record:
            if not isinstance(child.tag, str):
                continue
            name = etree.QName(child).localname
            if name in FIELDS:
                if name in fields:
                    raise ValueError(f"{record.tag}: multiple {name} fields")
                fields[name] = child
        if not fields:
            continue
        if "ObjectId" in fields:
            identity = fields["ObjectId"].text
            if not identity or not identity.strip() or identity in objects:
                raise ValueError(f"{record.tag}: empty or duplicate ObjectId {identity!r}")
            objects[identity] = record
        if fields.keys() - {"ObjectId"}:
            missing = FIELDS - fields.keys()
            if missing:
                raise ValueError(f"{record.tag}: incomplete link, missing {sorted(missing)}")
            links.append((record, fields))
        else:
            cls = etree.QName(record).localname
            if class_tags.setdefault(cls, record.tag) != record.tag:
                raise ValueError(f"Class {cls!r} is ambiguous across namespaces")
            pools[cls].append(identity)
    return objects, pools, links


def resolve_links(root, declarations, accepts, classes_for):
    _, pools, links = index_document(root)
    offsets = defaultdict(int)
    for record, fields in links:
        for side in SIDES:
            class_field = fields[side + "Class"]
            id_field = fields[side + "Id"]
            preferred = class_field.text
            cls_decl = declarations[class_field]
            for cls in classes_for(cls_decl, preferred):
                pool = pools.get(cls, ())
                if not pool or not accepts(cls_decl, cls):
                    continue
                key = (record.tag, side, cls)
                for _ in range(len(pool)):
                    identity = pool[offsets[key] % len(pool)]
                    offsets[key] += 1
                    if accepts(declarations[id_field], identity):
                        class_field.text = cls
                        id_field.text = identity
                        break
                else:
                    continue
                break
            else:
                raise ValueError(f"{record.tag} {fields['ObjectId'].text}: no same-document "
                                 f"object satisfies {side}Class ({preferred!r}) and {side}Id")


def audit_links(root, earlier_ids):
    objects, pools, links = index_document(root)
    duplicates = earlier_ids.intersection(objects)
    if duplicates:
        raise ValueError(f"ObjectId repeated across XML files: {min(duplicates)!r}")
    for record, fields in links:
        for side in SIDES:
            identity = fields[side + "Id"].text
            target = objects.get(identity)
            cls = fields[side + "Class"].text
            if target is None or cls not in pools or etree.QName(target).localname != cls:
                raise ValueError(f"{record.tag}: unresolved {side} reference {cls}/{identity}")
    earlier_ids.update(objects)
    return len(links) * len(SIDES)


"""Generate inert lexical values for XML Schema QA fixtures."""

from base64 import b64encode
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from uuid import UUID

from lxml import etree

_XS = "{http://www.w3.org/2001/XMLSchema}"


def _strings(index, minimum, maximum):
    if minimum > 100_000:
        raise ValueError("String length exceeds the fixture limit of 100000")
    serial = str(index)
    for text in (f"QA-{serial}", serial, "Q" + serial, str(UUID(int=index % (1 << 128))),
                 "QA", "A", ""):
        if maximum is not None and len(text) > maximum:
            text = text[-maximum:] if maximum else ""
        yield text.ljust(minimum, "A")


def _candidates(kind, index, facets):
    length = facets.get("length")
    minimum = int(length if length is not None else facets.get("minLength", 0))
    maximum = int(length) if length is not None else facets.get("maxLength")
    if maximum is not None:
        maximum = int(maximum)
    if kind == "boolean":
        return ("false", "true") if index % 2 else ("true", "false")
    if kind in {"IDREF", "IDREFS", "ENTITY", "ENTITIES", "NOTATION"}:
        return ()
    if kind in {"dateTime", "dateTimeStamp", "date", "time", "gYear", "gMonth",
                "gDay", "gYearMonth", "gMonthDay", "duration", "dayTimeDuration", "yearMonthDuration"}:
        day = date(2000, 1, 1) + timedelta(days=index % 36525)
        stamp = day.isoformat()
        time = f"00:00:{index % 60:02}Z"
        return ({"dateTime": stamp + "T" + time, "dateTimeStamp": stamp + "T" + time,
                 "date": stamp, "time": time, "gYear": f"{day.year:04d}",
                 "gMonth": f"--{day.month:02d}", "gDay": f"---{day.day:02d}",
                 "gYearMonth": stamp[:7], "gMonthDay": "--" + stamp[5:],
                 "duration": "P1D", "yearMonthDuration": "P1M", "dayTimeDuration": "P1D"}[kind],)
    if kind in {"byte", "short", "int", "long", "integer", "decimal", "float", "double",
                "positiveInteger", "negativeInteger", "nonNegativeInteger", "nonPositiveInteger",
                "unsignedByte", "unsignedShort", "unsignedInt", "unsignedLong"}:
        values = [index, index % 10, 0, 1, -1, -index]
        try:
            low = facets.get("minInclusive", facets.get("minExclusive"))
            high = facets.get("maxInclusive", facets.get("maxExclusive"))
            for bound in (low, high):
                if bound is not None:
                    edge = Decimal(str(bound))
                    values.extend([edge + index, edge - index, edge, edge + 1, edge - 1])
            if low is not None and high is not None:
                values.append((Decimal(str(low)) + Decimal(str(high))) / 2)
        except InvalidOperation:
            pass
        return (str(v) for v in values)
    if kind == "language":
        return ("en",)
    if kind == "anyURI":
        return (f"urn:qa:{index}",)
    if kind in {"hexBinary", "base64Binary"}:
        n = max(minimum, min(4, maximum if maximum is not None else 4))
        if n > 100_000:
            raise ValueError("Binary length exceeds the fixture limit of 100000")
        value = bytes([index % 256]) * n
        return (value.hex() if kind == "hexBinary" else b64encode(value).decode("ascii"),)
    return _strings(index, minimum, maximum)


def _describe(node, resolve, restrictions):
    """Unroll a restriction chain to its built-in base."""
    tag = etree.QName(node).localname
    if tag in {"element", "attribute"}:
        lexical = node.get("type")
        if lexical is None:
            inline = node.find(_XS + "simpleType")
            if inline is None:
                inline = node.find(_XS + "complexType")
            return "string" if inline is None else _describe(inline, resolve, restrictions)
    else:
        body = node.find(_XS + "restriction")
        if body is None:
            body = node.find(_XS + "simpleContent/" + _XS + "restriction")
        if body is not None:
            restrictions.append(body)
        else:
            body = node.find(_XS + "simpleContent/" + _XS + "extension")
        if body is None:
            for variety in ("list", "union"):
                compound = node.find(_XS + variety)
                if compound is not None:
                    return compound
            raise ValueError(f"Unsupported simple content at schema line {node.sourceline}")
        lexical = body.get("base")
        if lexical is None:
            inline = body.find(_XS + "simpleType")
            if inline is None:
                raise ValueError(f"Missing base type at schema line {node.sourceline}")
            return _describe(inline, resolve, restrictions)
        node = body

    prefix, _, local = lexical.rpartition(":")
    if node.nsmap.get(prefix or None) == _XS[1:-1]:
        return local
    for kind in ("simpleType", "complexType"):
        named = resolve(node, kind, lexical)
        if named is not None:
            return _describe(named, resolve, restrictions)
    raise ValueError(f"Cannot resolve value type {lexical!r} at schema line {node.sourceline}")


_FACETS = {"length", "minLength", "maxLength", "whiteSpace", "pattern", "enumeration",
           "fractionDigits", "totalDigits", "minInclusive", "minExclusive",
           "maxInclusive", "maxExclusive"}


@lru_cache(maxsize=512)
def _validator(kind, layers):
    """Use libxml2 to test lexical candidates against the XSD 1.0 facets."""
    ns = _XS[1:-1]
    schema = etree.Element(_XS + "schema", nsmap={"xs": ns})
    elem = etree.SubElement(schema, _XS + "element", name="v")
    parent = elem
    for layer in layers:
        inline = etree.Element(_XS + "simpleType")
        parent.insert(0, inline)
        body = etree.SubElement(inline, _XS + "restriction")
        parent = body
        # For derived restrictions, the nested base goes before facet children.
        for name, value in layer:
            etree.SubElement(body, _XS + name, value=value)
    attr = "base" if layers else "type"
    parent.set(attr, f"xs:{kind}")
    return etree.XMLSchema(schema)


def _member_value(member, node, index, resolve):
    if isinstance(member, str):
        prefix, _, local = member.rpartition(":")
        if node.nsmap.get(prefix or None) == _XS[1:-1]:
            validator = _validator(local, ())
            probe = etree.Element("v")
            for value in _candidates(local, index, {}):
                probe.text = value
                if validator.validate(probe):
                    return value
        else:
            named = resolve(node, "simpleType", member)
            if named is not None:
                return sample_value(named, index, 0, resolve)
        raise ValueError(f"Unsupported member type {member!r} at line {node.sourceline}")
    return sample_value(member, index, 0, resolve)


def _compound_value(node, index, resolve, facets):
    is_list = node.tag == _XS + "list"
    members = node.get("itemType" if is_list else "memberTypes", "").split()
    members.extend(node.findall(_XS + "simpleType"))
    if is_list:
        count = int(facets.get("length", facets.get("minLength", 1)))
        count = min(count, int(facets.get("maxLength", count)))
        if count > 100_000:
            raise ValueError("List length exceeds the fixture limit of 100000")
        return " ".join(_member_value(members[0], node, index + i, resolve) for i in range(count))
    for i in range(len(members)):
        try:
            return _member_value(members[(index + i) % len(members)], node, index, resolve)
        except ValueError:
            continue
    raise ValueError(f"No supported union member at line {node.sourceline}")


def _value_type(decl, resolve):
    restrictions = []
    kind = _describe(decl, resolve, restrictions)
    layers = tuple(tuple((etree.QName(child).localname, child.get("value"))
                         for child in restriction if isinstance(child.tag, str)
                         and child.tag.startswith(_XS) and etree.QName(child).localname in _FACETS)
                   for restriction in restrictions)
    return kind, layers


def accepts_value(decl, value, resolve):
    """Test a proposed scalar against the field's fixed value and XSD type."""
    if "fixed" in decl.attrib and decl.get("fixed") != value:
        return False
    kind, layers = _value_type(decl, resolve)
    if isinstance(kind, etree._Element):
        raise ValueError(f"Compound types are unsupported for identity fields at line {decl.sourceline}")
    probe = etree.Element("v")
    probe.text = value
    return _validator(kind, layers).validate(probe)


def class_values(decl, preferred, resolve):
    """Prefer the sampled class; alternatives must be explicitly enumerated."""
    if "fixed" in decl.attrib:
        return [decl.get("fixed")]
    _, layers = _value_type(decl, resolve)
    values = [value for layer in layers for facet, value in layer if facet == "enumeration"]
    return list(dict.fromkeys([preferred, *values]))


def sample_value(decl, serial, variant, resolve):
    """Produce a synthetic lexical value for an element or attribute declaration."""
    for key in ("fixed", "default"):
        if key in decl.attrib:
            return decl.attrib[key]
    kind, layers = _value_type(decl, resolve)
    index = serial + variant
    facets = {name: value for layer in reversed(layers) for name, value in layer}
    enums = [value for layer in layers for name, value in layer if name == "enumeration"]
    if isinstance(kind, etree._Element):
        # The complete generated document is subsequently schema-validated.
        return enums[index % len(enums)] if enums else _compound_value(kind, index, resolve, facets)
    validator = _validator(kind, layers)
    if enums:
        offset = index % len(enums)
        candidates = enums[offset:] + enums[:offset]
    else:
        candidates = _candidates(kind, index, facets)
    probe = etree.Element("v")
    for literal in candidates:
        probe.text = literal
        if validator.validate(probe):
            return literal
    raise ValueError(f"{decl.get('name') or decl.get('ref') or decl.tag}: no synthetic value "
                     f"for xs:{kind} meeting facets {sorted(facets)} (line {decl.sourceline})")



"""Generate and independently count structural XML fixtures from local XSD 1.0 files."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from lxml import etree

if __package__:
    from .fixture_links import audit_links, resolve_links
    from .fixture_schema import Schema, XS
    from .fixture_values import accepts_value, class_values, sample_value
else:
    from fixture_links import audit_links, resolve_links
    from fixture_schema import Schema, XS
    from fixture_values import accepts_value, class_values, sample_value


@dataclass
class Particle:
    kind: str
    minimum: int = 1
    maximum: int | None = 1
    children: list = field(default_factory=list)
    attrs: list = field(default_factory=list)
    decl: object = None
    path: tuple = ()
    text: bool = False
    entity: bool = False
    covers: set = field(default_factory=set)


def kind(node):
    return etree.QName(node).localname


def children(node):
    return [child for child in node if isinstance(child.tag, str)
            and child.tag != XS + "annotation"]


def content(schema, typ):
    """Expand complex-content extension and attribute groups."""
    result = []
    for item in children(typ):
        tag = kind(item)
        if tag in ("complexContent", "simpleContent"):
            result.extend(content(schema, item))
        elif tag == "extension":
            base = schema.resolve(item, "complexType", item.get("base"))
            if base is not None:
                result.extend(content(schema, base))
            result.extend(content(schema, item))
        elif tag == "attributeGroup":
            result.extend(content(schema, schema.declaration(item)))
        elif tag == "restriction":
            raise ValueError(f"Complex type restriction unsupported at line {item.sourceline}")
        else:
            result.append(item)
    return result


def compile_particle(schema, use, parent=(), stack=(), repeated=False):
    name = kind(use)
    maximum = use.get("maxOccurs", "1")
    p = Particle(name, int(use.get("minOccurs", "1")),
                 None if maximum == "unbounded" else int(maximum))
    if p.maximum == 0:
        return p
    many = repeated or p.maximum != 1
    decl = schema.declaration(use)
    if name == "element":
        p.decl = decl
        p.path = (*parent, schema.tag(decl))
        typ = schema.type_of(decl)
        complex_type = typ is not None and typ.tag == XS + "complexType"
        if typ is not None and typ in stack:
            raise ValueError(f"Recursive type requires an explicit fixture at {p.path}")
        if decl.get("abstract") in ("true", "1") or decl.get("substitutionGroup"):
            raise ValueError(f"Substitution groups require explicit fixtures at {p.path}")
        p.text = not complex_type or typ.find(XS + "simpleContent") is not None
        # A scalar collection may itself represent a list of records.
        p.entity = bool(parent) and (complex_type or many)
        if complex_type:
            for item in content(schema, typ):
                if kind(item) == "attribute":
                    if item.get("use") != "prohibited":
                        p.attrs.append(item)
                else:
                    p.children.append(compile_particle(schema, item, p.path, (*stack, typ)))
    elif name in ("group", "all", "sequence", "choice"):
        p.children = [compile_particle(schema, item, parent, stack, many)
                      for item in children(decl)]
        if name == "choice":
            p.children = [c for c in p.children if c.maximum != 0]
    else:
        raise ValueError(f"Unsupported xs:{name} under {parent}, line {use.sourceline}")
    p.covers = set().union(*(child.covers for child in p.children))
    if p.entity:
        p.covers.add(p.path)
    return p


class Writer:
    def __init__(self, schema, count, identity_seed):
        self.schema = schema
        self.goal = count
        self.counts = Counter()
        self.serial = 0
        self.identity_seed = identity_seed
        self.issued = set()
        self.declarations = {}

    def accepts(self, decl, value):
        return accepts_value(decl, value, self.schema.resolve)

    def classes_for(self, decl, preferred):
        return class_values(decl, preferred, self.schema.resolve)

    def object_id(self, decl):
        self.serial += 1
        serial = self.serial
        token = uuid5(NAMESPACE_URL, f"{self.identity_seed}/{serial}")
        for candidate in (f"QA-{token}", str(token), token.hex):
            if candidate not in self.issued and self.accepts(decl, candidate):
                self.issued.add(candidate)
                return candidate
        # Some schemas restrict IDs to short strings, numbers or enum values.
        for offset in range(max(2, len(self.issued) + 1)):
            candidate = sample_value(decl, serial, offset, self.schema.resolve)
            if candidate not in self.issued:
                self.issued.add(candidate)
                return candidate
        raise ValueError(f"Cannot generate a unique ObjectId at XSD line {decl.sourceline}")

    def need(self, p):
        return sum(max(0, self.goal - self.counts[path]) for path in p.covers)

    def value(self, node):
        self.serial += 1
        return sample_value(node, self.serial, 0, self.schema.resolve)

    def emit(self, p, parent):
        if p.maximum == 0:
            return
        repetitions = 0
        while p.maximum is None or repetitions < p.maximum:
            before = self.need(p)
            include_optional_value = repetitions == 0
            if repetitions >= p.minimum and not before and not include_optional_value:
                break
            if p.kind == "element":
                el = etree.SubElement(parent, p.path[-1])
                if p.entity:
                    self.counts[p.path] += 1
                for use in p.attrs:
                    decl = self.schema.declaration(use)
                    val = use.get("fixed", use.get("default"))
                    el.set(self.schema.tag(decl), val if val is not None else self.value(decl))
                if p.text:
                    local = etree.QName(el).localname
                    if local in ("SourceId", "DestinationId", "SourceClass", "DestinationClass"):
                        self.declarations[el] = p.decl
                    if local == "ObjectId":
                        el.text = self.object_id(p.decl)
                    elif local not in ("SourceId", "DestinationId"):
                        el.text = self.value(p.decl)
                for child in p.children:
                    self.emit(child, el)
            elif p.kind == "choice":
                if p.children:
                    self.emit(max(p.children, key=self.need), parent)
            else:
                for child in p.children:
                    self.emit(child, parent)
            repetitions += 1
            if repetitions >= p.minimum and self.need(p) == before:
                break


def recount(node, expected, counts, parent=()):
    path = (*parent, node.tag)
    if path in expected:
        counts[path] += 1
    for child in node:
        recount(child, expected, counts, path)


def generate(schema_path, root_name, count, out):
    schema = Schema(schema_path)
    roots = [r for r in schema.globals if root_name is None or
             root_name in (r.get("name"), schema.tag(r))]
    if len(roots) != 1:
        choices = ", ".join(r.get("name") for r in schema.globals)
        raise ValueError(f"Choose one document root using --root. Available: {choices}")
    root = compile_particle(schema, roots[0])
    if not root.covers:
        root.entity = True
        root.covers.add(root.path)
    identity_seed = sha256(schema_path.read_bytes()).hexdigest()
    writer = Writer(schema, count, identity_seed)
    audited_ids = set()
    endpoints = 0
    observed = Counter()
    docs = 0
    while min(observed[path] for path in root.covers) < count:
        remaining = writer.need(root)
        wrapper = etree.Element("fixture")
        writer.declarations.clear()
        writer.emit(root, wrapper)
        resolve_links(wrapper[0], writer.declarations, writer.accepts, writer.classes_for)
        docs += 1
        dest = out / f"{schema_path.stem}-{docs:03d}.xml"
        etree.ElementTree(wrapper[0]).write(str(dest), encoding="UTF-8",
                                            xml_declaration=True, pretty_print=True)
        saved = etree.parse(str(dest))
        schema.validator.assertValid(saved)
        endpoints += audit_links(saved.getroot(), audited_ids)
        recount(saved.getroot(), root.covers, observed)
        if writer.need(root) >= remaining:
            raise ValueError(f"No coverage progress in document {docs}")
    return {"schema": str(schema_path), "documents_validated": docs,
            "minimum_requested": count, "unique_object_ids": len(audited_ids),
            "verified_endpoints": endpoints,
            "coverage": [{"path": list(path), "entries": observed[path]}
                         for path in sorted(root.covers)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xsd", type=Path, required=True)
    parser.add_argument("--root", help="Document root name if XSD has several global elements")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    if args.count < 5:
        parser.error("--count must be at least 5")
    try:
        out = args.out.resolve()
        if out.exists():
            raise ValueError(f"Choose a new output directory; {out} already exists")
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent) as temp:
            stage = Path(temp) / "generated"
            stage.mkdir()
            report = generate(args.xsd, args.root, args.count, stage)
            (stage / "coverage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            stage.rename(out)
        print(f"{report['documents_validated']} XML document(s), "
              f"{len(report['coverage'])} covered paths. See {out / 'coverage.json'}")
    except (OSError, ValueError, etree.LxmlError) as exc:
        parser.exit(1, f"Generation failed: {exc}\n")


if __name__ == "__main__":
    main()


"""Load local XSD 1.0 documents and resolve declarations for fixture generation."""

from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname

from lxml import etree

XSD_NS = "http://www.w3.org/2001/XMLSchema"
XS = "{" + XSD_NS + "}"


def _local(uri):
    parts = urlsplit(uri)
    if parts.scheme != "file" or parts.netloc or parts.query or parts.fragment:
        raise ValueError(f"Expected a local XSD file, got {uri!r}")
    return Path(url2pathname(parts.path))


class _LocalOnly(etree.Resolver):
    def resolve(self, url, public_id, context):
        if url.startswith("file:"):
            path = _local(url)
        else:
            path = Path(url)
            if not path.is_absolute() or str(path).startswith(("//", "\\\\")):
                raise ValueError(f"Expected a local XSD file, got {url!r}")
        return self.resolve_filename(str(path), context)


class Schema:
    """Global declarations include each namespace reachable via local XSD files."""

    def __init__(self, path):
        self._ns = {}
        self._decls = {}
        self._seen = set()
        parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
        parser.resolvers.add(_LocalOnly())
        self._parser = parser
        entry = self._load(Path(path).resolve())
        self.validator = etree.XMLSchema(entry.getroottree())
        entry_ns = self._ns[entry]
        self.globals = [node for (kind, uri, _), node in self._decls.items()
                        if kind == "element" and uri == entry_ns]

    def _load(self, path, inherited=""):
        root = etree.parse(path.as_uri(), self._parser).getroot()
        if root.tag != XS + "schema" or root.getroottree().docinfo.doctype:
            raise ValueError(f"Expected an XML Schema document without a DOCTYPE in {path}")
        namespace = root.get("targetNamespace", inherited)
        identity = (path, namespace)
        if identity in self._seen:
            return root
        self._seen.add(identity)
        self._ns[root] = namespace
        for node in root:
            if not isinstance(node.tag, str):
                continue
            if node.tag in (XS + "redefine", XS + "override"):
                raise ValueError(f"Schema redefinition is unsupported in {path}")
            if node.tag in (XS + "include", XS + "import"):
                location = node.get("schemaLocation")
                if location:
                    base = node.base or path.as_uri()
                    if Path(base).is_absolute():
                        base = Path(base).as_uri() + ("/" if base.endswith("/") else "")
                    child = _local(urljoin(base, location)).resolve()
                    self._load(child, namespace if node.tag == XS + "include" else "")
            elif node.tag.startswith(XS) and node.get("name"):
                kind = etree.QName(node).localname
                self._decls[kind, namespace, node.get("name")] = node
        return root

    def _qualified(self, node, lexical):
        if ":" in lexical:
            prefix, name = lexical.split(":", 1)
            if prefix == "xml":
                return "http://www.w3.org/XML/1998/namespace", name
            return node.nsmap[prefix], name
        uri = node.nsmap.get(None, "")
        root = node.getroottree().getroot()
        if not uri and root.get("targetNamespace") is None:
            uri = self._ns[root]
        return uri, lexical

    def resolve(self, node, kind, qname):
        uri, name = self._qualified(node, qname)
        return self._decls.get((kind, uri, name))

    def declaration(self, node):
        ref = node.get("ref")
        if ref is None:
            return node
        decl = self.resolve(node, etree.QName(node).localname, ref)
        if decl is None:
            raise ValueError(f"Unresolved {etree.QName(node).localname} reference {ref!r}")
        return decl

    def tag(self, node):
        node = self.declaration(node)
        name = node.get("name")
        if not name:
            raise ValueError(f"Expected a named declaration at line {node.sourceline}")
        root = node.getroottree().getroot()
        kind = etree.QName(node).localname
        form = node.get("form", root.get(kind + "FormDefault", "unqualified"))
        uri = self._ns[root] if node.getparent() is root or form == "qualified" else ""
        return f"{{{uri}}}{name}" if uri else name

    def type_of(self, node):
        node = self.declaration(node)
        for kind in ("complexType", "simpleType"):
            typ = node.find(XS + kind)
            if typ is not None:
                return typ
        name = node.get("type")
        if name:
            for kind in ("complexType", "simpleType"):
                typ = self.resolve(node, kind, name)
                if typ is not None:
                    return typ
        return None



def discover_nomination_targets(db, cfg):
    connection = db.connection()
    inspector = inspect(connection)
    metadata = MetaData()

    table_prefix = cfg["table_prefix"]
    field_name = cfg.get("text_field", "name")
    qa_prefix = cfg["qa_prefix"]

    if not isinstance(table_prefix, str) or not table_prefix.startswith("nrd_"):
        raise ValueError("table_prefix must start with 'nrd_'")
    if not isinstance(qa_prefix, str) or not qa_prefix.strip():
        raise ValueError("qa_prefix must be a nonempty string")

    table_names = sorted(
        name for name in inspector.get_table_names(schema="public")
        if name.startswith(table_prefix)
    )

    groups = []
    counts = {}

    for name in table_names:
        table = Table(
            name,
            metadata,
            schema="public",
            autoload_with=connection,
            resolve_fks=False,
        )
        columns = table.c

        # A draft EDIT needs an existing object and an editable text field.
        if "object_id" not in columns or field_name not in columns:
            continue

        field = columns[field_name]
        if not isinstance(field.type, String) or isinstance(field.type, Enum):
            continue

        query = (
            select(columns.object_id, field)
            .where(field.startswith(qa_prefix, autoescape=True))
            .order_by(columns.object_id)
        )

        if "to_be_removed" in columns:
            removed = func.lower(columns.to_be_removed.cast(String))
            query = query.where(func.coalesce(removed, "false") == "false")

        if "deleted_at" in columns:
            query = query.where(columns.deleted_at.is_(None))

        targets = []
        seen_ids = set()

        for object_id, current_text in db.execute(query):
            if not isinstance(object_id, str) or not object_id.strip():
                continue
            if object_id in seen_ids:
                raise ValueError(
                    f"{name}: multiple active QA rows have object_id {object_id!r}"
                )
            seen_ids.add(object_id)
            targets.append({
                "entity_type": name,
                "entity_id": object_id,
                "field_name": field_name,
                "current_text": current_text,
            })

        counts[name] = len(targets)
        if targets:
            groups.append(targets)

    # Take one target per table per round so the first table cannot
    # consume the entire proposal count when other tables have matches.
    ordered_targets = [
        target
        for group in zip_longest(*groups)
        for target in group
        if target is not None
    ]

    return {
        "qa_edit_targets": ordered_targets,
        "matching_targets_by_table": counts,
    }
