"""
飞书 Docx Block → Markdown 文本转换器

将飞书 Docx API 返回的结构化 block 列表转换为可读的 Markdown 文本，
保留标题层级、列表、代码块等语义结构，供 RAG chunker 使用。
"""

import structlog

logger = structlog.get_logger(__name__)

# block_type → 名称映射（仅文档中实际用到的类型）
_BLOCK_TYPE_NAMES = {
    1: "page",
    2: "text",
    3: "heading1",
    4: "heading2",
    5: "heading3",
    6: "heading4",
    7: "heading5",
    8: "heading6",
    9: "heading7",
    10: "heading8",
    11: "heading9",
    12: "bullet",
    13: "ordered",
    14: "code",
    15: "quote",
    17: "todo",
    18: "bitable",
    22: "divider",
    23: "file",
    27: "image",
    31: "table",
    32: "table_cell",
}

# 需要提取 text_run 内容的 block 类型（文本类）
_TEXT_BLOCK_TYPES = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17}


def _extract_text_from_elements(elements: list[dict]) -> str:
    """从 block 的 elements 数组中提取纯文本内容。

    飞书 docx block 的文本结构：
    {
        "elements": [
            {"text_run": {"content": "Hello ", "text_element_style": {}}},
            {"text_run": {"content": "world", "text_element_style": {"bold": true}}}
        ]
    }

    也处理 mention_user、mention_doc、equation 等特殊元素。
    """
    parts: list[str] = []
    for elem in elements:
        # text_run — 最常见的文本元素
        text_run = elem.get("text_run")
        if text_run:
            content = text_run.get("content", "")
            if content:
                parts.append(content)
            continue

        # mention_user — @某人
        mention_user = elem.get("mention_user")
        if mention_user:
            parts.append(f"@{mention_user.get('user_id', 'user')}")
            continue

        # mention_doc — @文档
        mention_doc = elem.get("mention_doc")
        if mention_doc:
            title = mention_doc.get("title", "doc")
            parts.append(f"[{title}]")
            continue

        # equation — 公式
        equation = elem.get("equation")
        if equation:
            parts.append(f"${equation.get('content', '')}$")
            continue

        # 其他未知元素类型，跳过
    return "".join(parts)


def _get_block_content(block: dict) -> str:
    """从单个 block 中提取文本内容。

    飞书 block 的 content 字段名随 block_type 变化：
    - text block → block["text"]["elements"]
    - heading1 block → block["heading1"]["elements"]
    - code block → block["code"]["elements"]
    等等。
    """
    # 尝试所有可能的 content 字段名
    for key in ("text", "heading1", "heading2", "heading3", "heading4",
                "heading5", "heading6", "heading7", "heading8", "heading9",
                "bullet", "ordered", "code", "quote", "todo"):
        content_obj = block.get(key)
        if content_obj and isinstance(content_obj, dict):
            elements = content_obj.get("elements", [])
            return _extract_text_from_elements(elements)
    return ""


