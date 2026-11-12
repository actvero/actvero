import gzip
import hashlib
import json
import re
import tarfile
import zlib
from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from app.modules.workbenches.configuration import parse_fields
from app.modules.workbenches.schemas import WorkbenchConfigField

MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_ICON_BYTES = 64 * 1024
MAX_ICON_EDGE = 512
MAX_PREVIEW_BYTES = 128 * 1024
MAX_PREVIEW_EDGE = 2048
MAX_PREVIEWS = 3
IMAGE_PATH = re.compile(r"\./assets/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(png|jpe?g|webp)", re.ASCII)
IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
PACKAGE_NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", re.ASCII)
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
    re.ASCII,
)


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    dsh_requirement: str
    display_name: str
    description: str
    sha256: str
    config_fields: list[WorkbenchConfigField]
    icon_data_url: str | None
    preview_data_urls: list[str]


def version_order(value: str) -> tuple[int, int, int, bool, tuple[tuple[int, int | str], ...]]:
    """SemVer precedence ignores build metadata and compares numeric identifiers numerically."""
    match = SEMVER.fullmatch(value) if len(value) <= 80 else None
    if not match:
        raise ValueError("包版本必须使用完整的 SemVer 格式")
    major, minor, patch, prerelease = match.groups()
    identifiers = prerelease.split(".") if prerelease else []
    if any(item.isdecimal() and len(item) > 1 and item.startswith("0") for item in identifiers):
        raise ValueError("预发布版本的数字标识不能有前导零")
    return (
        int(major),
        int(minor),
        int(patch),
        prerelease is None,
        tuple((0, int(item)) if item.isdecimal() else (1, item) for item in identifiers),
    )


def _json_file(archive: tarfile.TarFile, member: tarfile.TarInfo) -> dict[str, object]:
    source = archive.extractfile(member)
    if source is None or member.size > MAX_JSON_BYTES:
        raise ValueError("包内 JSON 文件过大或不可读")
    with source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("包内 JSON 文件必须为对象")
    return value


def _path(member: tarfile.TarInfo) -> str:
    name = member.name.rstrip("/") if member.isdir() else member.name
    parts = name.split("/")
    if (
        len(name) > 512
        or "\\" in name
        or ":" in name
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0] != "package"
        or (len(parts) == 1 and not member.isdir())
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError("包内文件路径无效")
    if not (member.isfile() or member.isdir()) or member.issparse():
        raise ValueError("包内只允许普通文件与目录")
    return name


