
XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSD = f"{{{XSD_NS}}}"

STRING_XSD_TYPES = {
    "string",
    "normalizedString",
    "token",
    "language",
    "Name",
    "NCName",
    "NMTOKEN",
    "NMTOKENS",
    "ID",
    "IDREF",
    "IDREFS",
    "ENTITY",
    "ENTITIES",
    "anyURI",
}

NON_STRING_XSD_TYPES = {
    "boolean",
    "date",
    "dateTime",
    "time",
    "duration",
    "integer",
    "int",
    "long",
    "short",
    "byte",
    "unsignedInt",
    "unsignedLong",
    "unsignedShort",
    "unsignedByte",
    "positiveInteger",
    "negativeInteger",
    "nonNegativeInteger",
    "nonPositiveInteger",
    "decimal",
    "float",
    "double",
}


def is_string_xsd_element(
    xsd_element: etree._Element | None,
) -> bool:
    """Check whether an XSD element has string-based content."""

    if xsd_element is None:
        return False

    schema_root = xsd_element.getroottree().getroot()

    def type_is_text(type_name, visited):
        if not type_name:
            return False

        name = type_name.split(":")[-1]

        if name in STRING_XSD_TYPES:
            return True

        if name in NON_STRING_XSD_TYPES:
            return False

        if name in visited:
            return False

        named_type = schema_root.find(
            f"{XSD}simpleType[@name='{name}']"
        )

        if named_type is None:
            return False

        return simple_is_text(
            named_type,
            visited | {name},
        )

    def simple_is_text(simple_type, visited):
        if simple_type is None:
            return False

        restriction = simple_type.find(
            f"{XSD}restriction"
        )

        if restriction is not None:
            return type_is_text(
                restriction.get("base"),
                visited,
            )

        union = simple_type.find(f"{XSD}union")

        if union is not None:
            results = [
                type_is_text(name, visited)
                for name in union.get(
                    "memberTypes", ""
                ).split()
            ]

            results.extend(
                simple_is_text(child, visited)
                for child in union.findall(
                    f"{XSD}simpleType"
                )
            )

            return bool(results) and all(results)

        list_type = simple_type.find(f"{XSD}list")

        if list_type is not None:
            return type_is_text(
                list_type.get("itemType"),
                visited,
            )

        return False

    ref = xsd_element.get("ref")

    if ref:
        name = ref.split(":")[-1]
        referenced = schema_root.find(
            f"{XSD}element[@name='{name}']"
        )

        if referenced is not None:
            return is_string_xsd_element(referenced)

    type_name = xsd_element.get("type")

    if type_name:
        return type_is_text(type_name, set())

    return simple_is_text(
        xsd_element.find(f"{XSD}simpleType"),
        set(),
    )




def handle_scalar(
    tag: str,
    instance: object,
    node: etree._Element,
    db_columns: list[str],
    xsd_child: etree._Element,
) -> bool:

    db_col = COLUMN_ALIAS_MAP.get(
        tag,
        match_db_column(tag, db_columns),
    )

    if not db_col:
        return False

    val = getattr(instance, db_col, None)

    if isinstance(val, list):
        build_array_node(
            node,
            tag,
            instance,
            xsd_child,
        )
        return True

    child = SubElement(node, tag)

    set_xml_value(
        element=child,
        value=val,
        is_string_xsd=is_string_xsd_element(
            xsd_child
        ),
    )

    return True



def build_array_node(
    parent: etree._Element,
    tag_name: str,
    instance: Any,
    xsd_child: etree._Element | None = None,
) -> etree._Element:

    arr_node = SubElement(parent, tag_name)

    db_columns = [
        col.name
        for col in instance.__table__.columns
    ]

    possible_matches = [
        col
        for col in db_columns
        if normalize_name(col).startswith(
            normalize_name(tag_name)
        )
    ]

    if not possible_matches:
        return arr_node

    list_data = getattr(
        instance,
        possible_matches[0],
        None,
    )

    if not list_data:
        return arr_node

    array_xsd = None

    if xsd_child is not None:
        array_xsd = xsd_child.find(
            f".//{XSD}element"
            "[@name='arrayElement']"
        )

    use_cdata = is_string_xsd_element(array_xsd)

    for value in list_data:
        item = SubElement(
            arr_node,
            "arrayElement",
        )

        set_xml_value(
            element=item,
            value=value,
            is_string_xsd=use_cdata,
        )

    return arr_node



from pathlib import Path
from lxml import etree

xml = Path("tactical_output.xml").read_text(
    encoding="utf-8"
)

root = etree.fromstring(xml.encode("utf-8"))

print("Valid XML syntax:", root is not None)
print("CDATA sections:", xml.count("<![CDATA["))

for field in [
    "ObjectId",
    "ToBeRemoved",
    "Name",
    "Classification",
    "Latitude",
    "ReferenceDate",
]:
    elements = root.xpath(
        f".//*[local-name()='{field}']"
    )

    if elements:
        sample = etree.tostring(
            elements[0],
            encoding="unicode",
        )
        print(f"{field}: {sample}")
