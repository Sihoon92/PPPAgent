"""Contract between the layout schema and write_slide.

The MCP server hands a layout's content schema to the model, then validates
what the model writes back. Both halves of that contract are checked here.
"""

from pptagent.mcp_server import mcp_slide_validate
from pptagent.presentation.layout import Element, Layout
from pptagent.response.pptgen import EditorOutput, SlideElement
from pptagent.utils import Language


def make_layout() -> Layout:
    return Layout(
        title="opening",
        template_id=0,
        slides=[0],
        elements=[
            Element(name="main title", data=["Hello"], type="text"),
            Element(name="presenter", data=["Someone"], type="text"),
        ],
    )


def test_schema_spells_out_the_type_field():
    # The model reads this schema. A tab escape that eats the "t" of "type"
    # leaves it reading "ype: text".
    schema = Element(name="main title", data=["Hello"], type="text").get_schema()
    assert "\ttype: text" in schema


def test_a_missing_element_is_reported_rather_than_raised():
    partial = EditorOutput(elements=[SlideElement(name="main title", data=["Hi"])])
    _, errors = mcp_slide_validate(partial, make_layout(), Language(lid="en"))
    assert any("presenter" in e for e in errors)
