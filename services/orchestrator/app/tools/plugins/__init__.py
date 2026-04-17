"""
plugins/ – drop-in directory for third-party / user-created Lani tools.

How to create a plugin
──────────────────────
1. Create a new .py file here, e.g.  app/tools/plugins/my_tool.py
2. Inside that file define one or more classes that inherit from BaseTool:

    from app.tools.base import BaseTool
    from app.schemas.commands import ToolResult

    class MyTool(BaseTool):
        name        = "my_tool"
        description = "Does something useful."
        parameters  = [{"name": "input", "type": "str", "required": True}]

        async def run(self, **kwargs) -> ToolResult:
            value = kwargs.get("input", "")
            return ToolResult(ok=True, message=f"Got: {value}")

3. Restart the backend – the tool is auto-registered and immediately usable.

No changes to registry.py or any other core file are needed.
"""