def blocks_to_text(blocks: list[dict]) -> str:
    """将飞书 Docx blocks 列表转换为 Markdown 文本。

    Args:
        blocks: 飞书 Docx API 返回的 block 列表（data.items）

    Returns:
        Markdown 格式的纯文本
    """
    lines: list[str] = []
    ordered_counter = 0  # 有序列表计数器

    for block in blocks:
        block_type = block.get("block_type", 0)

        # 重置有序列表计数器（遇到非 ordered 类型时）
        if block_type != 13:
            ordered_counter = 0

        if block_type in (3, 4, 5, 6, 7, 8, 9, 10, 11):
            # heading1-9 → Markdown 标题
            level = block_type - 2  # heading1=3 → level 1
            text = _get_block_content(block)
            if text:
                lines.append(f"{'#' * level} {text}")

        elif block_type == 2:
            # 普通文本
            text = _get_block_content(block)
            if text:
                lines.append(text)

        elif block_type == 12:
            # 无序列表
            text = _get_block_content(block)
            if text:
                lines.append(f"- {text}")

        elif block_type == 13:
            # 有序列表
            ordered_counter += 1
            text = _get_block_content(block)
            if text:
                lines.append(f"{ordered_counter}. {text}")

        elif block_type == 14:
            # 代码块
            text = _get_block_content(block)
            # 尝试获取语言标识
            code_obj = block.get("code", {})
            style = code_obj.get("style", {})
            language = style.get("language", "")
            lang_map = {
                1: "plaintext", 2: "abap", 3: "ada", 4: "apache",
                5: "apex", 6: "assembly", 7: "bash", 8: "bnf",
                9: "c", 10: "clojure", 11: "cmake", 12: "coffeescript",
                13: "cpp", 14: "csharp", 15: "css", 16: "d", 17: "dart",
                18: "delphi", 19: "django", 20: "dockerfile", 21: "elixir",
                22: "erlang", 23: "fortran", 24: "fsharp", 25: "gherkin",
                26: "go", 27: "groovy", 28: "haskell", 29: "html",
                30: "http", 31: "json", 32: "julia", 33: "kotlin",
                34: "latex", 35: "lisp", 36: "lua", 37: "makefile",
                38: "markdown", 39: "matlab", 40: "nginx", 41: "objectivec",
                42: "ocaml", 43: "perl", 44: "php", 45: "powershell",
                46: "prolog", 47: "protobuf", 48: "python", 49: "r",
                50: "ruby", 51: "rust", 52: "sass", 53: "scala",
                54: "scheme", 55: "shell", 56: "sql", 57: "swift",
                58: "thrift", 59: "typescript", 60: "vbnet", 61: "verilog",
                62: "vhdl", 63: "xml", 64: "yaml",
            }
            lang_str = lang_map.get(language, "") if isinstance(language, int) else str(language)
            if text:
                lines.append(f"```{lang_str}")
                lines.append(text)
                lines.append("```")

        elif block_type == 15:
            # 引用
            text = _get_block_content(block)
            if text:
                # 多行引用每行加 > 前缀
                for line in text.split("\n"):
                    lines.append(f"> {line}")

        elif block_type == 17:
            # 待办事项
            text = _get_block_content(block)
            todo_obj = block.get("todo", {})
            style = todo_obj.get("style", {})
            done = style.get("done", False)
            checkbox = "[x]" if done else "[ ]"
            if text:
                lines.append(f"- {checkbox} {text}")

        elif block_type == 22:
            # 分割线
            lines.append("---")

        elif block_type == 27:
            # 图片 — 无法从 blocks API 获取实际内容
            lines.append("[图片]")

        elif block_type == 23:
            # 文件附件
            lines.append("[文件]")

        elif block_type == 31:
            # 表格 — 需要特殊处理
            lines.extend(_parse_table(block, blocks))

        elif block_type in (1, 18, 32, 999, 0):
            # page / bitable / table_cell / unsupported / unknown → 跳过
            continue

        else:
            logger.debug("unknown_block_type", block_type=block_type, block_id=block.get("block_id"))
            continue

    return "\n".join(lines)


def _parse_table(table_block: dict, all_blocks: list[dict]) -> list[str]:
    """解析表格 block，返回 Markdown 表格行。

    飞书表格结构：table block 包含 children（table_cell 的 block_id），
    每个 table_cell 又包含自己的 children（文本 block）。

    但 blocks API 返回的是扁平列表，需要通过 parent_id 关系重建表格。
    这里做一个简化实现：直接从 table block 的属性中获取行列数，
    然后按顺序提取 cell 内容。
    """
    table_obj = table_block.get("table", {})
    property_info = table_obj.get("property", {})
    row_count = property_info.get("row_size", 0)
    col_count = property_info.get("column_size", 0)

    if row_count == 0 or col_count == 0:
        return []

    # 获取 table 的 children（cell block_id 列表）
    children = table_block.get("children", [])
    if not children:
        return []

    # 构建 block_id → block 的索引
    block_index = {b.get("block_id"): b for b in all_blocks}

    # 按行列顺序提取 cell 内容
    rows: list[list[str]] = []
    for r in range(row_count):
        row: list[str] = []
        for c in range(col_count):
            idx = r * col_count + c
            if idx < len(children):
                cell_block = block_index.get(children[idx])
                if cell_block:
                    # cell 内部的 children 是文本 block
                    cell_children = cell_block.get("children", [])
                    cell_texts: list[str] = []
                    for child_id in cell_children:
                        child_block = block_index.get(child_id)
                        if child_block:
                            text = _get_block_content(child_block)
                            if text:
                                cell_texts.append(text)
                    row.append(" ".join(cell_texts) if cell_texts else "")
                else:
                    row.append("")
            else:
                row.append("")
        rows.append(row)

    if not rows:
        return []

    # 生成 Markdown 表格
    result: list[str] = []
    # 表头
    header = rows[0]
    result.append("| " + " | ".join(header) + " |")
    result.append("| " + " | ".join(["---"] * len(header)) + " |")
    # 数据行
    for row in rows[1:]:
        result.append("| " + " | ".join(row) + " |")

    return result
