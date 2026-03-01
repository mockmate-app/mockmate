"""MockMate interviewer sub-package - re-export root_agent for ADK discovery."""

from .agent import build_agent, root_agent

__all__ = ["build_agent", "root_agent"]