def _image(
    archive: tarfile.TarFile,
    entries: dict[str, tarfile.TarInfo],
    path: object,
    *,
    label: str,
    max_bytes: int,
    max_edge: int,
) -> str:
    if not isinstance(path, str) or len(path) > 200 or not (match := IMAGE_PATH.fullmatch(path)):
        raise ValueError(f"{label}须指向 ./assets 下的 PNG、JPEG 或 WebP 图片")
    entry = entries.get("package/" + path[2:])
    if entry is None or not entry.isfile() or not 0 < entry.size <= max_bytes:
        raise ValueError(f"{label}必须是包内不超过 {max_bytes // 1024} KiB 的图片文件")
    source = archive.extractfile(entry)
    if source is None:
        raise ValueError(f"无法读取{label}")
    with source:
        data = source.read()
    image_format = IMAGE_FORMATS[match[1]]
    try:
        with Image.open(BytesIO(data), formats=[image_format]) as image:
            if max(image.size) > max_edge or getattr(image, "is_animated", False):
                raise ValueError(f"{label}须为不超过 {max_edge} × {max_edge} 像素的静态图片")
            image.load()
    except (OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError(f"{label}无法解码或格式与扩展名不符") from error
    return f"data:image/{image_format.lower()};base64,{b64encode(data).decode('ascii')}"


def inspect(data: bytes) -> Package:
    """Inspect an Actvero .tgz in memory without extracting or running its entries."""
    if not data or len(data) > MAX_PACKAGE_BYTES:
        raise ValueError("工作台包大小必须在 0 到 8 MiB 之间")
    try:
        with gzip.GzipFile(fileobj=BytesIO(data)) as compressed:
            raw = compressed.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ValueError("工作台包解压后不能超过 32 MiB")
        with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
            entries: dict[str, tarfile.TarInfo] = {}
            for member in archive:
                entry_name = _path(member)
                if entry_name in entries or len(entries) >= 1024:
                    raise ValueError("包内文件重复或数量过多")
                entries[entry_name] = member
            for entry_name in entries:
                parts = entry_name.split("/")
                for i in range(1, len(parts)):
                    parent = entries.get("/".join(parts[:i]))
                    if parent is not None and not parent.isdir():
                        raise ValueError("包内目录与文件路径冲突")
            manifest_entry = entries.get("package/package.json")
            if manifest_entry is None or not manifest_entry.isfile():
                raise ValueError("缺少 package/package.json")
            manifest = _json_file(archive, manifest_entry)
            dsh = manifest.get("dsh")
            if not isinstance(dsh, dict):
                raise ValueError("缺少工作台格式声明")
            icon = (
                _image(
                    archive,
                    entries,
                    dsh["actveroWorkbenchIcon"],
                    label="工作台头像",
                    max_bytes=MAX_ICON_BYTES,
                    max_edge=MAX_ICON_EDGE,
                )
                if "actveroWorkbenchIcon" in dsh
                else None
            )
            paths = dsh.get("actveroWorkbenchPreviews", [])
            if (
                not isinstance(paths, list)
                or len(paths) > MAX_PREVIEWS
                or any(not isinstance(path, str) for path in paths)
                or len(set(paths)) != len(paths)
            ):
                raise ValueError("工作台预览最多可声明 3 个不同的图片路径")
            previews = [
                _image(
                    archive,
                    entries,
                    path,
                    label="工作台预览",
                    max_bytes=MAX_PREVIEW_BYTES,
                    max_edge=MAX_PREVIEW_EDGE,
                )
                for path in paths
            ]
            locale_entry = entries.get("package/locale/en.json")
            locale = (
                _json_file(archive, locale_entry) if locale_entry and locale_entry.isfile() else {}
            )
    except (
        OSError,
        EOFError,
        UnicodeError,
        tarfile.TarError,
        zlib.error,
        RecursionError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError("无法读取工作台 .tgz 安装包") from error

    name, version = manifest.get("name"), manifest.get("version")
    if not isinstance(name, str) or len(name) > 214 or not PACKAGE_NAME.fullmatch(name):
        raise ValueError("包名无效")
    if not isinstance(version, str):
        raise ValueError("缺少包版本")
    version_order(version)
    exports, engines = (manifest.get(key) for key in ("exports", "engines"))
    if not isinstance(exports, dict) or not isinstance(engines, dict):
        raise ValueError("缺少工作台入口或运行时要求")
    if type(dsh.get("actveroWorkbench")) is not int or dsh["actveroWorkbench"] != 1:
        raise ValueError("仅支持 Actvero 工作台包格式 1")
    client, bundle = dsh.get("client"), dsh.get("bundle")
    inject = client.get("inject") if isinstance(client, dict) else None
    if (
        not isinstance(client, dict)
        or client.get("platform") != "web"
        or (not isinstance(inject, list) or "@actvero/dsh-capability-ui" not in inject)
    ):
        raise ValueError("缺少 Actvero 客户端注册声明")
    for entry in (
        exports.get("."),
        exports.get("./client"),
        bundle.get("patch") if isinstance(bundle, dict) else None,
    ):
        file = (
            entries.get("package/" + entry[2:])
            if isinstance(entry, str) and entry.startswith("./")
            else None
        )
        if file is None or not file.isfile() or not file.size:
            raise ValueError("缺少 Host、Client 或配置入口文件")
    requirement = engines.get("dsh")
    if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 160:
        raise ValueError("缺少有效的 DSH 运行时要求")
    scripts = manifest.get("scripts", {})
    if not isinstance(scripts, dict) or any(
        stage in scripts for stage in ("preinstall", "install", "postinstall", "prepare")
    ):
        raise ValueError("工作台包不能声明安装脚本")
    meta = locale.get("meta")
    title = meta.get("title") if isinstance(meta, dict) else None
    summary = meta.get("description") if isinstance(meta, dict) else None
    description = (
        summary if isinstance(summary, str) and summary.strip() else manifest.get("description")
    )
    display_name = (title.strip() if isinstance(title, str) and title.strip() else name)[:100]
    description = description.strip()[:1024] if isinstance(description, str) else ""
    for value in (display_name, description, requirement):
        if "\0" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("包内展示资料包含无效字符")
    return Package(
        name=name,
        version=version,
        dsh_requirement=requirement.strip(),
        display_name=display_name,
        description=description,
        sha256=hashlib.sha256(data).hexdigest(),
        config_fields=parse_fields(dsh.get("actveroWorkbenchConfig", [])),
        icon_data_url=icon,
        preview_data_urls=previews,
    )
