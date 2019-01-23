from testdata_pb2 import DESCRIPTOR

import protopad

TEST_MESSAGE = DESCRIPTOR.message_types_by_name["TestMessage"]
OUTER = DESCRIPTOR.message_types_by_name["Outer"]
INNER = DESCRIPTOR.message_types_by_name["Inner"]

class TestParseAnyInput:

    def test_parse_valid_json(self):
        json = b'{ "text": "Hello, World!" }'
        result = protopad.parse_any_input(json, TEST_MESSAGE, None)
        assert result.text == "Hello, World!"

    def test_parse_valid_json_with_inner_number(self):
        json = b'{ "inner": { "number": 5 } }'
        result = protopad.parse_any_input(json, OUTER, INNER)
        inner_result = protopad.parse_any_input(result.inner, INNER, None)
        assert inner_result.number == 5

    def test_parse_valid_json_with_inner_text(self):
        json = b'{ "inner": { "text": "Five" } }'
        result = protopad.parse_any_input(json, OUTER, TEST_MESSAGE)
        inner_result = protopad.parse_any_input(result.inner, TEST_MESSAGE, None)
        assert inner_result.text == "Five"
