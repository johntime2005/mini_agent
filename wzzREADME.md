2026.5.1
给 Python 核心层补 pytest基本完成
说明：主要新增tests文件夹：
1. conftest.py 用于将测试用例的工作目录放在临时目录，不影响真实环境
2. test_executor.py test_policy.py test_session.py 三个核心层测试文件，具体内容已在文件中做注释
未来：可能需要增加test_service.py?