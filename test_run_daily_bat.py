"""run_daily.bat must stay ASCII with CRLF line endings.

The launcher runs `chcp 65001` itself, and cmd.exe then misreads multibyte
UTF-8 lines in the rest of the file: in a console that starts on code page
949, the tail of a Korean comment ran as a command and printed
"'니다.' is not recognized as an internal or external command".
LF-only endings are the other classic way to break a batch file's goto/labels.
"""

from pathlib import Path

BAT = Path(__file__).resolve().parent / "run_daily.bat"


def test_run_daily_bat_is_ascii():
    data = BAT.read_bytes()
    bad = [
        (n, line.decode("utf-8", errors="replace"))
        for n, line in enumerate(data.split(b"\n"), start=1)
        if any(b > 0x7F for b in line)
    ]
    assert not bad, f"non-ASCII lines in run_daily.bat: {bad}"


def test_run_daily_bat_uses_crlf():
    data = BAT.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n"), "run_daily.bat must use CRLF line endings"
