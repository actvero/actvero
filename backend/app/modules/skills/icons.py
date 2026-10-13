"""Portable icons. Package metadata is optional, bounded and never executed or fetched."""

import base64
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml
from fastapi import HTTPException
from yaml.tokens import AliasToken, AnchorToken

from app.modules.account.service import normalize_avatar

MAX_ICON = 256 * 1024


@lru_cache(maxsize=1)
def catalog() -> list[dict[str, str]]:
    return json.loads((Path(__file__).parent / "assets/icons.json").read_text())["items"]  # type: ignore[no-any-return]


def library_image(key: str) -> str:
    for item in catalog():
        if item["key"] == key:
            return item["image"]
    raise ValueError("请选择图标库中已有的图标")


def raster_image(data: bytes) -> str:
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("图标不能超过 2 MB")
    return "data:image/webp;base64," + base64.b64encode(normalize_avatar(data)).decode()


def uploaded_image(value: str) -> str:
    if not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+", value):
        raise ValueError("请选择 PNG、JPG 或 WebP 图标")
    try:
        return raster_image(base64.b64decode(value.split(",", 1)[1], validate=True))
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def svg_image(data: bytes) -> str:
    # Deliberately support only static vector shapes. No style, links, entities,
    # embedded images, animations, foreignObject or external resources.
    if len(data) > MAX_ICON:
        raise ValueError("SVG 过大")
    content = data.decode("utf-8-sig")
    content = re.sub(r"\A\s*<\?xml\s[^?]*\?>", "", content)
    if "<!" in content or "<?" in content:
        raise ValueError("SVG 包含不支持的声明")
    root = ET.fromstring(content)
    tags = {
        "svg",
        "g",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "title",
        "desc",
    }
    attributes = {
        "viewBox",
        "width",
        "height",
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "d",
        "points",
        "transform",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "fill-rule",
        "clip-rule",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
        "preserveAspectRatio",
        "version",
    }
    nodes = list(root.iter())
    if len(nodes) > 500 or root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
        raise ValueError("SVG 结构无效")
    for node in nodes:
        tag = node.tag.removeprefix("{http://www.w3.org/2000/svg}")
        if tag not in tags:
            raise ValueError("SVG 含不支持的元素")
        node.tag = tag
        for name, value in node.attrib.items():
            if (
                name not in attributes
                or not re.fullmatch(r"[a-zA-Z0-9\s.,+%#()\-]*", value)
                or "url" in value.lower()
            ):
                raise ValueError("SVG 含不支持的属性")
        if tag not in {"title", "desc"}:
            node.text = None
        node.tail = None
    root.set("xmlns", "http://www.w3.org/2000/svg")
    return "data:image/svg+xml;base64," + base64.b64encode(ET.tostring(root)).decode()


def package_icon(contents: dict[str, bytes], prefix: str) -> tuple[str, str]:
    raw = contents.get(prefix + "agents/openai.yaml")
    if raw is None:
        return "", ""
    try:
        if len(raw) > 16384:
            raise ValueError("配置过大")
        if any(isinstance(t, (AliasToken, AnchorToken)) for t in yaml.scan(raw)):
            raise ValueError("配置含别名")
        meta = yaml.safe_load(raw)
        interface = meta.get("interface", {}) if isinstance(meta, dict) else None
        if not isinstance(interface, dict):
            raise ValueError("配置格式无效")
        failed = False
        for field in ("icon_small", "icon_large"):
            path = interface.get(field)
            if not path:
                continue
            try:
                if not isinstance(path, str):
                    raise ValueError("路径无效")
                path = path.removeprefix("./")
                if (
                    ":" in path
                    or "\\" in path
                    or any(p in {"", ".", ".."} for p in path.split("/"))
                ):
                    raise ValueError("路径须在技能包内")
                data = contents[prefix + path]
                image = svg_image(data) if path.lower().endswith(".svg") else raster_image(data)
                return image, "小图标不可用，已使用包内大图标。" if failed else ""
            except (ValueError, KeyError, HTTPException, ET.ParseError, RecursionError):
                failed = True
        return "", "包内图标不可用，可在技能设置中选择图标。" if failed else ""
    except (ValueError, UnicodeError, yaml.YAMLError, RecursionError):
        return "", "图标配置无法读取，可在技能设置中选择图标。"


def resolved_icon(choice: dict[str, str], packaged: str) -> dict[str, str]:
    source = choice.get("source", "auto")
    if source == "library":
        image = library_image(choice.get("key", ""))
    elif source == "upload":
        image = choice.get("image", "")
    else:
        image, source = packaged, "package" if packaged else "fallback"
    return {
        "source": source,
        "image": image,
        "sha256": hashlib.sha256(base64.b64decode(image.split(",", 1)[1])).hexdigest()
        if image
        else "",
    }
