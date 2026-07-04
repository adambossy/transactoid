"""The production toolset must expose no subprocess-spawning shell tool.

Regression guard for Phase 6 finding F01/F06: the `bash` tool delegated to
``InProcessSandbox.exec``, which spawns a subprocess with the full server
``os.environ`` (threat model "none"). Under open multi-tenant signup any user
could run ``bash(["env"])`` and exfiltrate every secret. The tool was removed;
this test fails if any shell/exec tool is re-registered without a review.
"""

from penny.tools.registry import build_toolset

# Names that would (re)introduce a subprocess-spawning surface.
_FORBIDDEN_TOOL_NAMES = {"bash", "shell", "sh", "exec", "execute_shell", "run_shell"}


def test_toolset_has_no_shell_tool():
    names = {tool.name for tool in build_toolset().tools}
    leaked = names & _FORBIDDEN_TOOL_NAMES
    assert not leaked, f"shell-exec tool(s) back in the toolset: {sorted(leaked)}"


def test_bash_module_is_gone():
    # The module itself was deleted so nothing can import and re-register it.
    import importlib.util

    assert importlib.util.find_spec("penny.tools.bash") is None
