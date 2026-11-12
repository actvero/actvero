"""Versioned source blocks; every split retains offsets into immutable source text."""

import csv
import io
import json
import re
import zipfile
from bisect import bisect_right
from html import unescape
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from app.modules.knowledge.schemas import Chunking
from app.modules.knowledge.structural import SKIPPED_TYPES, TITLE_TYPES, structural_groups

MAX_FILE = 20 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_CHUNKS = 5000
TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
REMOTE_TYPES = {".pdf", ".png", ".jpg", ".jpeg"}


def inspect_file(filename: str, data: bytes) -> tuple[str, str]:
    if not filename or len(filename) > 200 or any(c in filename for c in "/\\\r\n\x00"):
        raise ValueError("文件名无效")
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in TYPES:
        raise ValueError("支持 PDF、PNG、JPG、TXT、Markdown、CSV、DOCX 和 XLSX")
    if not data or len(data) > MAX_FILE:
        raise ValueError("请选择非空文件，单个文件不能超过 20 MiB")
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("PDF 文件内容无效")
    if extension == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG 文件内容无效")
    if extension in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG 文件内容无效")
    return extension, TYPES[extension]


def archive_files(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = z.infolist()
            if len(entries) > 3000 or sum(i.file_size for i in entries) > 100 * 1024 * 1024:
                raise ValueError("解析内容超出上限，请拆分文件")
            result = {}
            for item in entries:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
                    raise ValueError("文件包含无效路径")
                if item.is_dir():
                    continue
                if item.filename.endswith((".json", ".xml", ".rels")):
                    if item.file_size > 16 * 1024 * 1024:
                        raise ValueError("文档结构文件过大")
                    result[item.filename] = z.read(item)
            return result
    except (zipfile.BadZipFile, RuntimeError):
        raise ValueError("文档压缩结构无法读取") from None


def xml(data: bytes) -> ET.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("文档包含不支持的 XML 声明")
    return ET.fromstring(data)


def source_block(text: str, index: int, **location: Any) -> dict[str, Any]:
    return {"text": text, "type": "text", "block_id": str(index), **location}


def text_blocks(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    heading = ""
    for match in re.finditer(r"\S[^\n]*(?:\n(?!\s*\n)[^\n]+)*", text):
        value = match.group().strip()
        is_title = bool(re.match(r"^#{1,6}\s", value)) and "\n" not in value
        if is_title:
            heading = value.lstrip("# ")
        result.append(
            source_block(
                value,
                len(result),
                line=text.count("\n", 0, match.start()) + 1,
                heading=heading,
                **{"type": "title" if is_title else "text"},
            )
        )
    return result


def local_parse(filename: str, data: bytes) -> list[dict[str, Any]]:
    extension = PurePosixPath(filename).suffix.lower()
    try:
        if extension in {".txt", ".md"}:
            result = text_blocks(data.decode("utf-8-sig"))
        elif extension == ".csv":
            rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
            result = [
                source_block(" | ".join(row), i, line=i + 1, cell_range=f"row:{i + 1}")
                for i, row in enumerate(rows)
                if any(row)
            ]
        elif extension == ".docx":
            entries = archive_files(data)
            root = xml(entries["word/document.xml"])
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            result = []
            for i, p in enumerate(root.iter(ns + "p")):
                value = "".join(t.text or "" for t in p.iter(ns + "t"))
                if value.strip():
                    result.append(source_block(value, i, line=i + 1))
        elif extension == ".xlsx":
            result = xlsx_blocks(archive_files(data))
        else:
            raise ValueError("此文件需要 MinerU 解析")
    except (UnicodeError, ET.ParseError, KeyError, csv.Error):
        raise ValueError("文件内容无法读取，文本文件请使用 UTF-8 编码") from None
    validate_blocks(result)
    return result


def xlsx_blocks(entries: dict[str, bytes]) -> list[dict[str, Any]]:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    relationships = xml(entries["xl/_rels/workbook.xml.rels"])
    targets = {r.attrib["Id"]: r.attrib["Target"] for r in relationships}
    strings = []
    if "xl/sharedStrings.xml" in entries:
        strings = [
            "".join(t.text or "" for t in item.iter(ns + "t"))
            for item in xml(entries["xl/sharedStrings.xml"])
        ]
    blocks: list[dict[str, Any]] = []
    for sheet in xml(entries["xl/workbook.xml"]).iter(ns + "sheet"):
        key = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = targets[key]
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheet_root = xml(entries[path])
        for row in sheet_root.iter(ns + "row"):
            cells, refs = [], []
            for cell in row.findall(ns + "c"):
                refs.append(cell.get("r", ""))
                value = cell.findtext(ns + "v", "")
                if cell.get("t") == "s":
                    try:
                        value = strings[int(value)]
                    except (ValueError, IndexError):
                        raise ValueError("表格共享文本引用无效") from None
                elif cell.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(ns + "t"))
                cells.append(value)
            if cells and any(cells):
                blocks.append(
                    source_block(
                        " | ".join(cells),
                        len(blocks),
                        sheet=sheet.get("name", ""),
                        cell_range=f"{refs[0]}:{refs[-1]}",
                    )
                )
    return blocks


def validate_blocks(blocks: list[dict[str, Any]]) -> None:
    if not blocks:
        raise ValueError("未解析到可检索文字，请检查原文或 OCR 结果")
    if len(blocks) > 20000 or sum(len(b["text"]) for b in blocks) > MAX_TEXT:
        raise ValueError("文档内容过多，请拆分后上传")


def mineru_parse(data: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files = archive_files(data)
    name = next(
        (n for n in files if n.endswith("_content_list.json") or n == "content_list.json"), None
    )
    if name is None:
        raise ValueError("MinerU 未返回可识别的内容列表，请检查解析版本")
    try:
        items = json.loads(files[name])
        if not isinstance(items, list):
            raise ValueError()
        groups = items if items and isinstance(items[0], list) else [items]
        blocks: list[dict[str, Any]] = []
        heading = ""
        for group_index, group in enumerate(groups):
            for item in group:
                kind = item.get("type", "text")
                if kind in SKIPPED_TYPES:
                    continue
                value = item.get("text") or item.get("table_body") or item.get("content") or ""
                if not isinstance(value, str):
                    continue
                value = unescape(re.sub(r"<[^>]*>", " ", value)).strip()
                if not value:
                    continue
                if item.get("text_level") or kind in TITLE_TYPES:
                    heading = value
                    kind = "title"
                page_idx = item.get("page_idx", group_index)
                if type(page_idx) is not int or not 0 <= page_idx < 100000:
                    raise ValueError()
                box = item.get("bbox")
                valid_box = (
                    isinstance(box, list)
                    and len(box) == 4
                    and all(type(v) in {int, float} and 0 <= v <= 1000 for v in box)
                    and box[0] < box[2]
                    and box[1] < box[3]
                )
                blocks.append(
                    source_block(
                        value,
                        len(blocks),
                        page=page_idx + 1,
                        heading=heading,
                        bbox=[v / 1000 for v in box] if valid_box else None,
                        coordinate_space="normalized" if valid_box else "unknown",
                        type=kind,
                    )
                )
        validate_blocks(blocks)
        return {"format": "mineru-content-list", "content_list": items}, blocks
    except (ValueError, TypeError, AttributeError):
        raise ValueError("MinerU 内容结构不完整或超过允许范围") from None


def split_blocks(
    blocks: list[dict[str, Any]], config: Chunking, *, hard_limit: int = 10000
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group by structure or slide by length; retain every original character range."""
    if hard_limit < 1:
        raise ValueError("模型输入长度上限无效")
    smart = config.mode == "smart"
    cap = hard_limit if smart else min(config.max_chars, hard_limit)
    overlap = min(config.overlap_chars, cap - 1) if not smart else 0
    groups = (
        structural_groups(blocks, target=config.target_chars, maximum=config.max_chars)
        if smart
        else [blocks]
    )
    output: list[tuple[str, list[dict[str, Any]]]] = []
    for group in groups:
        spans: list[tuple[int, int, dict[str, Any]]] = []
        offset = 0
        for block in group:
            spans.append((offset, offset + len(block["text"]), block))
            offset += len(block["text"]) + 2
        value = "\n\n".join(block["text"] for block in group)
        ends = [end for _, end, _ in spans]
        start = 0
        while start < len(value):
            end = min(start + cap, len(value))
            if smart and end < len(value):
                # Prefer an existing block boundary, then a sentence boundary.
                candidate = bisect_right(ends, end) - 1
                if candidate >= 0 and ends[candidate] > start:
                    end = ends[candidate]
                else:
                    boundary = max(value.rfind(c, start + cap // 2, end) for c in "。！？\n； ")
                    if boundary >= 0:
                        end = boundary + 1
            refs = []
            for index in range(bisect_right(ends, start), len(spans)):
                left, right, block = spans[index]
                if left >= end:
                    break
                if right <= left:
                    continue
                location = {k: v for k, v in block.items() if k not in {"text", "type"}}
                refs.append(
                    {**location, "start": max(start - left, 0), "end": min(end, right) - left}
                )
            if refs:
                output.append((value[start:end], refs))
                if len(output) > MAX_CHUNKS:
                    raise ValueError("切片数量超过 5000，请拆分文档或调大切片长度")
            if end == len(value):
                break
            start = end - overlap
            if smart:
                next_block = bisect_right(ends, start)
                if next_block < len(spans):
                    start = max(start, spans[next_block][0])
    return output


def terms(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9][a-z0-9_.-]*", value.casefold()))
    for text in re.findall(r"[\u4e00-\u9fff]+", value):
        words.update(text[i : i + 2] for i in range(max(1, len(text) - 1)))
    return words
