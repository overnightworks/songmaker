"""Reads the XMP packet of a published image the way a strict XMP reader does."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
IPTC_EXTENSION_NAMESPACE = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"


def read_digital_source_type(image_path: Path) -> str:
    """The IPTC digital source type of a PNG or JPEG's XMP packet, parsed as XML."""
    with Image.open(image_path) as image:
        packet = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    description = ElementTree.fromstring(packet).find(f".//{{{RDF_NAMESPACE}}}Description")
    assert description is not None, image_path.name
    return description.attrib[f"{{{IPTC_EXTENSION_NAMESPACE}}}DigitalSourceType"]
