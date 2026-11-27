"""테스트를 잘라서 돌린다 (셸 한 번에 300초 제한이 있어 나눠 실행할 때).

    python3 tests/run_slice.py 0 25     # 이름 순 0~24번째 테스트
    python3 tests/run_slice.py 25 50
"""
import sys
import unittest

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import test_app  # noqa: E402

start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 6

loader = unittest.TestLoader()
names = sorted(loader.getTestCaseNames(test_app.AppTest))
print('총 %d개 · %d~%d' % (len(names), start, min(end, len(names)) - 1), flush=True)

suite = unittest.TestSuite([test_app.AppTest(n) for n in names[start:end]])
res = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
