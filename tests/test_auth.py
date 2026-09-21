import stat

from fenox.core.auth import AuthStore


def test_owner_credential_lifecycle(tmp_path):
    auth = AuthStore(tmp_path / "auth.json")
    assert not auth.has_owner()
    assert not auth.verify_password("anything")

    auth.set_owner("correct horse battery staple")
    assert auth.has_owner()
    assert auth.verify_password("correct horse battery staple")
    assert not auth.verify_password("wrong")

    auth.reset()
    assert not auth.has_owner()


def test_sessions_are_signed_and_expire(tmp_path):
    auth = AuthStore(tmp_path / "auth.json")
    auth.set_owner("secret123")

    token = auth.issue_session()
    assert auth.verify_session(token)
    assert not auth.verify_session(token + "tampered")
    assert not auth.verify_session("")


def test_script_token_verifies_with_constant_time_compare(tmp_path):
    auth = AuthStore(tmp_path / "auth.json")
    auth.set_owner("secret123")

    token = auth.token()
    assert token and auth.verify_token(token)
    assert not auth.verify_token("nope")
    assert not auth.verify_token(None)

    rotated = auth.rotate_token()
    assert rotated != token
    assert not auth.verify_token(token)
    assert auth.verify_token(rotated)


def test_auth_file_is_owner_only(tmp_path):
    path = tmp_path / "auth.json"
    auth = AuthStore(path)
    auth.set_owner("secret123")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0, oct(mode)
