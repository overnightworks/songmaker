"""The tool catalog a host lends the provider layer.

This package executes no tool and knows no tool name. The host declares
which tools exist, how each one is described to a model, and the JSON
schema each one accepts; the provider layer renders that declaration into
a prompt, validates what the model asks for against it, and hands the call
back to the host's executor.

The text protocol's markers carry a brand, so they are declared here too
(issue #825, ruling e). Their default is songmaker's own wording, so a host
that declares nothing renders the prompt this package shipped with, byte
for byte.

Self-contained by design: pydantic only, no application import, so the
package can be released on its own.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_TAG_NAMESPACE = "songmaker"
_DEFAULT_PRODUCT_NAME = "Songmaker"


class ToolDeclaration(BaseModel):
    """One tool as a model sees it: its name, its purpose, its arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any]


class ToolProtocolMarkup(BaseModel):
    """The brand the text tool protocol wears in its markers and its prose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_namespace: str = Field(default=_DEFAULT_TAG_NAMESPACE, min_length=1)
    product_name: str = Field(default=_DEFAULT_PRODUCT_NAME, min_length=1)

    @property
    def call_open_tag(self) -> str:
        return f"<{self.tag_namespace}_tool_call>"

    @property
    def call_close_tag(self) -> str:
        return f"</{self.tag_namespace}_tool_call>"

    @property
    def result_open_tag(self) -> str:
        return f"<{self.tag_namespace}_tool_result>"

    @property
    def result_close_tag(self) -> str:
        return f"</{self.tag_namespace}_tool_result>"

    @property
    def opening_line_lf(self) -> str:
        return f"{self.call_open_tag}\n"

    @property
    def opening_line_crlf(self) -> str:
        return f"{self.call_open_tag}\r\n"


class ToolCatalog(BaseModel):
    """Every tool a turn may reach, in the order a model is shown them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tools: tuple[ToolDeclaration, ...] = Field(min_length=1)
    markup: ToolProtocolMarkup = ToolProtocolMarkup()

    def declaration(self, name: str) -> ToolDeclaration | None:
        """Return the declared tool of that name, or nothing if undeclared."""
        return next((tool for tool in self.tools if tool.name == name), None)
