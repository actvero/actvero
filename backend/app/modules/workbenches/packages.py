import gzip
import hashlib
import json
import re
import tarfile
import zlib
from dataclasses import dataclass
from io import BytesIO

from app.modules.workbenches.configuration import parse_fields
from app.modules.workbenches.schemas import WorkbenchConfigField

MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
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
    dsh, exports, engines = (manifest.get(key) for key in ("dsh", "exports", "engines"))
    if not isinstance(dsh, dict) or not isinstance(exports, dict) or not isinstance(engines, dict):
        raise ValueError("缺少工作台格式声明、入口或运行时要求")
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
    )
