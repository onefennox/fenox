from fenox.core import phone


def test_parse_content_rows_keeps_commas_and_folds_wrapped_values():
    output = (
        "Row: 0 _id=1, body=hello, world, address=+1234567890\n"
        "Row: 1 _id=2, body=first line\nsecond line\n"
    )
    rows = phone.parse_content_rows(output)
    assert rows[0]["body"] == "hello, world"
    assert rows[0]["address"] == "+1234567890"
    assert rows[1]["body"] == "first line\nsecond line"


def test_calls_where_builds_grouped_clauses():
    assert phone.calls_where(["missed"]) == "type=3"
    assert phone.calls_where(["missed", "incoming"]) == "(type=3 OR type=1)"
    # Matched by the last nine digits, so a country code on either side still lines up.
    assert phone.calls_where(number="+1 (555) 123-4567").startswith("number LIKE '%551234567")


def test_threads_merge_grouped_latest_and_unread(monkeypatch):
    def fake_query(serial, uri, projection=None, where=None, sort=None):
        if uri == phone.SMS_THREADS_URI:
            return True, [{"thread_id": "1", "msg_count": "2", "snippet": "see you"}], ""
        if uri == phone.SMS_URI:
            return True, [{"thread_id": "1", "address": "+1234567890", "date": "1700000000000"}], ""
        if uri == phone.SMS_INBOX_URI:
            return True, [{"thread_id": "1"}], ""
        return True, [], ""

    monkeypatch.setattr(phone, "content_query", fake_query)
    monkeypatch.setattr(phone, "contacts", lambda serial: {})
    rows, error = phone.threads("SERIAL")
    assert error == ""
    assert rows[0]["thread_id"] == "1"
    assert rows[0]["unread"] == 1
    assert rows[0]["label"] == "+1234567890"


def test_calls_resolve_names_from_contacts(monkeypatch):
    def fake_query(serial, uri, projection=None, where=None, sort=None):
        if uri == phone.CALL_LOG_URI:
            return True, [{"_id": "5", "number": "+1234567890", "date": "1700000000000",
                           "duration": "42", "type": "3", "new": "1", "name": "NULL"}], ""
        return True, [], ""

    monkeypatch.setattr(phone, "content_query", fake_query)
    names = {phone._number_key("1234567890"): "Ada"}
    rows, error = phone.calls("SERIAL", names)
    assert error == ""
    assert rows[0]["label"] == "Ada (+1234567890)"
    assert rows[0]["kind"] == "missed"
    assert rows[0]["duration"] == "42s"
    assert rows[0]["new"] is True
