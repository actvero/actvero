"""Bounded, non-executing ZIP inspection. Nothing is extracted to the filesystem."""

import hashlib
import re
import stat
import unicodedata
import zlib
from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import yaml
from fastapi import HTTPException
from yaml.tokens import AliasToken, AnchorToken

from app.modules.skills.icons import package_icon

MAX_PACKAGE = 20 * 1024 * 1024
MAX_UNPACKED = 40 * 1024 * 1024
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 500
MAX_PREVIEW = 256 * 1024


@dataclass
class Package:
    name: str
    description: str
    skill_md: str
    files: list[dict[str, str | int | bool]]
    sha256: str
    package_icon: str = ""
    icon_warning: str = ""


def invalid(message: str) -> HTTPException:
    return HTTPException(422, message)


def inspect_package(data: bytes) -> Package:
    if len(data) > MAX_PACKAGE:
        raise HTTPException(413, "技能包不能超过 20 MB")
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_FILES:
                raise invalid("技能包必须包含 1–500 个文件或目录")
            paths: set[str] = set()
            total = 0
            contents: dict[str, bytes] = {}
            for info in entries:
                path = info.filename.rstrip("/")
                if (
                    not path
                    or path.startswith("/")
                    or "\\" in path
                    or ":" in path
                    or any(c in path for c in ("\x00", "\r", "\n"))
                    or any(unicodedata.category(c).startswith("C") for c in path)
                    or any(p in {"", ".", ".."} for p in path.split("/"))
                    or len(path) > 500
                    or info.orig_filename != info.filename
                ):
                    raise invalid("技能包包含不安全的文件路径")
                normalized = unicodedata.normalize("NFC", path).casefold()
                if normalized in paths:
                    raise invalid("技能包包含重复文件路径")
                paths.add(normalized)
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise invalid("技能包不支持符号链接或特殊文件")
                if info.flag_bits & 1:
                    raise invalid("技能包不支持加密 ZIP")
                total += info.file_size
                if info.file_size > MAX_FILE or total > MAX_UNPACKED:
                    raise invalid("单文件不能超过 5 MB，解压后总大小不能超过 40 MB")
                if info.is_dir():
                    continue
                parts = path.split("/")
                if any(p in {".git", "node_modules", "__pycache__"} for p in parts):
                    raise invalid("请移除 .git、node_modules 和缓存目录")
                if any(p == ".env" or p.startswith(".env.") and p != ".env.example" for p in parts):
                    raise invalid("请移除环境凭据文件后重新上传")
                contents[path] = archive.read(info)
            for path in contents:
                if any(
                    "/".join(path.split("/")[:i]) in contents
                    for i in range(1, len(path.split("/")))
                ):
                    raise invalid("文件与目录路径发生冲突")
            skill_files = [p for p in contents if p.split("/")[-1] == "SKILL.md"]
            if len(skill_files) != 1:
                raise invalid("每次只能上传一个技能，且必须包含唯一的 SKILL.md")
            skill_path = skill_files[0]
            prefix = skill_path.removesuffix("SKILL.md")
            if prefix and (
                prefix.count("/") != 1 or any(not p.startswith(prefix) for p in contents)
            ):
                raise invalid("SKILL.md 应位于包根目录或唯一的一级目录中")
            if len(contents[skill_path]) > MAX_PREVIEW:
                raise invalid("SKILL.md 不能超过 256 KB")
            raw = contents[skill_path].decode("utf-8-sig")
            match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|$)", raw, re.S)
            if not match or len(match[1]) > 16384:
                raise invalid("SKILL.md 需要 YAML frontmatter，包含 name 和 description")
            if any(isinstance(t, (AliasToken, AnchorToken)) for t in yaml.scan(match[1])):
                raise invalid("技能元数据不支持 YAML 别名或锚点")
            meta = yaml.safe_load(match[1])
            if not isinstance(meta, dict):
                raise invalid("技能元数据必须是键值对象")
            name, description = meta.get("name"), meta.get("description")
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or len(name) > 64
            ):
                raise invalid("name 须为不超过 64 位的小写字母、数字和单个连字符")
            if prefix and prefix[:-1] != name:
                raise invalid("技能目录名须与 SKILL.md 中的 name 一致")
            if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
                raise invalid("description 必须为 1–1024 字的文本")
            files: list[dict[str, str | int | bool]] = []
            for path, content in sorted(contents.items()):
                try:
                    text = content.decode("utf-8")
                    previewable = len(content) <= MAX_PREVIEW and "\x00" not in text
                except UnicodeDecodeError:
                    previewable = False
                files.append(
                    {
                        "path": path,
                        "size": len(content),
                        "previewable": previewable,
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            return Package(
                name,
                description.strip(),
                raw[match.end() :].lstrip(),
                files,
                hashlib.sha256(data).hexdigest(),
                *package_icon(contents, prefix),
            )
    except (
        BadZipFile,
        EOFError,
        zlib.error,
        OSError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        UnicodeError,
        yaml.YAMLError,
        RecursionError,
    ):
        raise invalid("技能包无法读取，请检查 ZIP 和 SKILL.md 格式") from None


def read_file(data: bytes, path: str) -> str:
    with ZipFile(BytesIO(data)) as archive:
        try:
            info = archive.getinfo(path)
        except KeyError:
            raise HTTPException(404, "文件不存在") from None
        if info.file_size > MAX_PREVIEW:
            raise invalid("此文件过大，请下载技能包后查看")
        try:
            text = archive.read(info).decode("utf-8")
        except UnicodeError:
            raise invalid("此文件不支持文本预览") from None
        if "\x00" in text:
            raise invalid("此文件不支持文本预览")
        return text
