# ---------------------------------------------------------------------------
# tests 包标记文件
# ---------------------------------------------------------------------------
#
# 这个文件本身不写任何可执行代码，只靠"它存在"这件事，把 tests/ 目录标记
# 为一个 Python 包 (package)。
#
# 为什么需要它？
#   pytest 在默认的 "rootdir 模式" 下会按文件路径去 import 测试模块。
#   如果没有 __init__.py，那么：
#     tests/unit/test_policy.py
#     tests/integration/test_policy.py   （以后如果加这个文件）
#   会被 pytest 都视为同一个顶层模块 "test_policy"，进而触发经典报错：
#       ImportError: import file mismatch
#   加上 __init__.py 之后，它们会变成：
#     tests.unit.test_policy
#     tests.integration.test_policy
#   完整包路径不同，pytest 就不会混淆。
#
# 为什么注释写这么多而不是留空？
#   1. write_to_file 在空内容时会失败，所以至少要写点东西；
#   2. 之后任何人打开这个文件，都能立刻明白它为什么存在。
# ---------------------------------------------------------------------------
