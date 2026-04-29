"""Tests for tool JSON schema — ensuring OpenAI-compatible schemas."""

import json

from agents.tool import FunctionTool
from copane import tools as tools_module


# Collect all tools — keep in sync so schema tests cover everything
_ALL_TOOLS: list[FunctionTool] = [
    tools_module.read_file,
    tools_module.run_command,
    tools_module.grep_files,
    tools_module.list_files,
    tools_module.get_current_dir,
    tools_module.write_file,
]


# -- tests ---------------------------------------------------------------


class TestToolSchema:
    def test_all_tools_have_schema(self):
        """Every tool must produce a valid JSON schema."""
        for tool in _ALL_TOOLS:
            schema = tool.params_json_schema
            assert schema, f"{tool.name} has no schema"
            assert "type" in schema, f"{tool.name} schema missing 'type'"
            assert schema["type"] == "object", f"{tool.name} schema type not 'object'"

    def test_no_tool_has_config_in_schema(self):
        """'config' must never appear in tool schemas.

        OpenAI requires every schema property to have a 'type' key.
        LangSmith's @traceable adds an untyped 'config' parameter to the
        function signature, which the SDK would otherwise pull into the
        schema. We strip it post-decoration.
        """
        for tool in _ALL_TOOLS:
            schema = tool.params_json_schema
            props = schema.get("properties", {})
            assert "config" not in props, (
                f"{tool.name} schema contains 'config' property — "
                "strip it with _strip_config_from_schema()"
            )

    def test_every_property_has_type(self):
        """Every schema property must have a 'type' for OpenAI compatibility."""
        for tool in _ALL_TOOLS:
            schema = tool.params_json_schema
            props = schema.get("properties", {})
            for prop_name, prop_schema in props.items():
                assert "type" in prop_schema, (
                    f"{tool.name}.{prop_name} missing 'type'"
                )

    def test_required_fields_are_listed(self):
        """Tools should declare their required parameters."""
        for tool in _ALL_TOOLS:
            schema = tool.params_json_schema
            required = schema.get("required", [])
            props = schema.get("properties", {})
            for req in required:
                assert req in props, (
                    f"{tool.name} marks '{req}' required but it's not in properties"
                )

    def test_schema_is_serializable(self):
        """Schema must be JSON-serializable for the OpenAI API."""
        for tool in _ALL_TOOLS:
            schema = tool.params_json_schema
            try:
                json.dumps(schema)
            except (TypeError, ValueError) as e:
                assert False, f"{tool.name} schema not JSON-serializable: {e}"

    def test_tool_names_are_unique(self):
        """No two tools may share the same name."""
        names = [tool.name for tool in _ALL_TOOLS]
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, f"Duplicate tool names: {duplicates}"

    def test_read_file_has_path_required(self):
        schema = tools_module.read_file.params_json_schema
        assert "path" in schema.get("required", [])

    def test_run_command_has_cmd_required(self):
        schema = tools_module.run_command.params_json_schema
        assert "cmd" in schema.get("required", [])
