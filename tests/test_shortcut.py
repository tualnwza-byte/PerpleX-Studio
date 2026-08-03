from pathlib import Path

from perplex_studio.shortcut import _powershell_script


def test_shortcut_script_uses_the_selected_python_and_working_directory() -> None:
    script = _powershell_script(
        Path(r"C:\Studio\.venv\Scripts\python.exe"),
        Path(r"C:\Studio"),
        Path(r"C:\Users\User\Desktop\PerpleX Studio.lnk"),
    )

    assert "-m perplex_studio.app" in script
    assert "C:\\Studio\\.venv\\Scripts\\python.exe" in script
    assert "C:\\Users\\User\\Desktop\\PerpleX Studio.lnk" in script
