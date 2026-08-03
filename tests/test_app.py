from perplex_studio import app


def test_application_entry_point_is_available() -> None:
    assert callable(app.main)
