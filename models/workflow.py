"""Workflow data models"""

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Sequence, Tuple


@dataclass
class WorkflowParameter:
    name: str
    placeholder: str
    annotation: type
    description: str
    bindings: list[Tuple[str, str]] = field(default_factory=list)
    required: bool = True


@dataclass
class WorkflowToolDefinition:
    workflow_id: str
    tool_name: str
    description: str
    template: Dict[str, Any]
    parameters: "OrderedDict[str, WorkflowParameter]"
    output_preferences: Sequence[str]
