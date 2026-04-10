"""make_release.py

在 Blender 外部打包插件时，如果直接使用资源管理器压缩，中文文件名会被
按本地编码写入 ZIP，Blender 在安装时解码失败就会出现乱码。这个脚本使用
Python 的 `zipfile` 模块手动设置 UTF-8 标记位，确保中文文件名不再乱码。

使用方法：

```bash
python make_release.py
```

生成的压缩包会输出在脚本所在目录，文件名为 `<插件目录名>.zip`。

可选参数：

```
python make_release.py --output custom_name.zip
```

如果不希望将某些文件打包（如 `__pycache__`、`.git`），可以在
`EXCLUDE_PATTERNS` 中添加匹配规则。
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator


ROOT_DIR = Path(__file__).resolve().parent
ADDON_NAME = ROOT_DIR.name
DEFAULT_OUTPUT = ROOT_DIR / f"{ADDON_NAME}.zip"

# 需要排除的路径模式（相对目录匹配）
EXCLUDE_PATTERNS = {
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".git",
    ".gitignore",
    # 如需将本脚本也打进压缩包，请不要在这里排除
}


def should_exclude(relative_path: Path) -> bool:
    """判断文件/目录是否应该被排除"""
    rel = relative_path.as_posix()
    parts = rel.split("/")

    for pattern in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def iter_files(root: Path) -> Iterator[Path]:
    """遍历目录下所有文件，自动跳过排除项"""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(ROOT_DIR)
        if should_exclude(rel_path):
            continue
        yield path


def write_zip(output_path: Path, files: Iterable[Path]) -> None:
    """写出 zip 文件，并为条目设置 UTF-8 标记位"""
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            rel_path = file_path.relative_to(ROOT_DIR)
            arcname = f"{ADDON_NAME}/{rel_path.as_posix()}"

            # 使用 ZipInfo 设置 UTF-8 标记位
            info = zipfile.ZipInfo(arcname)
            info.flag_bits |= 0x800  # 告知解压器文件名使用 UTF-8
            info.external_attr = (file_path.stat().st_mode & 0xFFFF) << 16

            with file_path.open("rb") as f:
                zf.writestr(info, f.read())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打包 Blender 插件并保留中文文件名")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出 zip 文件路径 (默认: 插件目录同名)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output

    if not output.is_absolute():
        output = ROOT_DIR / output

    if output.exists():
        output.unlink()

    files = list(iter_files(ROOT_DIR))
    if not files:
        print("⚠️ 没有找到需要打包的文件。")
        return 1

    write_zip(output, files)

    print(f"✅ 插件已打包：{output}")
    print(f"📦 共包含 {len(files)} 个文件，已自动设置 UTF-8 文件名标记。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

