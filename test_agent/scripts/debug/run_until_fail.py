"""持续执行 test_runner.py，失败时停止。"""
import subprocess
import sys

test_case = sys.argv[1] if len(sys.argv) > 1 else "Nike_autofill_Signed_In"
run = 0

while True:
    run += 1
    print(f"\n{'='*60}")
    print(f"Run #{run}  test-case: {test_case}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, "test_agent/test_runner.py", "--test-case", test_case],
        cwd=r"c:\repos\browser-use",
    )

    if result.returncode != 0:
        print(f"\n❌ FAILED at run #{run}, stopping.")
        sys.exit(1)

    print(f"\n✅ Run #{run} passed, continuing...")
