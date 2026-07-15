from techshort.evidence import assertion_tokens, unsupported_assertion_tokens


def test_assertion_tokens_preserve_units_and_normalize_numbers() -> None:
    assert assertion_tokens("20 ms, 2.0%, 30 Hz, and 10.1234/example") == {
        "20ms",
        "2%",
        "30hz",
        "10.1234/example",
    }
    assert unsupported_assertion_tokens("20 ms and 2.0%", ["20 ms; about 2%"]) == []
    assert unsupported_assertion_tokens("20 Hz", ["20 ms"]) == ["20hz"]
